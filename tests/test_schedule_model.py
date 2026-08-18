from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from scripts.analysis.config import AnalysisConfig
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.roi import RoiCircle, RoiDefinition
from scripts.scheduling.schedule import RunMetadata, Schedule


def schedule_data(**overrides):
    value = {
        "start_date": "2026-07-23",
        "num_days": 2,
        "times": ["09:00", "10:00"],
        "replicates": 2,
        "replicate_interval_seconds": 10,
    }
    value.update(overrides)
    return value


def test_schedule_parses_normalizes_and_serializes_canonically():
    schedule = Schedule.from_dict(
        schedule_data(times=["10:00", "09:00", "09:00"])
    )

    assert schedule.start_date.isoformat() == "2026-07-23"
    assert [value.strftime("%H:%M") for value in schedule.times] == [
        "09:00",
        "10:00",
    ]
    assert schedule.end_date.isoformat() == "2026-07-24"
    assert schedule.daily_captures == 4
    assert schedule.total_captures == 8
    assert Schedule.from_json(schedule.to_json()) == schedule


def test_schedule_expands_days_and_replicates():
    schedule = Schedule.from_dict(schedule_data())

    expanded = schedule.expand(ZoneInfo("Europe/Amsterdam"))

    assert expanded[0].isoformat() == "2026-07-23T09:00:00+02:00"
    assert expanded[1].isoformat() == "2026-07-23T09:00:10+02:00"
    assert expanded[-1].isoformat() == "2026-07-24T10:00:10+02:00"


def test_schedule_expands_date_specific_capture_times():
    schedule = Schedule.create(
        start_date="2026-07-23",
        num_days=3,
        times=["08:00", "09:00", "17:00"],
        daily_times={
            "2026-07-23": ["08:00", "09:00"],
            "2026-07-25": ["17:00"],
        },
        replicates=1,
    )

    expanded = schedule.expand(ZoneInfo("Europe/Amsterdam"))

    assert [value.isoformat() for value in expanded] == [
        "2026-07-23T08:00:00+02:00",
        "2026-07-23T09:00:00+02:00",
        "2026-07-25T17:00:00+02:00",
    ]
    assert schedule.daily_time_points == 2
    assert schedule.daily_captures == 2
    assert schedule.total_captures == 3
    assert Schedule.from_json(schedule.to_json()) == schedule


def test_schedule_rejects_missing_fields_and_overlapping_replicates():
    with pytest.raises(ValueError, match="missing required field 'start_date'"):
        Schedule.from_dict({})
    with pytest.raises(ValueError, match="finish before"):
        Schedule.from_dict(
            schedule_data(
                times=["09:00", "09:01"],
                replicate_interval_seconds=60,
            )
        )


def test_run_metadata_round_trips_as_typed_data():
    value = {
        "id": str(uuid4()),
        "name": "Drought response",
        "researcher": "Researcher One",
        "notes": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    run = RunMetadata.from_dict(value)

    assert run.to_dict() == value
    assert Schedule.from_dict(schedule_data(run=value)).run == run


def test_schedule_preserves_optional_analysis_profile():
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

    schedule = Schedule.from_dict(
        schedule_data(analysis=profile.to_dict())
    )

    assert schedule.analysis == profile
    assert Schedule.from_json(schedule.to_json()) == schedule
