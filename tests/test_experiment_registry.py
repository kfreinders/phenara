from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from scripts.scheduling.experiment_registry import ExperimentRegistry
from scripts.scheduling.run_store import RunArchive


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc).isoformat()


def schedule(run_id="00000000-0000-4000-8000-000000000001"):
    return {
        "start_date": "2026-08-13", "num_days": 1, "times": ["12:00"],
        "run": {"id": run_id, "name": "Plants", "researcher": "Koen",
                "notes": None, "created_at": NOW},
    }


def test_registry_round_trips_reproducible_metadata(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.register(schedule=schedule(), schedule_hash="a" * 64,
                      dataset_name="dataset")
    registry.update_terminal(schedule()["run"]["id"], state="completed",
                             ended_at=NOW, capture_summary={"succeeded": 1})

    row = registry.get(schedule()["run"]["id"])

    assert row["schedule"] == schedule()
    assert row["capture_summary"] == {"succeeded": 1}
    assert registry.retention()["raw_data_blockers"][0]["run_id"] == row["run_id"]


@pytest.mark.parametrize("replacement_hash", ["b" * 64, "a" * 64])
def test_registry_rejects_reusing_run_id_for_another_schedule(
    tmp_path,
    replacement_hash,
):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    original = schedule()
    replacement = schedule()
    replacement["run"]["name"] = "Different experiment"
    registry.register(
        schedule=original,
        schedule_hash="a" * 64,
        dataset_name="original",
    )

    with pytest.raises(ValueError, match="another schedule"):
        registry.register(
            schedule=replacement,
            schedule_hash=replacement_hash,
            dataset_name="replacement",
        )

    row = registry.get(original["run"]["id"])
    assert row["schedule_hash"] == "a" * 64
    assert row["schedule"] == original
    assert row["dataset_name"] == "original"


def test_reconcile_warns_without_overwriting_duplicate_run_id(tmp_path):
    output_root = tmp_path / "captures"
    original = schedule()
    replacement = schedule()
    replacement["run"]["name"] = "Different experiment"
    for directory_name, configured, schedule_hash in (
        ("a-original", original, "a" * 64),
        ("b-replacement", replacement, "b" * 64),
    ):
        directory = output_root / directory_name
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps({
            "run": configured["run"],
            "schedule": configured,
            "schedule_hash": schedule_hash,
            "state": "active",
            "loaded_at": NOW,
        }))
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")

    warnings = registry.reconcile(output_root)

    row = registry.get(original["run"]["id"])
    assert row["schedule_hash"] == "a" * 64
    assert row["dataset_name"] == "a-original"
    assert warnings == [
        "b-replacement: This run ID is already associated with another schedule."
    ]


def test_deleted_metadata_is_retained_without_raw_data(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.register(schedule=schedule(), schedule_hash="a" * 64,
                      dataset_name="dataset", state="completed", ended_at=NOW)
    registry.mark_deleted(schedule()["run"]["id"], archive_name="run.zip",
                          archive_size_bytes=12, archive_sha256="f" * 64,
                          exported_at=NOW, deleted_at=NOW)

    row = registry.get(schedule()["run"]["id"])
    assert row["data_present"] is False
    assert row["archive_sha256"] == "f" * 64
    assert registry.retention()["can_activate"] is True


def test_run_archive_records_terminal_outcome(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    archive = RunArchive(
        tmp_path / "captures", schedule(), "a" * 64, [], registry
    )
    archive.mark_ended("cancelled")

    row = registry.get(schedule()["run"]["id"])
    assert row["state"] == "cancelled"
    assert row["capture_summary"]["total"] == 0


def test_run_archive_records_terminal_analysis_summary(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    archive = RunArchive(
        tmp_path / "captures", schedule(), "a" * 64, [], registry
    )
    analysis = {"total": 2, "succeeded": 2, "failed": 0}

    archive.mark_ended("completed", analysis_summary=analysis)

    assert registry.get(schedule()["run"]["id"])["analysis_summary"] == analysis
    assert json.loads(archive.manifest_path.read_text())["analysis_summary"] == analysis


def test_reconcile_preserves_analysis_summary_for_legacy_manifest(tmp_path):
    output_root = tmp_path / "captures"
    archive = RunArchive(output_root, schedule(), "a" * 64, [])
    archive.mark_ended("completed")
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.register(
        schedule=schedule(),
        schedule_hash="a" * 64,
        dataset_name=archive.directory.name,
        state="completed",
        ended_at=NOW,
    )
    registry.update_terminal(
        schedule()["run"]["id"],
        state="completed",
        ended_at=NOW,
        capture_summary={"total": 0},
        analysis_summary={"total": 1, "succeeded": 1},
    )
    manifest = json.loads(archive.manifest_path.read_text())
    manifest.pop("analysis_summary", None)
    archive.manifest_path.write_text(json.dumps(manifest))

    registry.reconcile(output_root)

    assert registry.get(schedule()["run"]["id"])["analysis_summary"] == {
        "total": 1,
        "succeeded": 1,
    }


def test_empty_superseded_run_is_not_retained(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    archive = RunArchive(
        tmp_path / "captures", schedule(), "a" * 64, [], registry
    )
    archive.mark_ended("superseded", superseded_by="replacement")

    assert registry.get(schedule()["run"]["id"]) is None


def test_export_metadata_is_persisted_before_cleanup(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    registry.register(schedule=schedule(), schedule_hash="a" * 64,
                      dataset_name="dataset", state="completed", ended_at=NOW)

    registry.record_export(schedule()["run"]["id"], archive_name="run.zip",
                           archive_size_bytes=20, archive_sha256="e" * 64,
                           exported_at=NOW)

    row = registry.get(schedule()["run"]["id"])
    assert row["data_present"] is True
    assert row["archive_ready"] is True
    assert row["archive_sha256"] == "e" * 64


def test_registry_prunes_only_cleaned_records_beyond_200(tmp_path):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    raw_run_id = str(UUID(int=1))
    for number in range(1, 202):
        run_id = str(UUID(int=number))
        configured = schedule(run_id)
        configured["run"]["created_at"] = (
            f"2026-08-13T00:{number // 60:02d}:{number % 60:02d}+00:00"
        )
        registry.register(
            schedule=configured,
            schedule_hash=f"{number:064x}",
            dataset_name=f"dataset-{number}",
            state="completed",
            ended_at=configured["run"]["created_at"],
        )
        if run_id != raw_run_id:
            registry.mark_deleted(
                run_id,
                archive_name=f"{number}.zip",
                archive_size_bytes=number,
                archive_sha256=f"{number:064x}",
                exported_at=configured["run"]["created_at"],
                deleted_at=configured["run"]["created_at"],
            )

    assert registry.get(raw_run_id)["data_present"] is True
    assert registry.retention()["retained_terminal_count"] == 200


def test_rebuild_restores_only_the_latest_200_deleted_records(tmp_path):
    deleted_root = tmp_path / "captures" / ".phenara-deleted-runs"
    deleted_root.mkdir(parents=True)
    run_ids = []
    for number in range(1, 202):
        run_id = str(UUID(int=number))
        run_ids.append(run_id)
        configured = schedule(run_id)
        timestamp = f"2026-08-13T00:{number // 60:02d}:{number % 60:02d}+00:00"
        configured["run"]["created_at"] = timestamp
        marker = {
            "version": 2,
            "run_id": run_id,
            "schedule_hash": f"{number:064x}",
            "deleted_at": timestamp,
            "experiment": {
                "schedule": configured,
                "schedule_hash": f"{number:064x}",
                "dataset_name": f"dataset-{number}",
                "state": "completed",
                "loaded_at": timestamp,
                "ended_at": timestamp,
                "superseded_by": None,
                "capture_summary": {"total": 1, "succeeded": 1},
                "analysis_summary": None,
                "archive_name": f"dataset-{number}.zip",
                "archive_size_bytes": number,
                "archive_sha256": f"{number:064x}",
                "exported_at": timestamp,
            },
        }
        (deleted_root / f"{run_id}.json").write_text(json.dumps(marker))

    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    warnings = registry.reconcile(tmp_path / "captures")

    assert warnings == []
    assert registry.retention()["retained_terminal_count"] == 200
    assert registry.get(run_ids[0]) is None
    assert registry.get(run_ids[-1])["data_present"] is False
    assert len(list(deleted_root.glob("*.json"))) == 200
