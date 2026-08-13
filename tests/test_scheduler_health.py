import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from gui.app import app
from phenopi.config import PROJECT_ROOT
from gui.services.scheduler_status import (
    build_daily_activity,
    build_schedule_overview,
    read_scheduler_health,
    read_scheduler_status,
)
from scripts.scheduling.heartbeat import SchedulerHeartbeat


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
APP_DIR = PROJECT_ROOT / "gui"


def write_heartbeat(
    path,
    *,
    state,
    age_seconds=0,
    message="state message",
    schedule=None,
    last_capture=None,
    storage=None,
    capture_summary=None,
    analysis_summary=None,
    recent_captures=None,
):
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "timestamp": (NOW - timedelta(seconds=age_seconds)).isoformat(),
                "state": state,
                "message": message,
            }
        )
    )
    path.with_name("scheduler-status.json").write_text(
        json.dumps(
            {
                "version": 1,
                "schedule": schedule,
                "last_capture": last_capture,
                "storage": storage,
                "capture_summary": capture_summary,
                "analysis_summary": analysis_summary,
                "recent_captures": recent_captures or [],
                "daily_capture_progress": None,
            }
        )
    )


def test_heartbeat_atomically_writes_current_state(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)

    assert heartbeat.set_state("running", "Scheduler is running.") is True

    payload = json.loads(heartbeat.path.read_text())
    assert payload["version"] == 2
    assert payload["state"] == "running"
    assert payload["message"] == "Scheduler is running."
    assert set(payload) == {"version", "timestamp", "state", "message"}
    assert payload["timestamp"].endswith("+00:00")
    assert set(tmp_path.iterdir()) == {heartbeat.path, heartbeat.status_path}


def test_heartbeat_rejects_unknown_state(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        SchedulerHeartbeat(tmp_path).set_state("unknown", "message")


def test_heartbeat_retains_or_clears_loaded_schedule(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)
    snapshot = schedule_snapshot()
    heartbeat.set_state("running", "running", schedule=snapshot)

    heartbeat.set_state("invalid_schedule", "rejected edit")
    assert json.loads(heartbeat.status_path.read_text())["schedule"] == snapshot

    heartbeat.set_state(
        "waiting_for_schedule",
        "waiting",
        schedule=None,
    )
    assert json.loads(heartbeat.status_path.read_text())["schedule"] is None


def test_heartbeat_write_failure_is_non_fatal(tmp_path):
    runtime_path = tmp_path / "runtime-file"
    runtime_path.write_text("not a directory")

    assert SchedulerHeartbeat(runtime_path).write() is False


def test_heartbeat_reports_capture_storage(tmp_path, monkeypatch):
    usage = shutil._ntuple_diskusage(1000, 600, 400)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)
    heartbeat = SchedulerHeartbeat(tmp_path, storage_path=tmp_path / "captures")

    heartbeat.write()

    storage = json.loads(heartbeat.status_path.read_text())["storage"]
    assert storage == {
        "total_bytes": 1000,
        "used_bytes": 600,
        "free_bytes": 400,
        "used_percent": 60.0,
    }


def test_heartbeat_publishes_capture_ledger_summary(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)
    summary = {
        "total": 2,
        "succeeded": 1,
        "failed": 0,
        "missed": 0,
        "remaining": 1,
        "elapsed_unreported": 0,
    }
    recent = [{"status": "succeeded", "scheduled_at": NOW.isoformat()}]
    analysis = {"total": 1, "succeeded": 1, "pending": 0}
    heartbeat.set_capture_status_provider(
        lambda: {
            "summary": summary,
            "recent": recent,
            "last": recent[0],
            "daily_progress": {"date": "2026-07-22", "points": []},
            "analysis": analysis,
        }
    )

    heartbeat.write()

    payload = json.loads(heartbeat.status_path.read_text())
    assert payload["capture_summary"] == summary
    assert payload["recent_captures"] == recent
    assert payload["last_capture"] == recent[0]
    assert payload["daily_capture_progress"]["date"] == "2026-07-22"
    assert payload["analysis_summary"] == analysis


def test_heartbeat_restores_capture_for_same_schedule(tmp_path):
    previous = {
        "schedule_hash": "abcdef1234567890",
        "status": "succeeded",
    }
    (tmp_path / "scheduler-heartbeat.json").write_text(
        json.dumps({"version": 1, "last_capture": previous})
    )
    heartbeat = SchedulerHeartbeat(tmp_path)

    heartbeat.set_state("running", "running", schedule=schedule_snapshot())

    assert json.loads(heartbeat.status_path.read_text())["last_capture"] == previous


def test_heartbeat_clears_capture_for_replacement_schedule(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)
    heartbeat.record_capture({"schedule_hash": "old", "status": "succeeded"})

    heartbeat.set_state("running", "running", schedule=schedule_snapshot())

    assert json.loads(heartbeat.status_path.read_text())["last_capture"] is None


@pytest.mark.parametrize(
    ("state", "expected_status"),
    [
        ("running", "healthy"),
        ("waiting_for_schedule", "waiting_for_schedule"),
        ("invalid_schedule", "invalid_schedule"),
    ],
)
def test_status_maps_fresh_scheduler_states(
    tmp_path, state, expected_status
):
    heartbeat_path = tmp_path / "heartbeat.json"
    write_heartbeat(heartbeat_path, state=state, age_seconds=5)

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == expected_status
    assert result["age_seconds"] == 5.0
    assert result["message"] == "state message"

    health = read_scheduler_health(heartbeat_path, now=NOW)
    assert health == {
        key: result[key]
        for key in ("status", "last_heartbeat_at", "age_seconds", "message")
    }


def test_status_marks_old_heartbeat_stale(tmp_path):
    heartbeat_path = tmp_path / "heartbeat.json"
    write_heartbeat(heartbeat_path, state="running", age_seconds=31)

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == "stale"
    assert result["age_seconds"] == 31.0


def test_status_exposes_optional_capture_and_storage(tmp_path):
    heartbeat_path = tmp_path / "heartbeat.json"
    capture = {"status": "failed", "message": "camera error"}
    storage = {"free_bytes": 100, "used_percent": 90.0}
    summary = {"total": 2, "succeeded": 1}
    analysis = {"total": 1, "succeeded": 0, "pending": 1}
    recent = [{"status": "succeeded"}]
    write_heartbeat(
        heartbeat_path,
        state="running",
        last_capture=capture,
        storage=storage,
        capture_summary=summary,
        analysis_summary=analysis,
        recent_captures=recent,
    )

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["last_capture"] == capture
    assert result["storage"] == storage
    assert result["capture_summary"] == summary
    assert result["analysis_summary"] == analysis
    assert result["recent_captures"] == recent


def schedule_snapshot():
    return {
        "hash": "abcdef1234567890",
        "timezone": "Europe/Amsterdam",
        "start_date": "2026-07-18",
        "num_days": 2,
        "times": ["09:00", "15:00"],
        "replicates": 2,
        "replicate_interval_seconds": 10,
    }


@pytest.mark.parametrize(
    ("now", "lifecycle", "elapsed", "remaining"),
    [
        (datetime(2026, 7, 18, 6, tzinfo=timezone.utc), "upcoming", 0, 8),
        (datetime(2026, 7, 18, 10, tzinfo=timezone.utc), "active", 2, 6),
        (datetime(2026, 7, 20, 10, tzinfo=timezone.utc), "finished", 8, 0),
    ],
)
def test_schedule_overview_lifecycle(now, lifecycle, elapsed, remaining):
    overview = build_schedule_overview(schedule_snapshot(), now=now)

    assert overview["lifecycle"] == lifecycle
    assert overview["elapsed_captures"] == elapsed
    assert overview["remaining_captures"] == remaining
    assert overview["total_captures"] == 8
    assert overview["estimated_remaining_storage_bytes"] == (
        remaining * 7_600_000 * 2
    )


def test_schedule_overview_exposes_valid_run_identity():
    snapshot = schedule_snapshot()
    snapshot["run"] = {
        "id": "7d781e86-49f1-4e70-9c1e-360d051aef90",
        "name": "Tray A drought response",
        "researcher": "Researcher One",
        "notes": None,
        "created_at": NOW.isoformat(),
    }

    overview = build_schedule_overview(snapshot, now=NOW)

    assert overview["run"]["name"] == "Tray A drought response"


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 7, 18, 6, tzinfo=timezone.utc),
        datetime(2026, 7, 18, 16, tzinfo=timezone.utc),
    ],
)
def test_current_calendar_day_is_highlighted_outside_capture_window(now):
    overview = build_schedule_overview(schedule_snapshot(), now=now)

    assert overview["days"][0]["status"] == "current"
    assert overview["days"][1]["status"] == "upcoming"


def test_daily_activity_aggregates_hours_and_window():
    activity = build_daily_activity(
        ["08:00", "08:30", "09:00", "09:30"],
        replicates=3,
    )

    assert len(activity["hours"]) == 24
    assert activity["hours"][8]["time_point_count"] == 2
    assert activity["hours"][8]["capture_count"] == 6
    assert activity["hours"][9]["capture_count"] == 6
    assert activity["hours"][8]["intensity_percent"] == 100.0
    assert activity["window_label"] == "08:00–09:30"
    assert activity["window_minutes"] == 90
    assert activity["window_duration_label"] == "1 hr 30 min"
    assert activity["peak_time_points_per_hour"] == 2
    assert activity["peak_captures_per_hour"] == 6


@pytest.mark.parametrize(
    ("times", "kind", "label"),
    [
        ([], "empty", "No time points"),
        (["08:00"], "single", "Single time point"),
        (["08:00", "08:30", "09:00"], "regular", "Every 30 min"),
        (
            ["08:00", "08:30", "09:00", "09:30", "10:15"],
            "typical",
            "Typically every 30 min",
        ),
        (["08:00", "08:15", "09:00", "10:30"], "variable", "Variable intervals"),
    ],
)
def test_daily_activity_summarizes_cadence(times, kind, label):
    activity = build_daily_activity(times)

    assert activity["cadence_kind"] == kind
    assert activity["cadence_label"] == label


def test_stale_status_retains_last_reported_schedule(tmp_path):
    heartbeat_path = tmp_path / "heartbeat.json"
    write_heartbeat(
        heartbeat_path,
        state="running",
        age_seconds=31,
        schedule=schedule_snapshot(),
    )

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == "stale"
    assert result["schedule"]["lifecycle"] == "active"
    assert result["schedule_is_last_reported"] is True


def test_invalid_schedule_snapshot_does_not_hide_health(tmp_path):
    heartbeat_path = tmp_path / "heartbeat.json"
    write_heartbeat(
        heartbeat_path,
        state="running",
        schedule={"invalid": "snapshot"},
    )

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == "healthy"
    assert result["schedule"] is None
    assert result["schedule_error"] is not None


@pytest.mark.parametrize("contents", [None, "not json", "{}"])
def test_status_marks_missing_or_invalid_heartbeat_unavailable(
    tmp_path, contents
):
    heartbeat_path = tmp_path / "heartbeat.json"
    if contents is not None:
        heartbeat_path.write_text(contents)

    result = read_scheduler_status(heartbeat_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["last_heartbeat_at"] is None
    assert result["age_seconds"] is None

    health = read_scheduler_health(heartbeat_path, now=NOW)
    assert set(health) == {
        "status",
        "last_heartbeat_at",
        "age_seconds",
        "message",
    }
    assert health["status"] == "unavailable"


def test_scheduler_status_routes_are_registered():
    assert str(app.url_path_for("react_app", path="scheduler")) == "/scheduler"
    assert str(app.url_path_for("scheduler_status_api")) == (
        "/api/scheduler/status"
    )
    assert str(app.url_path_for("scheduler_health_api")) == (
        "/api/scheduler/health"
    )


def test_scheduler_dashboard_is_owned_by_the_react_build():
    source = (APP_DIR / "frontend" / "src" / "pages" / "SchedulerPage.jsx").read_text()
    config = (APP_DIR / "frontend" / "vite.config.js").read_text()

    assert "function Dashboard" in source
    assert 'outDir: resolve(import.meta.dirname, "../react-dist")' in config


def test_scheduler_dashboard_has_accessible_storage_meter():
    source = (APP_DIR / "frontend" / "src" / "pages" / "SchedulerPage.jsx").read_text()

    assert 'role="progressbar"' in source
    assert "aria-valuenow={storage.used_percent}" in source
    assert "storage-meter--warning" in source
    assert "storage-meter--critical" in source
    assert "storageRisk" in source


def test_empty_scheduler_state_is_compact_and_has_guided_action():
    scheduler_source = (APP_DIR / "frontend" / "src" / "pages" / "SchedulerPage.jsx").read_text()
    dashboard_styles = (APP_DIR / "static" / "scheduler_status.css").read_text()

    assert "empty-icon" not in scheduler_source
    assert "The scheduler is ready for an experiment schedule." not in scheduler_source
    assert "schedule-cta-pulse" in dashboard_styles
    assert "prefers-reduced-motion" in dashboard_styles


def test_react_build_collects_the_page_styles():
    styles = (APP_DIR / "frontend" / "src" / "styles.css").read_text()

    assert '../../static/style.css' in styles
    assert '../../static/visual_preview.css' in styles
    assert '../../static/scheduler_status.css' in styles
    assert '../../static/camera_preview.css' in styles


def test_global_health_poll_uses_lightweight_endpoint():
    api_source = (APP_DIR / "frontend" / "src" / "api.js").read_text()
    hooks = (APP_DIR / "frontend" / "src" / "hooks.js").read_text()

    assert 'api("/api/scheduler/health")' in api_source
    assert 'api("/api/scheduler/status")' in api_source
    assert "useSchedulerHealth" in hooks
    assert "useSchedulerStatus" in hooks
