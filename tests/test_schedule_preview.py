import hashlib
import json
from zoneinfo import ZoneInfo

import pytest

from gui.services.schedule_preview import (
    ScheduleFormData,
    activate_schedule_draft,
    build_schedule_preview,
    compare_schedules,
    discard_schedule_draft,
    load_schedule_draft,
    persist_schedule_draft,
)
from gui.services.schedule_drafts import confirm_camera_alignment
from scripts.scheduling.make_schedule import write_schedule
from scripts.scheduling.scheduler import expand_schedule, load_schedule


BASE_ARGUMENTS = {
    "start_date": "2099-07-18",
    "num_days": 2,
    "replicates": 2,
    "replicate_interval_seconds": 10,
}


@pytest.mark.parametrize(
    ("mode", "mode_arguments", "expected"),
    [
        (
            "every",
            {"every_start": "09:00", "every_end": "10:00", "every_step_minutes": 30},
            ["09:00", "09:30", "10:00"],
        ),
        (
            "duration",
            {
                "duration_start": "09:00",
                "duration_minutes": 60,
                "duration_step_minutes": 30,
            },
            ["09:00", "09:30", "10:00"],
        ),
        (
            "centered",
            {
                "centered_center": "10:00",
                "centered_before_minutes": 30,
                "centered_after_minutes": 30,
                "centered_step_minutes": 30,
            },
            ["09:30", "10:00", "10:30"],
        ),
    ],
)
def test_build_schedule_preview_modes(mode, mode_arguments, expected):
    preview = build_schedule_preview(
        **BASE_ARGUMENTS,
        mode=mode,
        **mode_arguments,
    )

    assert preview.times == expected
    assert preview.daily_captures == len(expected) * 2
    assert preview.total_captures == len(expected) * 4
    assert preview.date_range_label == "2099-07-18 → 2099-07-19"
    assert preview.replicate_offsets == [
        {"number": 1, "offset_seconds": 0},
        {"number": 2, "offset_seconds": 10},
    ]
    assert preview.as_schedule_dict()["times"] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_date": "18-07-2026"},
        {"num_days": 0},
        {"replicates": 0},
        {"replicate_interval_seconds": -1},
        {"num_days": 10**100},
        {"replicates": 10**100},
        {"replicate_interval_seconds": 10**100},
        {"mode": "unknown"},
    ],
)
def test_schedule_preview_rejects_invalid_form_values(overrides):
    arguments = {
        **BASE_ARGUMENTS,
        "mode": "every",
        "every_start": "09:00",
        "every_end": "10:00",
        "every_step_minutes": 30,
    }
    arguments.update(overrides)

    with pytest.raises(ValueError):
        build_schedule_preview(**arguments)


def test_schedule_preview_requires_fields_for_selected_mode():
    with pytest.raises(ValueError, match="Duration mode requires"):
        build_schedule_preview(**BASE_ARGUMENTS, mode="duration")


def test_schedule_preview_rejects_past_and_overflowing_date_ranges():
    with pytest.raises(ValueError, match="past"):
        build_schedule_preview(
            **{**BASE_ARGUMENTS, "start_date": "2020-01-01"},
            mode="every",
        )
    with pytest.raises(ValueError, match="calendar"):
        build_schedule_preview(
            **{**BASE_ARGUMENTS, "start_date": "9999-12-31", "num_days": 2},
            mode="every",
            every_start="09:00",
            every_end="10:00",
            every_step_minutes=30,
        )


def test_schedule_preview_caps_total_capture_count():
    with pytest.raises(ValueError, match="maximum"):
        build_schedule_preview(
            **{
                **BASE_ARGUMENTS,
                "num_days": 365,
                "replicates": 100,
            },
            mode="every",
            every_start="00:00",
            every_end="23:59",
            every_step_minutes=1,
        )


def test_schedule_form_data_parses_checkbox_and_supplies_mode_defaults():
    form = ScheduleFormData.model_validate(
        {
            **BASE_ARGUMENTS,
            "mode": "every",
            "experiment_name": "  Canopy development  ",
            "researcher": "   ",
        }
    )

    assert form.every_start == "08:00"
    assert form.experiment_name == "Canopy development"
    assert form.researcher is None
    assert form.every_end == "19:30"
    assert form.preview_arguments()["every_step_minutes"] == 30
    assert form.centered_before_minutes == 120
    assert form.centered_after_minutes == 120
    assert form.centered_step_minutes == 30


def test_schedule_draft_round_trip_and_activation(tmp_path):
    draft_path = tmp_path / "schedule-draft.json"
    schedule_path = tmp_path / "schedule.json"
    form = ScheduleFormData(
        **BASE_ARGUMENTS,
        mode="every",
        experiment_name="Canopy development",
        every_start="09:00",
        every_end="09:00",
    )

    draft = persist_schedule_draft(form, draft_path)
    aligned_draft = confirm_camera_alignment(draft_path)
    loaded, preview = load_schedule_draft(draft_path)
    activated_hash = activate_schedule_draft(
        draft.schedule_hash,
        draft_path=draft_path,
        schedule_path=schedule_path,
    )

    assert loaded == aligned_draft
    assert preview.times == ["09:00"]
    assert activated_hash == draft.schedule_hash
    assert (
        hashlib.sha256(schedule_path.read_bytes()).hexdigest()
        == draft.schedule_hash
    )
    assert json.loads(schedule_path.read_text())["times"] == ["09:00"]
    activated = json.loads(schedule_path.read_text())
    assert activated["run"]["name"] == "Canopy development"
    assert activated["run"]["id"]
    assert not draft_path.exists()


@pytest.mark.parametrize(
    "value",
    ["", "   ", "x" * 81],
)
def test_schedule_form_requires_a_concise_experiment_name(value):
    with pytest.raises(ValueError):
        ScheduleFormData(
            **BASE_ARGUMENTS,
            mode="every",
            experiment_name=value,
        )


def test_schedule_draft_rejects_stale_hash(tmp_path):
    path = tmp_path / "draft.json"
    form = ScheduleFormData(
        **BASE_ARGUMENTS,
        mode="every",
        experiment_name="Canopy development",
    )
    persist_schedule_draft(form, path)

    with pytest.raises(ValueError, match="replaced"):
        activate_schedule_draft(
            "0" * 64,
            draft_path=path,
            schedule_path=tmp_path / "schedule.json",
        )


def test_schedule_draft_detects_tampering_and_can_be_discarded(tmp_path):
    path = tmp_path / "draft.json"
    form = ScheduleFormData(
        **BASE_ARGUMENTS,
        mode="every",
        experiment_name="Canopy development",
    )
    persist_schedule_draft(form, path)
    payload = json.loads(path.read_text())
    payload["schedule"]["num_days"] = 99
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="inconsistent"):
        load_schedule_draft(path)

    discard_schedule_draft(path)
    assert not path.exists()


def test_schedule_comparison_marks_changed_values():
    preview = build_schedule_preview(
        **BASE_ARGUMENTS,
        mode="every",
        every_start="09:00",
        every_end="10:00",
        every_step_minutes=30,
    )
    active = {
        "start_date": "2026-07-18",
        "end_date": "2026-07-18",
        "num_days": 1,
        "daily_time_points": 1,
        "replicates": 1,
        "replicate_interval_seconds": 0,
        "daily_captures": 1,
        "total_captures": 1,
    }

    comparison = compare_schedules(preview, active)

    assert comparison.has_active_schedule is True
    assert comparison.changed is True
    assert any(row["changed"] for row in comparison.rows)


def test_generated_schedule_is_compatible_with_scheduler(tmp_path):
    output = tmp_path / "schedule.json"
    write_schedule(
        output=output,
        start_date="2026-07-18",
        num_days=2,
        times=["09:00"],
        replicates=2,
        replicate_interval_seconds=10,
    )

    jobs = expand_schedule(
        load_schedule(output),
        ZoneInfo("Europe/Amsterdam"),
    )

    assert [job.strftime("%Y-%m-%d %H:%M:%S") for job in jobs] == [
        "2026-07-18 09:00:00",
        "2026-07-18 09:00:10",
        "2026-07-19 09:00:00",
        "2026-07-19 09:00:10",
    ]
