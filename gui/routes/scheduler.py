from __future__ import annotations

from datetime import datetime
import hashlib
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from uuid import UUID

from phenopi.config import (
    CAPTURE_OUTPUT_ROOT,
    SCHEDULE_DRAFT_PATH,
    SCHEDULER_COMMAND_PATH,
    SCHEDULER_HEARTBEAT_PATH,
)
from gui.services.experiment_exports import (
    ExperimentExportError,
    capture_image_path,
    delete_experiment_data,
    download_path,
    export_details,
    validate_finished_experiment,
)
from gui.services.schedule_drafts import load_current_schedule_draft
from gui.services.scheduler_status import (
    read_scheduler_health,
    read_scheduler_status,
)
from scripts.scheduling.commands import (
    read_schedule_cancellation,
    request_schedule_cancellation,
)
from scripts.scheduling.experiment_registry import ExperimentRegistry, REGISTRY_FILENAME


router = APIRouter()


class CancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_hash: str


class ExperimentDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_hash: str
    experiment_name: str
    archive_saved_confirmed: bool = False


def schedule_draft_state() -> str:
    """Return the scheduler-page action state for the persisted draft."""
    try:
        draft = load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    except ValueError:
        return "invalid"
    return "ready" if draft is not None else "none"


@router.get("/api/scheduler/status")
def scheduler_status_api() -> dict:
    status = _hide_deleted_finished_experiment(
        read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    )
    schedule_hash = (status.get("schedule") or {}).get("hash")
    return {
        **status,
        "draft_state": schedule_draft_state(),
        "cancellation_pending": _cancellation_pending(schedule_hash),
    }


@router.post("/api/scheduler/cancel", status_code=202)
def cancel_scheduled_experiment(request: CancellationRequest) -> dict:
    status = read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    scheduled = status.get("schedule")
    if status["status"] in {"stale", "unavailable"}:
        raise HTTPException(
            status_code=503,
            detail="The scheduler is not responding. The experiment cannot be stopped safely.",
        )
    if not scheduled or scheduled.get("lifecycle") not in {"active", "upcoming"}:
        raise HTTPException(
            status_code=409,
            detail="No active or upcoming experiment can be cancelled.",
        )
    if scheduled.get("hash") != request.schedule_hash:
        raise HTTPException(
            status_code=409,
            detail="The active schedule changed. Refresh before stopping the experiment.",
        )
    try:
        request_schedule_cancellation(SCHEDULER_COMMAND_PATH, request.schedule_hash)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The cancellation request could not be saved.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"accepted": True, "schedule_hash": request.schedule_hash}


def _cancellation_pending(schedule_hash: str | None) -> bool:
    try:
        request = read_schedule_cancellation(SCHEDULER_COMMAND_PATH)
    except ValueError:
        return False
    return bool(request and request.schedule_hash == schedule_hash)


@router.get("/api/scheduler/health")
def scheduler_health_api() -> dict:
    return read_scheduler_health(SCHEDULER_HEARTBEAT_PATH)


@router.get("/api/scheduler/capture-image")
def current_capture_image(
    scheduled_at: datetime = Query(),
) -> FileResponse:
    status = read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    schedule = status.get("schedule")
    if not schedule or not schedule.get("run"):
        raise HTTPException(status_code=404, detail="No experiment image is available.")
    try:
        image = capture_image_path(CAPTURE_OUTPUT_ROOT, schedule, scheduled_at)
    except ExperimentExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        image,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/api/experiments/{run_id}")
def finished_experiment(run_id: UUID) -> dict:
    schedule = _finished_schedule(run_id)
    try:
        details = export_details(CAPTURE_OUTPUT_ROOT, schedule)
    except ExperimentExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    details["capture_summary"] = read_scheduler_status(
        SCHEDULER_HEARTBEAT_PATH
    ).get("capture_summary")
    return details


@router.get("/api/experiments/{run_id}/download")
def download_finished_experiment(run_id: UUID) -> FileResponse:
    schedule = _finished_schedule(run_id)
    try:
        archive = download_path(CAPTURE_OUTPUT_ROOT, schedule)
    except ExperimentExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=archive.name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/api/experiments/{run_id}", status_code=204)
def remove_finished_experiment(
    run_id: UUID,
    request: ExperimentDeletionRequest,
) -> None:
    schedule = _finished_schedule(run_id)
    expected_name = schedule["run"]["name"]
    if (
        request.schedule_hash != schedule["hash"]
        or request.experiment_name != expected_name
    ):
        raise HTTPException(
            status_code=409,
            detail="The deletion confirmation does not match this experiment.",
        )
    if not request.archive_saved_confirmed:
        raise HTTPException(
            status_code=409,
            detail="Confirm that the downloaded archive was saved before deletion.",
        )
    try:
        archive = download_path(CAPTURE_OUTPUT_ROOT, schedule)
        archive_size = archive.stat().st_size
        archive_sha256 = _sha256(archive)
        archive_name = archive.name
        delete_experiment_data(CAPTURE_OUTPUT_ROOT, schedule)
        now = datetime.now(timezone.utc).isoformat()
        registry = ExperimentRegistry(
            SCHEDULER_HEARTBEAT_PATH.parent / REGISTRY_FILENAME
        )
        registry.mark_deleted(
            str(run_id),
            archive_name=archive_name,
            archive_size_bytes=archive_size,
            archive_sha256=archive_sha256,
            exported_at=now,
            deleted_at=now,
        )
    except ExperimentExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The experiment data could not be deleted.",
        ) from exc


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finished_schedule(run_id: UUID) -> dict:
    status = read_scheduler_status(SCHEDULER_HEARTBEAT_PATH)
    try:
        schedule = validate_finished_experiment(status, run_id)
        if export_details(CAPTURE_OUTPUT_ROOT, schedule)["state"] == "deleted":
            raise ExperimentExportError(
                "This finished experiment is no longer available."
            )
        return schedule
    except ExperimentExportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _hide_deleted_finished_experiment(status: dict) -> dict:
    """Present a deleted completed run as an empty scheduler."""
    schedule = status.get("schedule")
    if not schedule or schedule.get("lifecycle") != "finished":
        return status
    try:
        deleted = (
            export_details(CAPTURE_OUTPUT_ROOT, schedule)["state"] == "deleted"
        )
    except (ExperimentExportError, OSError, KeyError, TypeError, ValueError):
        return status
    if not deleted:
        return status
    return {
        **status,
        "schedule": None,
        "schedule_error": None,
        "schedule_is_last_reported": False,
        "last_capture": None,
        "capture_summary": None,
        "recent_captures": [],
        "daily_capture_progress": None,
        "analysis_summary": None,
    }
