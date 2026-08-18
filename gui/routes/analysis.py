from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gui.services.analysis_preview import (
    build_analysis_preview,
    build_roi_preview,
)
from phenara.config import SCHEDULE_DRAFT_PATH
from gui.services.schedule_drafts import (
    attach_analysis_profile_to_draft,
    load_current_schedule_draft,
)
from scripts.analysis.profile import AnalysisProfile
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.roi import RoiDefinition


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisCropRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fits_image(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Analysis area must fit within the image.")
        return self


class MaskPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class MaskStrokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    radius: float = Field(ge=0.002, le=0.1)
    points: list[MaskPointRequest] = Field(min_length=1, max_length=2000)


class AnalysisPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_data: str = Field(min_length=1, max_length=13_500_000)
    config: dict = Field(default_factory=dict)
    analysis_crop: AnalysisCropRequest | None = None
    mask_exclusions: list[MaskStrokeRequest] = Field(
        default_factory=list, max_length=200
    )


class RoiPreviewRequest(AnalysisPreviewRequest):
    analysis_crop: AnalysisCropRequest


class SaveAnalysisProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict
    roi: dict


@router.get("/configure")
def configure_analysis() -> dict:
    loaded = load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    workflow_available = bool(
        loaded and loaded[0].form.analysis_enabled
    )
    return {
        "config": AnalysisConfig().to_dict(),
        "workflow_available": workflow_available,
        "camera_aligned": bool(
            workflow_available and loaded[0].camera_aligned
        ),
        "profile_saved": bool(
            workflow_available and loaded[0].schedule.get("analysis")
        ),
    }


@router.post("/preview")
def preview_analysis(request: AnalysisPreviewRequest) -> dict:
    try:
        return build_analysis_preview(
            request.image_data,
            request.config,
            (
                request.analysis_crop.model_dump()
                if request.analysis_crop is not None
                else None
            ),
            [stroke.model_dump() for stroke in request.mask_exclusions],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/roi")
def detect_analysis_roi(request: RoiPreviewRequest) -> dict:
    try:
        return build_roi_preview(
            request.image_data,
            request.config,
            request.analysis_crop.model_dump(),
            [stroke.model_dump() for stroke in request.mask_exclusions],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/profile")
def save_analysis_profile(request: SaveAnalysisProfileRequest) -> dict:
    loaded = load_current_schedule_draft(SCHEDULE_DRAFT_PATH)
    if loaded is None:
        raise HTTPException(
            status_code=409,
            detail="Create an analysis-enabled experiment draft first.",
        )
    if not loaded[0].camera_aligned:
        raise HTTPException(
            status_code=409,
            detail="Confirm the camera alignment before calibrating analysis.",
        )
    try:
        profile = AnalysisProfile(
            schema_version=1,
            config=AnalysisConfig.from_dict(request.config),
            roi=RoiDefinition.from_dict(request.roi),
        )
        attach_analysis_profile_to_draft(
            profile,
            draft_path=SCHEDULE_DRAFT_PATH,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The analysis setup could not be saved.",
        ) from exc
    return {
        "saved": True,
        "config_fingerprint": profile.config.fingerprint,
        "roi_fingerprint": profile.roi.fingerprint,
    }


@router.delete("/profile", status_code=204)
def delete_analysis_profile() -> None:
    raise HTTPException(
        status_code=409,
        detail="Analysis calibration is managed with its experiment draft.",
    )
