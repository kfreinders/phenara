import json
from datetime import datetime, timezone

import pytest

from gui.services.experiment_exports import (
    ExperimentExportError,
    capture_image_path,
)
from scripts.scheduling.run_store import RunArchive
from scripts.scheduling.schedule import Schedule


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def schedule():
    return Schedule.create(
        start_date="2026-07-31",
        num_days=1,
        times=["12:00"],
        run={
            "id": "f65e5f45-1111-4222-8333-123456789abc",
            "name": "Control",
            "created_at": NOW.isoformat(),
        },
    )


def snapshot(configured):
    return {"hash": "a" * 64, **configured.to_dict()}


def test_resolves_successful_capture_from_matching_run_ledger(tmp_path):
    configured = schedule()
    archive = RunArchive(tmp_path, configured, "a" * 64, [NOW])
    image = archive.capture_path(NOW)
    image.write_bytes(b"jpeg")
    archive.record(
        scheduled_at=NOW,
        status="succeeded",
        message="ok",
        image_path=image,
    )

    assert capture_image_path(tmp_path, snapshot(configured), NOW) == image


def test_resolves_legacy_successful_capture_without_recorded_image_path(tmp_path):
    configured = schedule()
    archive = RunArchive(tmp_path, configured, "a" * 64, [NOW])
    image = archive.capture_path(NOW)
    image.write_bytes(b"jpeg")
    archive.record(scheduled_at=NOW, status="succeeded", message="ok")

    assert capture_image_path(tmp_path, snapshot(configured), NOW) == image


def test_rejects_missing_failed_and_unsafe_capture_images(tmp_path):
    configured = schedule()
    archive = RunArchive(tmp_path, configured, "a" * 64, [NOW])
    archive.record(scheduled_at=NOW, status="failed", message="camera error")

    with pytest.raises(ExperimentExportError, match="No image"):
        capture_image_path(tmp_path, snapshot(configured), NOW)

    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"jpeg")
    archive.events_path.write_text(json.dumps({
        "version": 1,
        "capture_id": NOW.isoformat(),
        "status": "succeeded",
        "image_path": "../outside.jpg",
    }) + "\n")

    with pytest.raises(ExperimentExportError, match="unsafe"):
        capture_image_path(tmp_path, snapshot(configured), NOW)
