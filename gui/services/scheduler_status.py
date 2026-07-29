from __future__ import annotations

from collections import Counter
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.scheduling.heartbeat import HEARTBEAT_STATES
from scripts.scheduling.schedule import Schedule
from gui.services.storage_estimate import estimate_storage_bytes


STALE_AFTER = timedelta(seconds=30)


def build_schedule_overview(
    snapshot: dict,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Turn a loaded heartbeat schedule snapshot into dashboard data."""
    tz = ZoneInfo(snapshot["timezone"])
    configured = Schedule.from_dict(snapshot)
    normalized = configured.to_dict()
    run = configured.run.to_dict() if configured.run is not None else None
    schedule_hash = str(snapshot["hash"])
    local_now = now.astimezone(tz)
    run_times = configured.expand(tz)
    start_date = configured.start_date
    end_date = configured.end_date

    elapsed = [run_time for run_time in run_times if run_time < local_now]
    remaining = [run_time for run_time in run_times if run_time >= local_now]

    if not run_times:
        lifecycle = "empty"
    elif local_now < run_times[0]:
        lifecycle = "upcoming"
    elif local_now <= run_times[-1]:
        lifecycle = "active"
    else:
        lifecycle = "finished"

    total = len(run_times)
    progress = 0.0 if total == 0 else round(len(elapsed) / total * 100, 1)
    current_day = None
    if start_date <= local_now.date() <= end_date:
        current_day = (local_now.date() - start_date).days + 1

    days = []
    for offset in range(normalized["num_days"]):
        day_date = start_date + timedelta(days=offset)
        day_runs = [value for value in run_times if value.date() == day_date]
        day_elapsed = sum(value < local_now for value in day_runs)
        if day_date < local_now.date():
            day_status = "complete"
        elif day_date == local_now.date():
            day_status = "current"
        else:
            day_status = "upcoming"
        days.append(
            {
                "number": offset + 1,
                "date": day_date.isoformat(),
                "status": day_status,
                "elapsed_captures": day_elapsed,
                "total_captures": len(day_runs),
            }
        )

    daily_activity = build_daily_activity(
        normalized["times"],
        replicates=normalized["replicates"],
    )

    return {
        "lifecycle": lifecycle,
        "hash": schedule_hash,
        "timezone": snapshot["timezone"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "num_days": normalized["num_days"],
        "current_day": current_day,
        "times": normalized["times"],
        "daily_time_points": configured.daily_time_points,
        "varies_by_day": bool(configured.daily_times),
        "replicates": normalized["replicates"],
        "replicate_interval_seconds": normalized[
            "replicate_interval_seconds"
        ],
        "daily_captures": configured.daily_captures,
        "total_captures": total,
        "elapsed_captures": len(elapsed),
        "remaining_captures": len(remaining),
        "estimated_remaining_storage_bytes": estimate_storage_bytes(
            len(remaining)
        ),
        "progress_percent": progress,
        "first_capture_at": _iso_or_none(run_times[0] if run_times else None),
        "next_capture_at": _iso_or_none(remaining[0] if remaining else None),
        "last_capture_at": _iso_or_none(run_times[-1] if run_times else None),
        "days": days,
        "daily_activity": daily_activity,
        "replicate_offsets": [
            {
                "number": index + 1,
                "offset_seconds": index
                * normalized["replicate_interval_seconds"],
            }
            for index in range(normalized["replicates"])
        ],
        "run": run,
    }


def build_daily_activity(
    times: list[str],
    *,
    replicates: int = 1,
) -> dict[str, Any]:
    """Summarize daily capture load as hourly activity and cadence."""
    minutes = sorted(_time_to_minutes(value) for value in times)
    counts = [0] * 24
    for value in minutes:
        counts[value // 60] += 1
    peak_time_points = max(counts, default=0)
    peak_captures = peak_time_points * replicates
    hours = [
        {
            "hour": hour,
            "label": f"{hour:02d}:00",
            "time_point_count": count,
            "capture_count": count * replicates,
            "intensity_percent": (
                0
                if peak_time_points == 0
                else round(count / peak_time_points * 100, 1)
            ),
        }
        for hour, count in enumerate(counts)
    ]

    cadence_kind, cadence_minutes = _summarize_cadence(minutes)
    cadence_label = {
        "empty": "No time points",
        "single": "Single time point",
        "variable": "Variable intervals",
    }.get(cadence_kind)
    if cadence_kind == "regular":
        cadence_label = f"Every {_format_duration(cadence_minutes)}"
    elif cadence_kind == "typical":
        cadence_label = f"Typically every {_format_duration(cadence_minutes)}"

    first = times[0] if times else None
    last = times[-1] if times else None
    window_minutes = minutes[-1] - minutes[0] if minutes else 0
    return {
        "hours": hours,
        "first_time": first,
        "last_time": last,
        "window_minutes": window_minutes,
        "window_duration_label": _format_duration(window_minutes),
        "window_label": (
            f"{first}–{last}" if first is not None and last is not None else "—"
        ),
        "cadence_kind": cadence_kind,
        "cadence_minutes": cadence_minutes,
        "cadence_label": cadence_label,
        "peak_time_points_per_hour": peak_time_points,
        "peak_captures_per_hour": peak_captures,
    }


def _summarize_cadence(minutes: list[int]) -> tuple[str, int | None]:
    if not minutes:
        return "empty", None
    if len(minutes) == 1:
        return "single", None
    deltas = [end - start for start, end in zip(minutes, minutes[1:])]
    cadence, frequency = Counter(deltas).most_common(1)[0]
    if frequency == len(deltas):
        return "regular", cadence
    if frequency / len(deltas) >= 0.75:
        return "typical", cadence
    return "variable", None


def read_scheduler_status(
    heartbeat_path: Path,
    *,
    now: datetime | None = None,
    stale_after: timedelta = STALE_AFTER,
) -> dict[str, Any]:
    """Read scheduler health and its last reported loaded schedule."""
    current_time = now or datetime.now(timezone.utc)
    heartbeat = _read_heartbeat(
        heartbeat_path,
        now=current_time,
        stale_after=stale_after,
    )
    if heartbeat is None:
        return _unavailable_status()
    payload, health = heartbeat

    overview = None
    schedule_error = None
    snapshot = payload.get("schedule")
    if snapshot is not None:
        try:
            overview = build_schedule_overview(snapshot, now=current_time)
        except (KeyError, TypeError, ValueError):
            schedule_error = "The loaded schedule details could not be read."

    return {
        **health,
        "schedule": overview,
        "schedule_error": schedule_error,
        "schedule_is_last_reported": health["status"] == "stale"
        and overview is not None,
        "last_capture": _optional_dict(payload.get("last_capture")),
        "capture_summary": _optional_dict(payload.get("capture_summary")),
        "recent_captures": _dict_list(payload.get("recent_captures")),
        "daily_capture_progress": _optional_dict(
            payload.get("daily_capture_progress")
        ),
        "analysis_summary": _optional_dict(payload.get("analysis_summary")),
        "storage": _optional_dict(payload.get("storage")),
    }


def read_scheduler_health(
    heartbeat_path: Path,
    *,
    now: datetime | None = None,
    stale_after: timedelta = STALE_AFTER,
) -> dict[str, Any]:
    """Read only the scheduler fields needed by the global health pill."""
    heartbeat = _read_heartbeat(
        heartbeat_path,
        now=now or datetime.now(timezone.utc),
        stale_after=stale_after,
    )
    return _unavailable_health() if heartbeat is None else heartbeat[1]


def _read_heartbeat(
    heartbeat_path: Path,
    *,
    now: datetime,
    stale_after: timedelta,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        payload = json.loads(heartbeat_path.read_text())
        timestamp = datetime.fromisoformat(payload["timestamp"])
        state = payload["state"]
        message = payload["message"]
        if payload.get("version") != 1 or timestamp.tzinfo is None:
            raise ValueError("unsupported heartbeat")
        if state not in HEARTBEAT_STATES or not isinstance(message, str):
            raise ValueError("invalid heartbeat state")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

    age_seconds = max(
        0.0,
        (now.astimezone(timezone.utc) - timestamp).total_seconds(),
    )
    if age_seconds > stale_after.total_seconds():
        status = "stale"
        message = "The scheduler heartbeat has stopped updating."
    else:
        status = {
            "running": "healthy",
            "waiting_for_schedule": "waiting_for_schedule",
            "invalid_schedule": "invalid_schedule",
        }[state]

    return payload, {
        "status": status,
        "last_heartbeat_at": timestamp.isoformat(),
        "age_seconds": round(age_seconds, 1),
        "message": message,
    }


def _unavailable_status() -> dict[str, Any]:
    return {
        **_unavailable_health(),
        "schedule": None,
        "schedule_error": None,
        "schedule_is_last_reported": False,
        "last_capture": None,
        "capture_summary": None,
        "recent_captures": [],
        "daily_capture_progress": None,
        "analysis_summary": None,
        "storage": None,
    }


def _unavailable_health() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "last_heartbeat_at": None,
        "age_seconds": None,
        "message": "No valid scheduler heartbeat is available.",
    }


def _time_to_minutes(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour * 60 + parsed.minute


def _format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    hours, remaining = divmod(minutes, 60)
    if hours and remaining:
        return f"{hours} hr {remaining} min"
    if hours:
        return f"{hours} hr"
    return f"{remaining} min"


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_dict(value: Any) -> dict | None:
    return value if isinstance(value, dict) else None


def _dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
