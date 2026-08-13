from datetime import datetime, timezone

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
