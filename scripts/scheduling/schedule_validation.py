from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Hashable, TypeVar


T = TypeVar("T", bound=Hashable)

MAX_EXPERIMENT_DAYS = 365
MAX_REPLICATES = 100
MAX_REPLICATE_INTERVAL_SECONDS = 86_400
MAX_WINDOW_MINUTES = 1439
MAX_STEP_MINUTES = 1440
MAX_TOTAL_CAPTURES = 100_000


def validate_schedule_size(
    *,
    num_days: int,
    daily_time_points: int,
    replicates: int,
    replicate_interval_seconds: int,
) -> None:
    """Reject unsafe values before date arithmetic or large allocations."""
    _bounded(num_days, 1, MAX_EXPERIMENT_DAYS, "Number of days")
    _bounded(replicates, 1, MAX_REPLICATES, "Replicates")
    _bounded(
        replicate_interval_seconds,
        0,
        MAX_REPLICATE_INTERVAL_SECONDS,
        "Replicate interval",
    )
    if daily_time_points <= 0:
        raise ScheduleValidationError("The schedule must contain a capture time.")
    total = num_days * daily_time_points * replicates
    if total > MAX_TOTAL_CAPTURES:
        raise ScheduleValidationError(
            f"The schedule contains {total:,} captures; the maximum is "
            f"{MAX_TOTAL_CAPTURES:,}. Reduce the days, time points, or replicates."
        )


def validate_replicate_windows(
    base_seconds: Iterable[int],
    *,
    replicates: int,
    replicate_interval_seconds: int,
) -> None:
    """Require every replicate burst to finish before the next time point."""
    ordered = sorted(set(base_seconds))
    if not ordered or replicates <= 1:
        return
    burst_seconds = (replicates - 1) * replicate_interval_seconds
    for current, following in zip(ordered, ordered[1:]):
        if current + burst_seconds >= following:
            raise ScheduleValidationError(
                f"Replicates for {_clock(current)} must finish before the "
                f"next time point at {_clock(following)}. Reduce the replicate "
                "count or interval."
            )
    if ordered[-1] + burst_seconds >= 24 * 60 * 60:
        raise ScheduleValidationError(
            f"Replicates for {_clock(ordered[-1])} must finish before midnight. "
            "Reduce the replicate count or interval."
        )


def _clock(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _bounded(value: int, minimum: int, maximum: int, label: str) -> None:
    if value < minimum or value > maximum:
        raise ScheduleValidationError(
            f"{label} must be between {minimum:,} and {maximum:,}."
        )


class ScheduleValidationError(ValueError):
    """
    Raised when a schedule is invalid.

    This exception is intended for user-facing schedule validation errors, such
    as duplicate capture times or invalid schedule settings. Command-line tools
    can catch this exception and report a concise error message without showing
    a full traceback.
    """


def format_duplicate_values(
    duplicates: Iterable[str],
    max_display: int = 5,
) -> str:
    """
    Format duplicate values for display in an error message.

    Parameters
    ----------
    duplicates : Iterable[str]
        Duplicate values formatted as strings.
    max_display : int, optional
        Maximum number of duplicate values to include explicitly.

    Returns
    -------
    str
        Formatted duplicate-value summary.
    """
    sorted_duplicates = sorted(duplicates)
    shown = sorted_duplicates[:max_display]

    duplicate_text = ", ".join(shown)
    remaining = len(sorted_duplicates) - len(shown)

    if remaining > 0:
        duplicate_text += f", ... ({remaining} more)"

    return duplicate_text


def validate_unique_values(
    values: Iterable[T],
    *,
    label: str = "schedule",
    value_name: str = "capture time",
    formatter: Callable[[T], str] = str,
) -> None:
    """
    Check that values are unique.

    Parameters
    ----------
    values : Iterable[T]
        Values to check for duplicates.
    label : str, optional
        Description of the object being validated.
    value_name : str, optional
        Name of the duplicated value type used in the error message.
    formatter : Callable[[T], str], optional
        Function used to format duplicate values for display.

    Raises
    ------
    ScheduleValidationError
        If duplicate values are present.
    """
    seen: set[T] = set()
    duplicates: set[T] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    if not duplicates:
        return

    duplicate_text = format_duplicate_values(
        formatter(value) for value in duplicates
    )
    duplicate_count = len(duplicates)

    raise ScheduleValidationError(
        f"{label} contains {duplicate_count} duplicate {value_name}(s). "
        f"First duplicates: {duplicate_text}. This usually means "
        "that replicate captures overlap with other scheduled captures. "
        "Increase --step-minutes, reduce --replicates, or reduce "
        "--replicate-interval-seconds."
    )
