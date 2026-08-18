from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


DEVELOPMENT_MODE_VERSION = 1
CALIBRATION_IMAGE_NAME = "calibration.jpg"
DEVELOPMENT_MARKER_NAME = "DEVELOPMENT_DATA.txt"
_NATURAL_PART = re.compile(r"(\d+)")


def read_development_mode(path: Path) -> bool:
    """Read persistent development mode, defaulting safely to production."""
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("Development mode state could not be read.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != DEVELOPMENT_MODE_VERSION
        or not isinstance(payload.get("enabled"), bool)
    ):
        raise ValueError("Development mode state is invalid.")
    return payload["enabled"]


def write_development_mode(path: Path, enabled: bool) -> None:
    payload: dict[str, Any] = {
        "version": DEVELOPMENT_MODE_VERSION,
        "enabled": enabled,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def _atomic_write_text(path: Path, contents: str) -> None:
    """Persist capture mode without importing the scheduling/analysis stack."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def calibration_image(image_dir: Path) -> Path:
    path = image_dir / CALIBRATION_IMAGE_NAME
    if not path.is_file():
        raise ValueError(
            f"Development calibration image is missing: {path}"
        )
    return path


def sequence_images(image_dir: Path) -> list[Path]:
    if not image_dir.is_dir():
        raise ValueError(
            f"Development sample directory is missing: {image_dir}"
        )
    images = [
        path
        for path in image_dir.iterdir()
        if path.is_file()
        and path.name.casefold() != CALIBRATION_IMAGE_NAME
        and path.suffix.casefold() in {".jpg", ".jpeg"}
    ]
    images.sort(key=lambda path: natural_key(path.name))
    if not images:
        raise ValueError(
            "Development sample directory contains no capture-sequence JPEGs."
        )
    return images


def validate_development_images(image_dir: Path) -> dict[str, Any]:
    calibration = calibration_image(image_dir)
    images = sequence_images(image_dir)
    return {
        "calibration_image": calibration.name,
        "sequence_images": len(images),
    }


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NATURAL_PART.split(value)
    )
