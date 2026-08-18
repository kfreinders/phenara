from datetime import date, timedelta
from uuid import UUID

from gui.services.schedule_drafts import (
    load_schedule_draft,
    reuse_schedule_as_draft,
)
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.roi import RoiCircle, RoiDefinition


def source_schedule(**updates):
    value = {
        "start_date": "2026-06-01",
        "num_days": 3,
        "times": ["08:15", "12:45", "17:05"],
        "replicates": 2,
        "replicate_interval_seconds": 15,
        "run": {
            "id": "00000000-0000-4000-8000-000000000001",
            "name": "Colleague drought trial",
            "researcher": "Researcher One",
            "notes": "Keep the same pot layout",
            "created_at": "2026-05-20T10:00:00+00:00",
        },
    }
    value.update(updates)
    return value


def test_reuse_creates_fresh_editable_draft_with_equivalent_capture_plan(tmp_path):
    reused_start = date.today() + timedelta(days=2)
    draft_path = tmp_path / "schedule-draft.json"

    draft = reuse_schedule_as_draft(
        source_schedule(),
        draft_path,
        start_date=reused_start,
    )
    loaded, preview = load_schedule_draft(draft_path)

    assert loaded == draft
    assert UUID(draft.schedule["run"]["id"]) != UUID(
        source_schedule()["run"]["id"]
    )
    assert draft.form.experiment_name == "Colleague drought trial copy"
    assert draft.form.researcher == "Researcher One"
    assert draft.form.notes == "Keep the same pot layout"
    assert draft.form.mode == "custom"
    assert draft.form.custom_days[0].windows[0].start == "08:15"
    assert draft.form.custom_days[0].windows[0].end == "12:45"
    assert draft.camera_aligned is False
    assert draft.camera_preview_ready is False
    assert preview.start_date == reused_start.isoformat()
    assert preview.num_days == 3
    assert preview.total_captures == 18
    assert preview.times == ["08:15", "12:45", "17:05"]


def test_reuse_shifts_custom_daily_timing_without_changing_day_offsets(tmp_path):
    reused_start = date.today() + timedelta(days=1)
    source = source_schedule(
        daily_times={
            "2026-06-01": ["09:00"],
            "2026-06-03": ["10:00", "14:00"],
        },
        times=["09:00", "10:00", "14:00"],
    )

    draft = reuse_schedule_as_draft(
        source,
        tmp_path / "schedule-draft.json",
        start_date=reused_start,
    )

    assert draft.schedule["daily_times"] == {
        reused_start.isoformat(): ["09:00"],
        (reused_start + timedelta(days=2)).isoformat(): ["10:00", "14:00"],
    }
    assert draft.schedule["replicates"] == 2
    assert draft.schedule["replicate_interval_seconds"] == 15


def test_reuse_preserves_analysis_configuration_but_requires_new_alignment(tmp_path):
    config = AnalysisConfig(roi_rows=1, roi_cols=1, threshold=132)
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

    draft = reuse_schedule_as_draft(
        source_schedule(analysis=profile.to_dict()),
        tmp_path / "schedule-draft.json",
        start_date=date.today() + timedelta(days=1),
    )

    assert draft.form.analysis_enabled is True
    assert draft.schedule["analysis"] == profile.to_dict()
    assert draft.camera_aligned is False
