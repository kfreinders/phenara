from datetime import date

import pytest
from fastapi import HTTPException

from gui.app import app
from gui.routes import development as development_routes
from gui.routes import scheduler as scheduler_routes
from gui.services.schedule_drafts import persist_schedule_draft
from gui.services.schedule_form import ScheduleFormData


FRONTEND = (
    __import__("phenara.config", fromlist=["PROJECT_ROOT"]).PROJECT_ROOT
    / "gui"
    / "frontend"
    / "src"
)


def draft_form() -> ScheduleFormData:
    return ScheduleFormData(
        mode="every",
        experiment_name="Navigation test",
        start_date=date.today().isoformat(),
        num_days=2,
        replicates=1,
        replicate_interval_seconds=0,
        every_start="09:00",
        every_end="10:00",
        every_step_minutes=30,
    )


def test_header_keeps_experiment_steps_out_of_the_main_navigation():
    app_source = (FRONTEND / "App.jsx").read_text()
    components = (FRONTEND / "components.jsx").read_text()

    assert "function Navigation" not in components
    assert "<Navigation" not in app_source


def test_camera_alignment_is_a_guarded_schedule_step():
    source = (FRONTEND / "pages" / "CameraPage.jsx").read_text()

    assert 'params.get("workflow") !== "schedule"' in source
    assert '"/api/schedule/draft/camera"' in source
    assert '{ method: "POST" }' in source
    assert "acquireCameraPreview" in source
    assert "getUserMedia" not in source
    assert "Confirm alignment" in source
    assert (
        'analysisEnabled ? "/analysis?workflow=schedule" : "/schedule/review"'
        in source
    )
    assert "<WorkflowSteps current={3}" in source
    assert 'updated.analysis_requested' in source


def test_spa_fallback_and_all_user_routes_are_registered_in_react():
    assert str(app.url_path_for("react_app", path="scheduler")) == "/scheduler"
    source = (FRONTEND / "App.jsx").read_text()
    for route in (
        'path="scheduler"',
        'path="schedule"',
        'path="schedule/edit"',
        'path="schedule/build"',
        'path="schedule/build/edit"',
        'path="schedule/review"',
        'path="schedule/activation"',
        'path="camera"',
        'path="experiments/:runId"',
    ):
        assert route in source


def test_development_capture_controls_are_registered_and_visible():
    assert (
        str(app.url_path_for("get_development_status"))
        == "/api/development/status"
    )
    assert (
        str(app.url_path_for("acquire_camera_preview"))
        == "/api/camera/preview"
    )
    source = (FRONTEND / "App.jsx").read_text()
    assert "Enable development mode" in source
    assert "Development mode on" in source
    assert "Use sample images" in source
    assert "development?.available" in source


def test_development_mode_api_is_unavailable_without_deploy_flag(monkeypatch):
    monkeypatch.setattr(development_routes, "DEVELOPMENT_AVAILABLE", False)

    assert development_routes.get_development_status() == {"available": False}
    with pytest.raises(HTTPException) as unavailable:
        development_routes.update_development_status(
            development_routes.DevelopmentModeRequest(enabled=True)
        )
    assert unavailable.value.status_code == 404


def test_activation_page_rejects_a_malformed_schedule_hash():
    source = (FRONTEND / "pages" / "ActivationPage.jsx").read_text()

    assert "/^[0-9a-f]{64}$/" in source
    assert "Invalid activation link" in source


def test_scheduler_api_reports_ready_invalid_and_missing_drafts(
    tmp_path, monkeypatch
):
    draft_path = tmp_path / "schedule-draft.json"
    monkeypatch.setattr(scheduler_routes, "SCHEDULE_DRAFT_PATH", draft_path)

    assert scheduler_routes.schedule_draft_state() == "none"
    draft_path.write_text("")
    assert scheduler_routes.schedule_draft_state() == "invalid"
    persist_schedule_draft(draft_form(), draft_path)
    assert scheduler_routes.scheduler_status_api()["draft_state"] == "ready"


def test_scheduler_page_has_context_sensitive_next_actions():
    source = (FRONTEND / "pages" / "SchedulerPage.jsx").read_text()

    assert 'draftState === "ready"' in source
    assert 'draftState === "invalid"' in source
    assert 'schedule?.lifecycle !== "finished"' in source
    assert "Review draft" in source
    assert "Experiment finished with capture issues" in source
    assert "Download experiment data" in source
    assert "Replace schedule…" in source


def test_cancel_api_requires_a_healthy_matching_active_schedule(
    tmp_path, monkeypatch
):
    command_path = tmp_path / "scheduler-command.json"
    schedule_hash = "c" * 64
    monkeypatch.setattr(scheduler_routes, "SCHEDULER_COMMAND_PATH", command_path)
    monkeypatch.setattr(
        scheduler_routes,
        "read_scheduler_status",
        lambda path: {
            "status": "healthy",
            "schedule": {"hash": schedule_hash, "lifecycle": "active"},
        },
    )

    response = scheduler_routes.cancel_scheduled_experiment(
        scheduler_routes.CancellationRequest(schedule_hash=schedule_hash)
    )

    assert response["accepted"] is True
    assert command_path.exists()
    assert scheduler_routes._cancellation_pending(schedule_hash) is True

    with pytest.raises(HTTPException) as mismatch:
        scheduler_routes.cancel_scheduled_experiment(
            scheduler_routes.CancellationRequest(schedule_hash="d" * 64)
        )
    assert mismatch.value.status_code == 409


def test_cancel_api_accepts_an_upcoming_schedule(tmp_path, monkeypatch):
    command_path = tmp_path / "scheduler-command.json"
    schedule_hash = "e" * 64
    monkeypatch.setattr(scheduler_routes, "SCHEDULER_COMMAND_PATH", command_path)
    monkeypatch.setattr(
        scheduler_routes,
        "read_scheduler_status",
        lambda path: {
            "status": "healthy",
            "schedule": {"hash": schedule_hash, "lifecycle": "upcoming"},
        },
    )

    response = scheduler_routes.cancel_scheduled_experiment(
        scheduler_routes.CancellationRequest(schedule_hash=schedule_hash)
    )

    assert response["accepted"] is True
    assert scheduler_routes._cancellation_pending(schedule_hash) is True
