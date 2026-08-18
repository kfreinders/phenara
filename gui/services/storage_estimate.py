from __future__ import annotations

from typing import Any


CAPTURE_IMAGE_BYTES = 7_600_000
SECONDARY_DATA_RESERVE_FACTOR = 2


def estimate_storage_bytes(capture_count: int) -> int:
    """Estimate raw captures plus an equal reserve for derived data."""
    return capture_count * CAPTURE_IMAGE_BYTES * SECONDARY_DATA_RESERVE_FACTOR


def assess_schedule_storage(
    capture_count: int,
    storage: dict[str, Any] | None,
) -> dict[str, Any]:
    required = estimate_storage_bytes(capture_count)
    free = storage.get("free_bytes") if isinstance(storage, dict) else None
    if not isinstance(free, (int, float)) or free < 0:
        state = "unverified"
        free = None
    else:
        state = "insufficient" if required > free else "sufficient"
    return {
        "status": state,
        "required_bytes": required,
        "required_label": format_bytes(required),
        "free_bytes": free,
        "free_label": format_bytes(free) if free is not None else None,
        "raw_bytes": capture_count * CAPTURE_IMAGE_BYTES,
        "raw_label": format_bytes(capture_count * CAPTURE_IMAGE_BYTES),
    }


def format_bytes(value: int | float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit = 0
    while size >= 1000 and unit < len(units) - 1:
        size /= 1000
        unit += 1
    if unit < 2:
        number = f"{size:.0f}"
    else:
        number = f"{size:.1f}".rstrip("0").rstrip(".")
    return f"{number} {units[unit]}"
