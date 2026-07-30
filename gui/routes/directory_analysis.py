from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4

import cv2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from scripts.analysis.analyze_canopy import analyze_images
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.roi import RoiDefinition


router = APIRouter(prefix="/api/directory-analysis", tags=["directory-analysis"])
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
_inspection_executor = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="directory-inspection"
)
_inspection_jobs: dict[str, dict] = {}
_inspection_lock = Lock()


class DirectoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directory: str = Field(min_length=1, max_length=4096)
    black_mean_threshold: float = Field(default=10.0, ge=0, le=255)


class DirectoryImageRequest(DirectoryRequest):
    image: str = Field(min_length=1, max_length=1024)


class RunDirectoryAnalysisRequest(DirectoryRequest):
    calibration_image: str = Field(min_length=1, max_length=1024)
    output_directory: str | None = Field(default=None, max_length=4096)
    config: dict
    roi: dict


def _directory(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")
    return path


def _image_path(directory: Path, name: str) -> Path:
    if Path(name).name != name:
        raise ValueError("Image must be a filename from the selected directory.")
    path = (directory / name).resolve()
    try:
        path.relative_to(directory)
    except ValueError as exc:
        raise ValueError("Image path escapes the selected directory.") from exc
    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("Selected image is not a supported image file.")
    return path


def _scan(
    directory: Path,
    threshold: float,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Path], int, int]:
    usable: list[Path] = []
    black = 0
    unreadable = 0
    candidates = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: path.name,
    )
    total = len(candidates)
    if progress is not None:
        progress(0, total)
    for completed, path in enumerate(candidates, start=1):
        # Mean brightness does not require a full-resolution decode. OpenCV's
        # reduced JPEG mode decodes at one eighth of the original width and
        # height, substantially reducing inspection time and memory use.
        image = cv2.imread(str(path), cv2.IMREAD_REDUCED_GRAYSCALE_8)
        if image is None:
            # Some codecs do not implement reduced decoding.
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            unreadable += 1
        elif float(image.mean()) <= threshold:
            black += 1
        else:
            usable.append(path)
        if progress is not None:
            progress(completed, total)
    return usable, black, unreadable


@router.post("/inspect")
def inspect_directory(request: DirectoryRequest) -> dict:
    try:
        directory = _directory(request.directory)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = uuid4().hex
    with _inspection_lock:
        _inspection_jobs[job_id] = {
            "status": "queued",
            "completed_images": 0,
            "total_images": 0,
        }
    _inspection_executor.submit(
        _run_inspection,
        job_id,
        directory,
        request.black_mean_threshold,
    )
    return {"job_id": job_id}


def _run_inspection(job_id: str, directory: Path, threshold: float) -> None:
    def update_progress(completed: int, total: int) -> None:
        with _inspection_lock:
            _inspection_jobs[job_id].update(
                {
                    "status": "running",
                    "completed_images": completed,
                    "total_images": total,
                }
            )

    try:
        usable, black, unreadable = _scan(
            directory, threshold, progress=update_progress
        )
        result = {
            "status": "completed",
            "completed_images": len(usable) + black + unreadable,
            "total_images": len(usable) + black + unreadable,
            "directory": str(directory),
            "images": [path.name for path in usable],
            "usable_count": len(usable),
            "black_excluded_count": black,
            "unreadable_excluded_count": unreadable,
        }
    except Exception as exc:
        result = {
            "status": "failed",
            "error": f"Directory inspection failed: {exc}",
        }
    with _inspection_lock:
        _inspection_jobs[job_id].update(result)


@router.get("/inspect/{job_id}")
def directory_inspection_status(job_id: str) -> dict:
    with _inspection_lock:
        result = _inspection_jobs.get(job_id)
        if result is None:
            raise HTTPException(
                status_code=404, detail="Directory inspection was not found."
            )
        return dict(result)


@router.post("/image")
def directory_image(request: DirectoryImageRequest) -> dict:
    try:
        directory = _directory(request.directory)
        path = _image_path(directory, request.image)
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("Calibration image could not be decoded.")
        if float(image.mean()) <= request.black_mean_threshold:
            raise ValueError("A black image cannot be used for calibration.")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"image_data": f"data:{mime};base64,{encoded}", "name": path.name}


@router.post("/run")
def run_directory_analysis(request: RunDirectoryAnalysisRequest) -> dict:
    try:
        directory = _directory(request.directory)
        usable, black, unreadable = _scan(
            directory, request.black_mean_threshold
        )
        if not usable:
            raise ValueError("No readable, non-black images are available.")
        calibration = _image_path(directory, request.calibration_image)
        if calibration not in usable:
            raise ValueError(
                "Calibration must use a readable, non-black image from the directory."
            )
        config = AnalysisConfig.from_dict(request.config)
        roi = RoiDefinition.from_dict(request.roi)
        output = (
            Path(request.output_directory).expanduser().resolve()
            if request.output_directory
            else directory / "analysis"
        )
        if output == directory:
            raise ValueError("Output directory must differ from the input directory.")
        output.mkdir(parents=True, exist_ok=True)
        config.save(output / "analysis_config.json")
        workers = max(1, (os.cpu_count() or 2) - 2)
        combined = analyze_images(
            usable,
            output,
            config,
            workers,
            roi_definition=roi,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "completed": True,
        "output_directory": str(output),
        "analyzed_images": len(usable),
        "result_rows": len(combined),
        "black_excluded_count": black,
        "unreadable_excluded_count": unreadable,
    }
