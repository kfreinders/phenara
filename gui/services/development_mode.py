from __future__ import annotations

from pathlib import Path

from gui.services.scheduler_status import read_scheduler_status
from phenopi.development import (
    read_development_mode,
    validate_development_images,
    write_development_mode,
)


def development_status(
    *,
    mode_path: Path,
    image_dir: Path,
    draft_path: Path,
    heartbeat_path: Path,
) -> dict:
    enabled = read_development_mode(mode_path)
    scheduler = read_scheduler_status(heartbeat_path)
    scheduled = scheduler.get("schedule")
    lifecycle = (scheduled or {}).get("lifecycle")

    reason = None
    if draft_path.exists():
        reason = "Finish or discard the current experiment draft first."
    elif scheduler["status"] in {"stale", "unavailable", "invalid_schedule"}:
        reason = "Scheduler state must be healthy before changing capture mode."
    elif lifecycle in {"active", "upcoming"}:
        reason = "Capture mode is locked while an experiment is scheduled."

    samples = None
    sample_error = None
    try:
        samples = validate_development_images(image_dir)
    except ValueError as exc:
        sample_error = str(exc)

    return {
        "enabled": enabled,
        "can_toggle": reason is None,
        "blocked_reason": reason,
        "sample_directory": str(image_dir),
        "samples": samples,
        "sample_error": sample_error,
    }


def set_development_mode(
    enabled: bool,
    *,
    mode_path: Path,
    image_dir: Path,
    draft_path: Path,
    heartbeat_path: Path,
) -> dict:
    status = development_status(
        mode_path=mode_path,
        image_dir=image_dir,
        draft_path=draft_path,
        heartbeat_path=heartbeat_path,
    )
    if not status["can_toggle"]:
        raise ValueError(status["blocked_reason"])
    if enabled:
        validate_development_images(image_dir)
    write_development_mode(mode_path, enabled)
    return development_status(
        mode_path=mode_path,
        image_dir=image_dir,
        draft_path=draft_path,
        heartbeat_path=heartbeat_path,
    )
