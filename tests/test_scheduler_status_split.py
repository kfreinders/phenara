import json
from datetime import datetime, timezone

import pytest

from gui.services.scheduler_status import read_scheduler_health, read_scheduler_status


NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


def write_compact_heartbeat(path):
    path.write_text(json.dumps({
        "version": 2,
        "timestamp": NOW.isoformat(),
        "state": "running",
        "message": "Scheduler is running.",
    }))


@pytest.mark.parametrize("status_contents", [None, "not json", "{}"])
def test_bad_detailed_status_preserves_health_and_returns_warning(
    tmp_path,
    status_contents,
):
    heartbeat_path = tmp_path / "scheduler-heartbeat.json"
    write_compact_heartbeat(heartbeat_path)
    if status_contents is not None:
        (tmp_path / "scheduler-status.json").write_text(status_contents)

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == "healthy"
    assert result["schedule"] is None
    assert result["schedule_error"] == "Detailed scheduler status is unavailable."
    assert read_scheduler_health(heartbeat_path, now=NOW)["status"] == "healthy"


def test_split_status_preserves_existing_service_contract(tmp_path):
    heartbeat_path = tmp_path / "scheduler-heartbeat.json"
    write_compact_heartbeat(heartbeat_path)
    (tmp_path / "scheduler-status.json").write_text(json.dumps({
        "version": 1,
        "schedule": None,
        "last_capture": {"status": "succeeded"},
        "capture_summary": {"succeeded": 1},
        "recent_captures": [{"status": "succeeded"}],
        "daily_capture_progress": {"points": []},
        "analysis_summary": {"succeeded": 1},
        "storage": {"free_bytes": 100},
    }))

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["schedule_error"] is None
    assert result["last_capture"] == {"status": "succeeded"}
    assert result["capture_summary"] == {"succeeded": 1}
    assert result["recent_captures"] == [{"status": "succeeded"}]
    assert result["daily_capture_progress"] == {"points": []}
    assert result["analysis_summary"] == {"succeeded": 1}
    assert result["storage"] == {"free_bytes": 100}
