from __future__ import annotations

import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from gui.services.development_mode import (
    development_status,
    set_development_mode,
)
from gui.services.schedule_drafts import (
    load_current_schedule_draft,
    record_camera_preview,
)
from phenopi.config import (
    CAMERA_PREVIEW_PATH,
    CAPTURE_SCRIPT_PATH,
    DEVELOPMENT_IMAGE_DIR,
    DEVELOPMENT_MODE_PATH,
    PYTHON_BIN,
    SCHEDULE_DRAFT_PATH,
    SCHEDULER_HEARTBEAT_PATH,
)


router = APIRouter(prefix="/api", tags=["development"])


class DevelopmentModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _status() -> dict:
    return development_status(
        mode_path=DEVELOPMENT_MODE_PATH,
        image_dir=DEVELOPMENT_IMAGE_DIR,
        draft_path=SCHEDULE_DRAFT_PATH,
        heartbeat_path=SCHEDULER_HEARTBEAT_PATH,
    )


@router.get("/development/status")
def get_development_status() -> dict:
    try:
        return _status()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/development/status")
def update_development_status(request: DevelopmentModeRequest) -> dict:
    try:
        return set_development_mode(
            request.enabled,
            mode_path=DEVELOPMENT_MODE_PATH,
            image_dir=DEVELOPMENT_IMAGE_DIR,
            draft_path=SCHEDULE_DRAFT_PATH,
            heartbeat_path=SCHEDULER_HEARTBEAT_PATH,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Development mode could not be updated.",
        ) from exc


@router.post("/camera/preview")
def acquire_camera_preview() -> FileResponse:
    try:
        loaded = load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if loaded is None:
        raise HTTPException(
            status_code=409,
            detail="Create an experiment draft before acquiring a camera preview.",
        )
    CAMERA_PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                str(PYTHON_BIN),
                str(CAPTURE_SCRIPT_PATH),
                "--output-path",
                str(CAMERA_PREVIEW_PATH),
                "--calibration-preview",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        record_camera_preview(SCHEDULE_DRAFT_PATH)
    except subprocess.CalledProcessError as exc:
        message = _capture_error_detail(exc.stderr)
        raise HTTPException(
            status_code=503,
            detail=message,
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The camera preview could not be stored.",
        ) from exc
    return _preview_response()


def _capture_error_detail(stderr: str | None) -> str:
    if stderr:
        final_line = stderr.strip().splitlines()[-1]
        for prefix in ("RuntimeError: ", "ValueError: "):
            if final_line.startswith(prefix):
                return final_line.removeprefix(prefix)
    return "The camera preview could not be acquired."


@router.get("/camera/preview")
def get_camera_preview() -> FileResponse:
    try:
        loaded = load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if loaded is None or not loaded[0].camera_preview_ready:
        raise HTTPException(
            status_code=404,
            detail="No confirmed camera preview is available.",
        )
    return _preview_response()


def _preview_response() -> FileResponse:
    if not CAMERA_PREVIEW_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail="No camera preview is available.",
        )
    return FileResponse(
        CAMERA_PREVIEW_PATH,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )
