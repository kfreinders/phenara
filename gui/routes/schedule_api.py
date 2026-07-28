from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from phenopi.config import (
    DEFAULT_SCHEDULE_PATH,
    SCHEDULE_DRAFT_PATH,
    SCHEDULER_HEARTBEAT_PATH,
)
from gui.services.schedule_comparison import compare_schedules
from gui.services.schedule_drafts import (
    activate_schedule_draft,
    attach_analysis_profile_to_draft,
    confirm_camera_alignment,
    discard_schedule_draft,
    load_current_schedule_draft,
    persist_schedule_draft,
)
from gui.services.schedule_form import ScheduleFormData, form_defaults
from gui.services.scheduler_status import read_scheduler_status
from gui.services.storage_estimate import assess_schedule_storage


router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_hash: str
    confirm_active_replacement: bool = False


@router.get("/configure")
def configure_schedule(edit: bool = False) -> dict:
    loaded = _load_draft()
    defaults = form_defaults()
    return {
        "form": loaded[0].form.form_arguments() if edit and loaded else defaults,
        "defaults": defaults,
        "minimum_start_date": date.today().isoformat(),
        "draft_state": "ready" if loaded else "none",
        "analysis_profile_saved": bool(
            loaded and loaded[0].schedule.get("analysis")
        ),
    }


@router.post("/draft")
def create_schedule_draft(form: ScheduleFormData) -> dict:
    try:
        persist_schedule_draft(
            form,
            SCHEDULE_DRAFT_PATH,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The schedule draft could not be saved.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_schedule_draft()


@router.get("/draft")
def get_schedule_draft() -> dict:
    loaded = _load_draft()
    if loaded is None:
        raise HTTPException(status_code=404, detail="No schedule draft is available.")
    draft, preview = loaded
    status = read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    return _review_payload(draft, preview, status)


@router.delete("/draft", status_code=204)
def delete_schedule_draft() -> None:
    discard_schedule_draft(SCHEDULE_DRAFT_PATH)


@router.post("/draft/analysis")
def attach_draft_analysis() -> dict:
    try:
        attach_analysis_profile_to_draft(
            draft_path=SCHEDULE_DRAFT_PATH,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="No schedule draft is available.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The analysis calibration could not be attached.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return get_schedule_draft()


@router.post("/draft/camera")
def confirm_draft_camera() -> dict:
    if _load_draft() is None:
        raise HTTPException(
            status_code=404,
            detail="No schedule draft is available.",
        )
    try:
        confirm_camera_alignment(SCHEDULE_DRAFT_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return get_schedule_draft()


@router.post("/activate")
def activate_schedule(request: ActivationRequest) -> dict:
    loaded = _load_draft()
    if loaded is None:
        raise HTTPException(status_code=404, detail="No schedule draft is available.")
    draft, preview = loaded
    status = read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    review = _review_payload(draft, preview, status)

    if draft.schedule_hash != request.draft_hash:
        raise HTTPException(
            status_code=409,
            detail="This draft has been replaced. Review the latest draft first.",
        )
    if status["status"] in {"stale", "unavailable"}:
        raise HTTPException(
            status_code=503,
            detail="The scheduler is not responding. Activation is unavailable.",
        )
    if review["storage_assessment"]["status"] == "insufficient":
        raise HTTPException(
            status_code=409,
            detail="The estimated experiment data exceeds the available storage.",
        )
    if review["analysis_requested"] and not review["analysis_ready"]:
        raise HTTPException(
            status_code=409,
            detail=(
                "Complete and save the canopy analysis calibration before "
                "activating this experiment."
            ),
        )
    if not review["camera_aligned"]:
        raise HTTPException(
            status_code=409,
            detail="Confirm the camera alignment before activating this experiment.",
        )

    active = status.get("schedule")
    if active and active.get("hash") == draft.schedule_hash:
        discard_schedule_draft(SCHEDULE_DRAFT_PATH)
        return {"schedule_hash": draft.schedule_hash, "already_active": True}

    replacing_schedule = bool(
        active and active.get("lifecycle") in {"active", "upcoming"}
    )
    if replacing_schedule and not request.confirm_active_replacement:
        return {"confirmation_required": True, "review": review}

    try:
        activated_hash = activate_schedule_draft(
            request.draft_hash,
            draft_path=SCHEDULE_DRAFT_PATH,
            schedule_path=DEFAULT_SCHEDULE_PATH,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The schedule could not be activated.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"schedule_hash": activated_hash, "already_active": False}


def _load_draft():
    try:
        return load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _review_payload(draft, preview, status: dict) -> dict:
    active = status.get("schedule")
    comparable = (
        active
        if active and active.get("lifecycle") in {"upcoming", "active"}
        else None
    )
    storage = assess_schedule_storage(preview.total_captures, status.get("storage"))
    scheduler_responding = status["status"] not in {"stale", "unavailable"}
    comparison = compare_schedules(preview, comparable)
    return {
        "draft": draft.model_dump(),
        "preview": {
            **preview.as_schedule_dict(),
            "end_date": preview.end_date,
            "date_range_label": preview.date_range_label,
            "daily_time_points": preview.daily_time_points,
            "daily_captures": preview.daily_captures,
            "total_captures": preview.total_captures,
            "first_time": preview.first_time,
            "last_time": preview.last_time,
            "summary_sentence": preview.summary_sentence,
            "replicate_offsets": preview.replicate_offsets,
            "timeline_points": preview.timeline_points,
        },
        "comparison": {
            "rows": comparison.rows,
            "has_active_schedule": comparison.has_active_schedule,
            "changed": comparison.changed,
        },
        "scheduler_status": status,
        "storage_assessment": storage,
        "scheduler_responding": scheduler_responding,
        "analysis_requested": draft.form.analysis_enabled,
        "analysis_ready": draft.schedule.get("analysis") is not None,
        "camera_aligned": draft.camera_aligned,
        "camera_preview_ready": draft.camera_preview_ready,
        "can_activate": (
            scheduler_responding
            and storage["status"] != "insufficient"
            and draft.camera_aligned
            and (
                not draft.form.analysis_enabled
                or draft.schedule.get("analysis") is not None
            )
        ),
        "already_active": bool(
            comparable and comparable.get("hash") == draft.schedule_hash
        ),
        "replacing_active": bool(active and active.get("lifecycle") == "active"),
        "replacing_schedule": bool(comparable),
    }
