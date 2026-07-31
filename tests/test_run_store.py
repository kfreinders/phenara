import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zipfile import ZipFile

import pytest

from scripts.analysis.config import AnalysisConfig
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.roi import RoiCircle, RoiDefinition
from scripts.scheduling.run_store import RunArchive, run_directory_name


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def schedule(run_id=None, **overrides):
    value = {
        "start_date": "2026-07-22",
        "num_days": 1,
        "times": ["11:00", "13:00"],
        "replicates": 1,
        "replicate_interval_seconds": 0,
        "run": {
            "id": run_id or str(uuid4()),
            "name": "Drought response / tray A",
            "researcher": "Researcher One",
            "notes": None,
            "created_at": NOW.isoformat(),
        },
    }
    value.update(overrides)
    return value


def test_run_archive_creates_portable_manifest_and_safe_directory(tmp_path):
    configured = schedule()
    archive = RunArchive(tmp_path, configured, "a" * 64, [NOW])

    manifest = json.loads(archive.manifest_path.read_text())
    assert archive.directory.name == run_directory_name(
        configured["start_date"], configured["run"]
    )
    assert "/" not in archive.directory.name
    assert manifest["run"] == configured["run"]
    assert manifest["schedule_hash"] == "a" * 64
    assert manifest["state"] == "active"


def test_run_archive_materializes_attached_analysis_profile(tmp_path):
    config = AnalysisConfig(roi_rows=1, roi_cols=1)
    profile = AnalysisProfile(
        1,
        config,
        RoiDefinition(
            2,
            1,
            1,
            100,
            100,
            config.fingerprint,
            (RoiCircle(0, 0, 0.5, 0.5, 0.2),),
        ),
    )

    archive = RunArchive(
        tmp_path,
        schedule(analysis=profile.to_dict()),
        "a" * 64,
        [NOW],
    )

    assert AnalysisConfig.load(
        archive.analysis_dir / "analysis-config.json"
    ) == config
    assert RoiDefinition.load(
        archive.analysis_dir / "roi-definition.json"
    ) == profile.roi


def test_capture_ledger_reconstructs_latest_results_and_summary(tmp_path):
    past = NOW - timedelta(hours=1)
    future = NOW + timedelta(hours=1)
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [past, future])
    archive.record(
        scheduled_at=past,
        status="failed",
        message="camera unavailable",
    )
    archive.record(
        scheduled_at=past,
        status="succeeded",
        message="capture job succeeded on retry",
    )

    payload = archive.status_payload(NOW)

    assert payload["summary"] == {
        "total": 2,
        "succeeded": 1,
        "failed": 0,
        "missed": 0,
        "remaining": 1,
        "elapsed_unreported": 0,
    }
    assert payload["last"]["status"] == "succeeded"


def test_capture_ledger_records_a_portable_image_path(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])
    image_path = archive.capture_path(NOW)
    image_path.touch()

    event = archive.record(
        scheduled_at=NOW,
        status="succeeded",
        message="ok",
        image_path=image_path,
    )

    assert event["image_path"] == "capture_20260722_120000.jpg"


def test_capture_ledger_rejects_images_outside_the_run(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])

    with pytest.raises(ValueError, match="inside the run directory"):
        archive.record(
            scheduled_at=NOW,
            status="succeeded",
            message="ok",
            image_path=tmp_path / "other.jpg",
        )


def test_run_archive_records_unreported_past_captures_as_missed(tmp_path):
    past = NOW - timedelta(hours=1)
    future = NOW + timedelta(hours=1)
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [past, future])

    archive.record_unreported_past(NOW)

    assert archive.status_payload(NOW)["summary"]["missed"] == 1


def test_run_archive_does_not_mark_recoverable_grace_window_capture_missed(
    tmp_path,
):
    too_old = NOW - timedelta(minutes=11)
    recoverable = NOW - timedelta(minutes=5)
    archive = RunArchive(
        tmp_path,
        schedule(),
        "a" * 64,
        [too_old, recoverable],
    )

    archive.record_unreported_past(
        NOW,
        cutoff=NOW - timedelta(minutes=10),
    )

    payload = archive.status_payload(NOW)
    assert payload["summary"]["missed"] == 1
    assert payload["summary"]["elapsed_unreported"] == 1


def test_status_payload_groups_current_day_results_by_time_point(tmp_path):
    configured = schedule(replicates=2, replicate_interval_seconds=10)
    expected = [
        NOW - timedelta(hours=1),
        NOW - timedelta(hours=1) + timedelta(seconds=10),
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=1) + timedelta(seconds=10),
    ]
    archive = RunArchive(tmp_path, configured, "a" * 64, expected)
    archive.record(scheduled_at=expected[0], status="succeeded", message="ok")
    archive.record(scheduled_at=expected[1], status="failed", message="camera error")

    progress = archive.status_payload(NOW)["daily_progress"]

    assert progress["date"] == NOW.date().isoformat()
    assert progress["is_today"] is True
    assert [point["status"] for point in progress["points"]] == ["failed", "remaining"]
    assert progress["points"][0]["counts"]["succeeded"] == 1
    assert progress["points"][0]["message"] == "camera error"
    assert progress["points"][0]["captures"] == [
        {
            "scheduled_at": expected[0].isoformat(),
            "time": expected[0].strftime("%H:%M:%S"),
            "replicate": 1,
            "status": "succeeded",
            "message": "ok",
            "image_available": False,
        },
        {
            "scheduled_at": expected[1].isoformat(),
            "time": expected[1].strftime("%H:%M:%S"),
            "replicate": 2,
            "status": "failed",
            "message": "camera error",
            "image_available": False,
        },
    ]


def test_capture_ledger_ignores_only_an_interrupted_final_line(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])
    archive.record(scheduled_at=NOW, status="succeeded", message="ok")
    with archive.events_path.open("a") as output:
        output.write('{"version":')

    assert len(archive.events()) == 1

    archive.events_path.write_text('{"bad":true}\n{"version":')
    with pytest.raises(ValueError, match="invalid event"):
        archive.events()


def test_run_id_cannot_be_reused_for_another_schedule(tmp_path):
    configured = schedule()
    RunArchive(tmp_path, configured, "a" * 64, [NOW])

    with pytest.raises(ValueError, match="another schedule"):
        RunArchive(tmp_path, configured, "b" * 64, [NOW])


def test_run_can_be_marked_superseded(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])

    archive.mark_ended("superseded", superseded_by=str(uuid4()))

    manifest = json.loads(archive.manifest_path.read_text())
    assert manifest["state"] == "superseded"
    assert manifest["ended_at"] is not None
    assert manifest["superseded_by"] is not None


def test_run_can_be_marked_cancelled(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])

    archive.mark_ended("cancelled")

    manifest = json.loads(archive.manifest_path.read_text())
    assert manifest["state"] == "cancelled"
    assert manifest["ended_at"] is not None
    assert manifest["superseded_by"] is None


def test_completed_run_creates_portable_zip_archive(tmp_path):
    archive = RunArchive(tmp_path, schedule(), "a" * 64, [NOW])
    capture = archive.directory / "capture_20260722_120000.jpg"
    capture.write_bytes(b"image")

    archive.mark_ended("completed")
    archive._archive_thread.join(timeout=5)

    assert archive.archive_path.exists()
    with ZipFile(archive.archive_path) as downloaded:
        names = set(downloaded.namelist())
        assert f"{archive.directory.name}/run.json" in names
        assert f"{archive.directory.name}/{capture.name}" in names
        manifest = json.loads(
            downloaded.read(f"{archive.directory.name}/run.json")
        )
    assert manifest["state"] == "completed"
