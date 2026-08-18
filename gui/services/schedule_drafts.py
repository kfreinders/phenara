from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from phenara.config import (
    DEFAULT_SCHEDULE_PATH,
    SCHEDULE_DRAFT_PATH,
)
from gui.services.schedule_builder import (
    PastStartDateError,
    SchedulePreview,
    build_schedule_preview,
)
from gui.services.schedule_form import ScheduleFormData, form_defaults
from scripts.scheduling.make_schedule import (
    atomic_write_text,
    schedule_json,
    write_schedule,
)
from scripts.analysis.profile import AnalysisProfile


DRAFT_VERSION = 3


class ScheduleDraft(BaseModel):
    """A persisted, reviewed schedule and the form that generated it."""

    version: int = DRAFT_VERSION
    created_at: str
    form: ScheduleFormData
    schedule: dict[str, Any]
    schedule_hash: str
    camera_aligned: bool = False
    camera_preview_ready: bool = False


def persist_schedule_draft(
    form: ScheduleFormData,
    path: Path = SCHEDULE_DRAFT_PATH,
) -> ScheduleDraft:
    preview = build_schedule_preview(**form.preview_arguments())
    existing = None
    if path.exists():
        try:
            existing, _ = load_schedule_draft(path)
        except (PastStartDateError, ValueError):
            existing = None
    run = (
        {
            **existing.schedule["run"],
            "name": form.experiment_name,
            "researcher": form.researcher,
            "notes": form.notes,
        }
        if existing
        else {
            "id": str(uuid4()),
            "name": form.experiment_name,
            "researcher": form.researcher,
            "notes": form.notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    schedule = {**preview.as_schedule_dict(), "run": run}
    if (
        form.analysis_enabled
        and existing
        and existing.schedule.get("analysis") is not None
    ):
        schedule["analysis"] = existing.schedule["analysis"]
    draft = ScheduleDraft(
        created_at=datetime.now(timezone.utc).isoformat(),
        form=form,
        schedule=schedule,
        schedule_hash=_schedule_hash(schedule),
        camera_aligned=existing.camera_aligned if existing else False,
        camera_preview_ready=(
            existing.camera_preview_ready if existing else False
        ),
    )
    atomic_write_text(path, draft.model_dump_json(indent=2) + "\n")
    return draft


def reuse_schedule_as_draft(
    source: dict[str, Any],
    path: Path = SCHEDULE_DRAFT_PATH,
    *,
    start_date: date | None = None,
) -> ScheduleDraft:
    """Create a new editable draft from a retained experiment schedule."""
    source_start = date.fromisoformat(str(source["start_date"]))
    reused_start = start_date or date.today()
    num_days = int(source["num_days"])
    source_daily = source.get("daily_times") or {
        (source_start + timedelta(days=offset)).isoformat(): source["times"]
        for offset in range(num_days)
    }
    shifted_daily = [
        (
            reused_start + (date.fromisoformat(day) - source_start),
            tuple(times),
        )
        for day, times in sorted(source_daily.items())
    ]
    custom_days = []
    for day, times in shifted_daily:
        if custom_days and (
            custom_days[-1]["times"] == times
            and date.fromisoformat(custom_days[-1]["end_date"]) + timedelta(days=1)
            == day
        ):
            custom_days[-1]["end_date"] = day.isoformat()
            continue
        custom_days.append({
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "times": times,
        })
    form_values = {
        **form_defaults(),
        "mode": "custom",
        "experiment_name": _copy_name(source["run"]["name"]),
        "researcher": source["run"].get("researcher"),
        "notes": source["run"].get("notes"),
        "analysis_enabled": source.get("analysis") is not None,
        "start_date": reused_start.isoformat(),
        "num_days": num_days,
        "replicates": int(source.get("replicates", 1)),
        "replicate_interval_seconds": int(
            source.get("replicate_interval_seconds", 0)
        ),
        "custom_days": [
            {
                "start_date": block["start_date"],
                "end_date": block["end_date"],
                "windows": _time_windows(block["times"]),
            }
            for block in custom_days
        ],
    }
    form = ScheduleFormData(**form_values)
    preview = build_schedule_preview(**form.preview_arguments())
    run = {
        "id": str(uuid4()),
        "name": form.experiment_name,
        "researcher": form.researcher,
        "notes": form.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    schedule = {**preview.as_schedule_dict(), "run": run}
    if source.get("analysis") is not None:
        schedule["analysis"] = AnalysisProfile.from_dict(
            source["analysis"]
        ).to_dict()
    draft = ScheduleDraft(
        created_at=datetime.now(timezone.utc).isoformat(),
        form=form,
        schedule=schedule,
        schedule_hash=_schedule_hash(schedule),
        camera_aligned=False,
        camera_preview_ready=False,
    )
    atomic_write_text(path, draft.model_dump_json(indent=2) + "\n")
    return draft


def load_schedule_draft(
    path: Path = SCHEDULE_DRAFT_PATH,
) -> tuple[ScheduleDraft, SchedulePreview]:
    try:
        draft = ScheduleDraft.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("The saved schedule draft could not be read.") from exc
    if draft.version != DRAFT_VERSION:
        raise ValueError("The saved schedule draft uses an unsupported version.")
    preview = build_schedule_preview(**draft.form.preview_arguments())
    expected_schedule = {
        **preview.as_schedule_dict(),
        "run": draft.schedule.get("run"),
    }
    if draft.schedule.get("analysis") is not None:
        if not draft.form.analysis_enabled:
            raise ValueError(
                "The saved schedule draft has an unexpected analysis setup."
            )
        expected_schedule["analysis"] = AnalysisProfile.from_dict(
            draft.schedule["analysis"]
        ).to_dict()
    if expected_schedule != draft.schedule:
        raise ValueError("The saved schedule draft is inconsistent.")
    if _schedule_hash(draft.schedule) != draft.schedule_hash:
        raise ValueError("The saved schedule draft has changed unexpectedly.")
    return draft, preview


def load_current_schedule_draft(
    path: Path = SCHEDULE_DRAFT_PATH,
) -> tuple[ScheduleDraft, SchedulePreview] | None:
    """Load a usable draft, removing it if its start date has expired."""
    if not path.exists():
        return None
    try:
        return load_schedule_draft(path)
    except PastStartDateError:
        discard_schedule_draft(path)
        return None


def discard_schedule_draft(path: Path = SCHEDULE_DRAFT_PATH) -> None:
    path.unlink(missing_ok=True)


def confirm_camera_alignment(
    path: Path = SCHEDULE_DRAFT_PATH,
) -> ScheduleDraft:
    """Record the mandatory camera-alignment check for one experiment."""
    draft, _ = load_schedule_draft(path)
    if not draft.camera_preview_ready:
        raise ValueError(
            "Acquire a camera preview before confirming alignment."
        )
    updated = draft.model_copy(update={"camera_aligned": True})
    atomic_write_text(path, updated.model_dump_json(indent=2) + "\n")
    return updated


def record_camera_preview(
    path: Path = SCHEDULE_DRAFT_PATH,
) -> ScheduleDraft:
    """Record a fresh preview and require its alignment to be confirmed."""
    draft, _ = load_schedule_draft(path)
    updated = draft.model_copy(
        update={
            "camera_aligned": False,
            "camera_preview_ready": True,
        }
    )
    atomic_write_text(path, updated.model_dump_json(indent=2) + "\n")
    return updated


def attach_analysis_profile_to_draft(
    profile: AnalysisProfile | None = None,
    *,
    draft_path: Path = SCHEDULE_DRAFT_PATH,
) -> ScheduleDraft:
    """Attach a calibration to its analysis-enabled experiment draft."""
    draft, _ = load_schedule_draft(draft_path)
    if not draft.form.analysis_enabled:
        raise ValueError(
            "This experiment was configured for image capture only."
        )
    if profile is None and draft.schedule.get("analysis") is None:
        raise ValueError(
            "Complete and save the canopy analysis calibration first."
        )
    analysis = (
        profile.to_dict()
        if profile is not None
        else draft.schedule["analysis"]
    )
    schedule = {**draft.schedule, "analysis": analysis}
    updated = draft.model_copy(
        update={
            "schedule": schedule,
            "schedule_hash": _schedule_hash(schedule),
        }
    )
    atomic_write_text(
        draft_path,
        updated.model_dump_json(indent=2) + "\n",
    )
    return updated


def activate_schedule_draft(
    expected_hash: str,
    *,
    draft_path: Path = SCHEDULE_DRAFT_PATH,
    schedule_path: Path = DEFAULT_SCHEDULE_PATH,
) -> str:
    draft, preview = load_schedule_draft(draft_path)
    if draft.schedule_hash != expected_hash:
        raise ValueError(
            "This draft has been replaced. Review the latest draft before activating it."
        )
    if not draft.camera_aligned:
        raise ValueError(
            "Confirm the camera alignment before activating this experiment."
        )
    if draft.form.analysis_enabled and draft.schedule.get("analysis") is None:
        raise ValueError(
            "Complete and save the canopy analysis calibration before activation."
        )
    write_schedule(
        output=schedule_path,
        start_date=preview.start_date,
        num_days=preview.num_days,
        times=preview.times,
        replicates=preview.replicates,
        replicate_interval_seconds=preview.replicate_interval_seconds,
        run=draft.schedule["run"],
        analysis=draft.schedule.get("analysis"),
        daily_times=draft.schedule.get("daily_times"),
        overwrite=True,
    )
    discard_schedule_draft(draft_path)
    return draft.schedule_hash


def _schedule_hash(schedule: dict[str, Any]) -> str:
    return hashlib.sha256(schedule_json(schedule).encode()).hexdigest()


def _copy_name(value: str) -> str:
    suffix = " copy"
    return f"{value[:80 - len(suffix)].rstrip()}{suffix}"


def _time_windows(values: tuple[str, ...]) -> list[dict[str, str | int]]:
    """Represent exact capture times as a compact set of regular windows."""
    minutes = [
        int(value.split(":", maxsplit=1)[0]) * 60
        + int(value.split(":", maxsplit=1)[1])
        for value in values
    ]
    windows = []
    index = 0
    while index < len(minutes):
        start = minutes[index]
        if index == len(minutes) - 1:
            end = start
            step = 1
            index += 1
        else:
            step = minutes[index + 1] - start
            end_index = index + 1
            while (
                end_index + 1 < len(minutes)
                and minutes[end_index + 1] - minutes[end_index] == step
            ):
                end_index += 1
            end = minutes[end_index]
            index = end_index + 1
        windows.append({
            "start": f"{start // 60:02d}:{start % 60:02d}",
            "end": f"{end // 60:02d}:{end % 60:02d}",
            "step_minutes": step,
        })
    return windows
