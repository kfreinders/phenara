import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from gui.app import app
from phenara.config import PROJECT_ROOT
from gui.routes import schedule_api
from gui.services.schedule_drafts import (
    attach_analysis_profile_to_draft,
    confirm_camera_alignment,
    discard_schedule_draft,
    persist_schedule_draft,
    record_camera_preview,
)
from gui.services.schedule_form import ScheduleFormData
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.roi import RoiCircle, RoiDefinition


FRONTEND = PROJECT_ROOT / "gui" / "frontend" / "src"


def schedule_form_data(**updates) -> ScheduleFormData:
    values = {
        "mode": "every",
        "experiment_name": "Seedling drought response",
        "researcher": "Researcher One",
        "notes": "Tray A",
        "start_date": date.today().isoformat(),
        "num_days": 2,
        "replicates": 2,
        "replicate_interval_seconds": 10,
        "every_start": "09:00",
        "every_end": "10:00",
        "every_step_minutes": 30,
    }
    values.update(updates)
    return ScheduleFormData(**values)


def write_heartbeat(path, *, age_seconds=0, state="waiting_for_schedule", schedule=None, storage=None):
    timestamp = datetime.now(timezone.utc).timestamp() - age_seconds
    path.write_text(json.dumps({
        "version": 2,
        "timestamp": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "state": state,
        "message": "test scheduler state",
    }))
    path.with_name("scheduler-status.json").write_text(json.dumps({
        "version": 1,
        "schedule": schedule,
        "last_capture": None,
        "storage": storage,
    }))


def configure_paths(monkeypatch, tmp_path):
    draft = tmp_path / "schedule-draft.json"
    schedule = tmp_path / "schedule.json"
    heartbeat = tmp_path / "scheduler-heartbeat.json"
    monkeypatch.setattr(schedule_api, "SCHEDULE_DRAFT_PATH", draft)
    monkeypatch.setattr(schedule_api, "DEFAULT_SCHEDULE_PATH", schedule)
    monkeypatch.setattr(schedule_api, "SCHEDULER_HEARTBEAT_PATH", heartbeat)
    monkeypatch.setattr(schedule_api, "CAPTURE_OUTPUT_ROOT", tmp_path / "captures")
    return draft, schedule, heartbeat


def save_analysis_profile(path):
    config = AnalysisConfig(roi_rows=1, roi_cols=1)
    profile = AnalysisProfile(
        schema_version=1,
        config=config,
        roi=RoiDefinition(
            schema_version=2,
            rows=1,
            columns=1,
            source_width=100,
            source_height=100,
            config_fingerprint=config.fingerprint,
            circles=(RoiCircle(0, 0, 0.5, 0.5, 0.2),),
        ),
    )
    profile.save(path)
    return profile


def test_configure_api_and_react_form_expose_safe_defaults(tmp_path, monkeypatch):
    configure_paths(monkeypatch, tmp_path)
    payload = schedule_api.configure_schedule()
    source = (FRONTEND / "pages" / "ScheduleBuilderPage.jsx").read_text()
    capture_mode = (FRONTEND / "pages" / "CaptureModePage.jsx").read_text()

    assert payload["form"]["replicates"] == 1
    assert payload["form"]["replicate_interval_seconds"] == 0
    assert payload["form"]["analysis_enabled"] is False
    assert payload["defaults"] == payload["form"]
    assert payload["minimum_start_date"] == date.today().isoformat()
    assert "Reset defaults" in source
    assert "Continue to camera alignment" in source
    assert "<CameraModeIcon />" in capture_mode
    assert "<AnalyzeModeIcon />" in capture_mode
    assert "Images only" not in source
    assert "Analyze canopy" not in source
    assert 'max="365"' in source
    assert "replicate-interval-control" in source
    assert 'label="Start date"' in source
    assert "YYYY-MM-DD" in source
    assert 'label="Start time"' in source
    assert "(24h)" not in source
    assert 'type="date"' in source
    assert 'type="time"' not in source
    assert "Open graphical date picker" in source
    assert "Increase ${label.toLowerCase()} by one minute" in source
    assert "Decrease ${label.toLowerCase()} by one minute" in source
    assert source.index("<legend>Experiment</legend>") < source.index("<legend>Schedule mode</legend>")
    assert source.count("<legend>Schedule mode</legend>") == 1
    assert "<legend>Every n minutes</legend>" not in source
    assert "<legend>Fixed duration</legend>" not in source
    assert "<legend>Centered window</legend>" not in source
    assert "<HelpTip" in source
    assert "Capture from the start time through the end time" in source
    assert "Capture from the start time for the chosen duration" in source
    assert "Create a window before and after a center time" in source
    assert "<ScheduleWindowPreview form={form} />" in source


def test_configure_api_discards_an_expired_draft(tmp_path, monkeypatch):
    draft_path, _, _ = configure_paths(monkeypatch, tmp_path)
    form = schedule_form_data(start_date=(date.today() - timedelta(days=1)).isoformat())
    draft_path.write_text(json.dumps({
        "version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "form": form.model_dump(),
        "schedule": {},
        "schedule_hash": "a" * 64,
    }))

    payload = schedule_api.configure_schedule()

    assert payload["draft_state"] == "none"
    assert payload["form"]["start_date"] == date.today().isoformat()
    assert not draft_path.exists()


def test_configure_api_recovers_from_an_unreadable_draft(tmp_path, monkeypatch):
    draft_path, _, _ = configure_paths(monkeypatch, tmp_path)
    draft_path.write_text("{not valid json")

    payload = schedule_api.configure_schedule(edit=True)

    assert payload["draft_state"] == "invalid"
    assert payload["form"] == payload["defaults"]
    assert payload["form"]["start_date"] == date.today().isoformat()
    assert draft_path.exists()

    schedule_api.delete_schedule_draft()

    assert not draft_path.exists()


def test_rejected_draft_returns_a_user_facing_api_error(tmp_path, monkeypatch):
    configure_paths(monkeypatch, tmp_path)
    form = schedule_form_data(start_date=(date.today() - timedelta(days=1)).isoformat())

    with pytest.raises(HTTPException, match="past") as raised:
        schedule_api.create_schedule_draft(form)

    assert raised.value.status_code == 422


def test_draft_api_returns_complete_review_payload(tmp_path, monkeypatch):
    draft_path, _, heartbeat = configure_paths(monkeypatch, tmp_path)
    write_heartbeat(heartbeat)

    payload = schedule_api.create_schedule_draft(schedule_form_data())

    assert draft_path.exists()
    assert payload["draft"]["form"]["experiment_name"] == "Seedling drought response"
    assert payload["preview"]["total_captures"] == 12
    assert payload["preview"]["timeline_points"]
    assert payload["camera_aligned"] is False
    assert payload["can_activate"] is False
    assert payload["analysis_requested"] is False
    assert payload["analysis_ready"] is False

    with pytest.raises(HTTPException, match="camera alignment"):
        schedule_api.activate_schedule(
            schedule_api.ActivationRequest(
                draft_hash=payload["draft"]["schedule_hash"]
            )
        )
    with pytest.raises(HTTPException, match="preview"):
        schedule_api.confirm_draft_camera()
    record_camera_preview(draft_path)
    aligned = schedule_api.confirm_draft_camera()
    assert aligned["camera_aligned"] is True
    assert aligned["can_activate"] is True


def test_analysis_enabled_draft_requires_calibration_before_activation(
    tmp_path,
    monkeypatch,
):
    draft_path, schedule_path, heartbeat = configure_paths(monkeypatch, tmp_path)
    write_heartbeat(heartbeat)

    review = schedule_api.create_schedule_draft(
        schedule_form_data(analysis_enabled=True)
    )
    record_camera_preview(draft_path)
    schedule_api.confirm_draft_camera()

    assert review["analysis_requested"] is True
    assert review["analysis_ready"] is False
    assert review["can_activate"] is False
    with pytest.raises(HTTPException, match="calibration") as blocked:
        schedule_api.activate_schedule(
            schedule_api.ActivationRequest(
                draft_hash=review["draft"]["schedule_hash"]
            )
        )
    assert blocked.value.status_code == 409
    assert not schedule_path.exists()

    profile = save_analysis_profile(tmp_path / "analysis-profile.json")
    attach_analysis_profile_to_draft(profile, draft_path=draft_path)
    attached = schedule_api.attach_draft_analysis()
    activated = schedule_api.activate_schedule(
        schedule_api.ActivationRequest(
            draft_hash=attached["draft"]["schedule_hash"]
        )
    )

    assert attached["analysis_ready"] is True
    assert attached["can_activate"] is True
    assert activated["already_active"] is False
    assert json.loads(schedule_path.read_text())["analysis"]


def test_capture_only_draft_does_not_inherit_saved_analysis_profile(
    tmp_path,
    monkeypatch,
):
    draft_path, _, heartbeat = configure_paths(monkeypatch, tmp_path)
    write_heartbeat(heartbeat)
    save_analysis_profile(tmp_path / "analysis-profile.json")

    review = schedule_api.create_schedule_draft(
        schedule_form_data(analysis_enabled=False)
    )

    assert "analysis" not in review["draft"]["schedule"]
    with pytest.raises(HTTPException, match="capture only"):
        schedule_api.attach_draft_analysis()


def test_calibration_survives_edits_but_not_a_new_experiment(
    tmp_path,
    monkeypatch,
):
    draft_path, _, heartbeat = configure_paths(monkeypatch, tmp_path)
    write_heartbeat(heartbeat)
    original = schedule_api.create_schedule_draft(
        schedule_form_data(analysis_enabled=True)
    )
    profile = save_analysis_profile(tmp_path / "legacy-analysis-profile.json")
    attach_analysis_profile_to_draft(profile, draft_path=draft_path)

    edited = schedule_api.create_schedule_draft(
        schedule_form_data(
            analysis_enabled=True,
            notes="Updated notes for the same experiment",
        )
    )

    assert edited["analysis_ready"] is True
    assert (
        edited["draft"]["schedule"]["run"]["id"]
        == original["draft"]["schedule"]["run"]["id"]
    )

    discard_schedule_draft(draft_path)
    unrelated = schedule_api.create_schedule_draft(
        schedule_form_data(
            analysis_enabled=True,
            experiment_name="A different experiment",
        )
    )

    assert unrelated["analysis_ready"] is False
    assert "analysis" not in unrelated["draft"]["schedule"]


def test_activation_is_blocked_for_stale_scheduler_or_insufficient_storage(tmp_path, monkeypatch):
    draft_path, schedule_path, heartbeat = configure_paths(monkeypatch, tmp_path)
    draft = persist_schedule_draft(schedule_form_data(), draft_path)
    write_heartbeat(heartbeat, age_seconds=31)
    request = schedule_api.ActivationRequest(draft_hash=draft.schedule_hash)

    with pytest.raises(HTTPException) as stale:
        schedule_api.activate_schedule(request)
    assert stale.value.status_code == 503
    assert not schedule_path.exists()

    write_heartbeat(heartbeat, storage={"free_bytes": 1, "used_percent": 50})
    with pytest.raises(HTTPException) as storage:
        schedule_api.activate_schedule(request)
    assert storage.value.status_code == 409
    assert not schedule_path.exists()


def test_finished_schedule_is_not_used_for_draft_comparison(tmp_path, monkeypatch):
    draft_path, _, heartbeat = configure_paths(monkeypatch, tmp_path)
    persist_schedule_draft(schedule_form_data(), draft_path)
    write_heartbeat(heartbeat, schedule={
        "hash": "a" * 64,
        "timezone": "Europe/Amsterdam",
        "start_date": (date.today() - timedelta(days=4)).isoformat(),
        "num_days": 2,
        "times": ["08:00", "16:00"],
        "replicates": 1,
        "replicate_interval_seconds": 0,
    })

    review = schedule_api.get_schedule_draft()

    assert review["comparison"]["has_active_schedule"] is False


def test_identical_active_schedule_is_prominent_and_needs_no_activation(tmp_path, monkeypatch):
    draft_path, _, heartbeat = configure_paths(monkeypatch, tmp_path)
    draft = persist_schedule_draft(schedule_form_data(), draft_path)
    record_camera_preview(draft_path)
    confirm_camera_alignment(draft_path)
    write_heartbeat(heartbeat, state="running", schedule={
        "hash": draft.schedule_hash,
        "timezone": "Europe/Amsterdam",
        **draft.schedule,
    })

    review = schedule_api.get_schedule_draft()
    result = schedule_api.activate_schedule(schedule_api.ActivationRequest(draft_hash=draft.schedule_hash))

    assert review["already_active"] is True
    assert result == {"schedule_hash": draft.schedule_hash, "already_active": True}
    assert not draft_path.exists()


def test_active_schedule_must_be_cancelled_before_new_activation(tmp_path, monkeypatch):
    draft_path, schedule_path, heartbeat = configure_paths(monkeypatch, tmp_path)
    draft = persist_schedule_draft(schedule_form_data(), draft_path)
    record_camera_preview(draft_path)
    confirm_camera_alignment(draft_path)
    write_heartbeat(heartbeat, state="running", schedule={
        "hash": "a" * 64,
        "timezone": "Europe/Amsterdam",
        "start_date": (date.today() - timedelta(days=1)).isoformat(),
        "num_days": 3,
        "times": ["00:00", "23:59"],
        "replicates": 1,
        "replicate_interval_seconds": 0,
    })
    request = schedule_api.ActivationRequest(draft_hash=draft.schedule_hash)

    with pytest.raises(HTTPException, match="Cancel the current experiment") as blocked:
        schedule_api.activate_schedule(request)

    assert blocked.value.status_code == 409
    assert draft_path.exists()
    assert not schedule_path.exists()


def test_upcoming_schedule_must_be_cancelled_before_new_activation(tmp_path, monkeypatch):
    draft_path, schedule_path, heartbeat = configure_paths(monkeypatch, tmp_path)
    draft = persist_schedule_draft(schedule_form_data(), draft_path)
    record_camera_preview(draft_path)
    confirm_camera_alignment(draft_path)
    write_heartbeat(heartbeat, schedule={
        "hash": "b" * 64,
        "timezone": "Europe/Amsterdam",
        "start_date": (date.today() + timedelta(days=2)).isoformat(),
        "num_days": 2,
        "times": ["09:00"],
        "replicates": 1,
        "replicate_interval_seconds": 0,
    })
    request = schedule_api.ActivationRequest(draft_hash=draft.schedule_hash)

    with pytest.raises(HTTPException, match="Cancel the current experiment") as blocked:
        schedule_api.activate_schedule(request)

    assert blocked.value.status_code == 409
    assert draft_path.exists()
    assert not schedule_path.exists()


def test_schedule_api_routes_and_react_workflow_are_complete():
    assert str(app.url_path_for("configure_schedule")) == "/api/schedule/configure"
    assert str(app.url_path_for("create_schedule_draft")) == "/api/schedule/draft"
    assert str(app.url_path_for("get_schedule_draft")) == "/api/schedule/draft"
    assert (
        str(app.url_path_for("attach_draft_analysis"))
        == "/api/schedule/draft/analysis"
    )
    assert (
        str(app.url_path_for("confirm_draft_camera"))
        == "/api/schedule/draft/camera"
    )
    assert str(app.url_path_for("activate_schedule")) == "/api/schedule/activate"
    app_source = (FRONTEND / "App.jsx").read_text()
    activation = (FRONTEND / "pages" / "ActivationPage.jsx").read_text()
    scheduler = (FRONTEND / "pages" / "SchedulerPage.jsx").read_text()
    components = (FRONTEND / "components.jsx").read_text()
    builder = (FRONTEND / "pages" / "ScheduleBuilderPage.jsx").read_text()
    capture_mode = (FRONTEND / "pages" / "CaptureModePage.jsx").read_text()
    review = (FRONTEND / "pages" / "ScheduleReviewPage.jsx").read_text()
    analysis = (FRONTEND / "pages" / "AnalysisSetupPage.jsx").read_text()
    assert "ScheduleBuilderPage" in app_source
    assert "CaptureModePage" in app_source
    assert "ScheduleReviewPage" in app_source
    assert "ActivationPage" in app_source
    assert "Choose capture mode" in capture_mode
    assert "Images only" in capture_mode
    assert "Analyze canopy" in capture_mode
    assert "Continue to schedule" in capture_mode
    assert "Images only" not in builder
    assert "Analyze canopy" not in builder
    assert "Continue to camera alignment" in builder
    assert 'navigate("/camera?workflow=schedule")' in builder
    assert "Canopy calibration required" in review
    assert "Calibrate analysis" in review
    assert "Use this calibration" in analysis
    assert "Save and continue to review" in analysis
    assert "Back to schedule" in analysis
    assert 'params.get("workflow") !== "schedule"' in analysis
    assert '<Navigate to="/schedule" replace />' in analysis
    assert "workflow_available" in analysis
    assert 'to="/schedule/build/edit"' in analysis
    assert "The plant mask is a black-and-white image" in analysis
    assert (
        'import { ErrorNotice, HelpTip, Loading, WorkflowSteps }'
        in analysis
    )
    assert 'id="analysis-help-image"' not in analysis
    assert 'id="analysis-help-orientation"' not in analysis
    assert 'id="analysis-help-channel"' not in analysis
    assert 'id="analysis-help-mask"' not in analysis
    assert 'id="analysis-help-roi"' not in analysis
    assert 'aria-label={`${label} exact value`}' in analysis
    assert 'id="analysis-help-setting-channel"' in analysis
    assert "White pixels are treated as plant" in analysis
    assert "black pixels are treated as background" in analysis
    assert "IntersectionObserver" in analysis
    assert 'data-control-group="orientation"' in analysis
    assert "Controls this preview" not in analysis
    assert "ROI grid has not been detected" in analysis
    assert "Restore defaults" in analysis
    assert "setConfig({ ...defaultConfig })" in analysis
    assert 'id="analysis-help-setting-rows"' in analysis
    assert 'id="analysis-help-setting-columns"' in analysis
    assert 'id="analysis-help-setting-detect"' in analysis
    assert "analysis-control-group-note" not in analysis
    assert "analysis-roi-note" not in analysis
    assert "scrollIntoView" in analysis
    assert "prefers-reduced-motion" in analysis
    assert 'if (key === "rotate_angle") {\\n      setAnalysisCrop' not in analysis
    assert '"Calibrate"' in components
    assert '"Align camera"' in components
    assert '"Capture mode"' in components
    assert '"Schedule"' in components
    assert '"Confirmed"' not in components
    assert "schedule?.hash === expected" in activation
    assert "setCountdown(5)" in activation
    assert "Create another schedule" not in activation
    assert "function StopExperiment" in scheduler
    assert 'api("/api/scheduler/cancel"' in scheduler
    assert "I understand that this experiment cannot be resumed." in scheduler
    assert "Cancel scheduled experiment" in scheduler
    assert "I understand that no captures will be taken" in scheduler
    assert "capture-result-bar" in scheduler
    assert "Result pending" in scheduler
    assert 'role="img"' in scheduler
    assert "Today’s imaging progress" in scheduler
    assert "daily-progress-pulse" in scheduler
    assert "daily-progress-complete" in scheduler
    assert "Smaller markers show technical replicates." in scheduler
    assert "Next replicate" in scheduler
    assert "Markers are condensed" not in scheduler
    assert "Scroll to inspect every time point." in scheduler
    assert "Recent outcomes" not in scheduler
    assert "daily-next-pointer" in scheduler
    assert "Latest actual capture" not in scheduler
    assert "Final capture" not in scheduler
    assert "Finishes at" in scheduler
    assert "function ScheduleStorage" in scheduler
    assert "day-strip" not in components
    assert "Scheduled experiment days" not in components
    assert "preview-overview" in components
    assert "Experiment dates" in components
    assert "Capture volume" in components
    assert "Technical replicates" not in components
    assert "timeline-replicates" in components
    assert "buildTimelineTicks" in components
