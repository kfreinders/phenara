from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gui.services.schedule_builder import SchedulePreview


@dataclass(frozen=True)
class ScheduleComparison:
    rows: list[dict[str, Any]]
    has_active_schedule: bool
    changed: bool


def compare_schedules(
    preview: SchedulePreview,
    active: dict[str, Any] | None,
) -> ScheduleComparison:
    active_range = None
    if active:
        active_range = active["start_date"]
        if active["num_days"] != 1:
            active_range += f" → {active['end_date']}"
    values = [
        ("Date range", active_range, preview.date_range_label),
        ("Experiment days", active.get("num_days") if active else None, preview.num_days),
        (
            "Daily time points",
            active.get("daily_time_points") if active else None,
            preview.daily_time_points,
        ),
        (
            "Technical replicates",
            active.get("replicates") if active else None,
            preview.replicates,
        ),
        (
            "Replicate spacing",
            f'{active.get("replicate_interval_seconds")} s' if active else None,
            f"{preview.replicate_interval_seconds} s",
        ),
        (
            "Daily captures",
            active.get("daily_captures") if active else None,
            preview.daily_captures,
        ),
        (
            "Total captures",
            active.get("total_captures") if active else None,
            preview.total_captures,
        ),
    ]
    rows = [
        {"label": label, "active": old, "draft": new, "changed": old != new}
        for label, old, new in values
    ]
    return ScheduleComparison(
        rows=rows,
        has_active_schedule=active is not None,
        changed=any(row["changed"] for row in rows),
    )
