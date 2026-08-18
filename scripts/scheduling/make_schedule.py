from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile

from .schedule_validation import (
    MAX_STEP_MINUTES,
    MAX_WINDOW_MINUTES,
    validate_replicate_windows,
    validate_schedule_size,
    validate_unique_values,
)
from .schedule import Schedule


def every_n_minutes(start: str, end: str, step_minutes: int) -> list[str]:
    """
    Generate times at a fixed interval between two clock times.

    The returned list includes both the start time and, if reached exactly by
    stepping, the end time. All times are formatted as "HH:MM".

    Parameters
    ----------
    start : str
        Start time in 24-hour "HH:MM" format.
    end : str
        End time in 24-hour "HH:MM" format.
    step_minutes : int
        Interval between consecutive times, in minutes. Must be greater than 0.

    Returns
    -------
    list[str]
        Sorted list of time strings from `start` to `end`, inclusive where
        applicable.

    Raises
    ------
    ValueError
        If `step_minutes` is not greater than 0, or if `start` or `end` are not
        valid "HH:MM" strings.

    Examples
    --------
    >>> every_n_minutes("09:00", "10:00", 30)
    ['09:00', '09:30', '10:00']

    The end time is only included if it falls exactly on a step.

    >>> every_n_minutes("09:00", "09:45", 30)
    ['09:00', '09:30']
    """
    if step_minutes <= 0:
        raise ValueError("step_minutes must be > 0")
    if step_minutes > MAX_STEP_MINUTES:
        raise ValueError(f"step_minutes must be <= {MAX_STEP_MINUTES}")

    times: list[str] = []
    current = datetime.strptime(start, "%H:%M")
    end_dt = datetime.strptime(end, "%H:%M")
    if end_dt < current:
        raise ValueError("end time must not be earlier than start time")

    while current <= end_dt:
        times.append(current.strftime("%H:%M"))
        current += timedelta(minutes=step_minutes)

    return times


def every_n_minutes_for_duration(
    start: str,
    duration_minutes: int,
    step_minutes: int,
) -> list[str]:
    """
    Generate times at a fixed interval starting from a given time and duration.

    The returned list starts at `start` and continues in steps of
    `step_minutes` until the specified duration has been covered. The start
    time is always included, and the final time is included if it falls exactly
    on a step.

    Parameters
    ----------
    start : str
        Start time in 24-hour "HH:MM" format.
    duration_minutes : int
        Total duration to cover, in minutes. Must be greater than or equal to
        0.
    step_minutes : int
        Interval between consecutive times, in minutes. Must be greater than 0.

    Returns
    -------
    list[str]
        List of time strings in "HH:MM" format spanning the requested duration.

    Raises
    ------
    ValueError
        If `duration_minutes` is negative.
    ValueError
        If `step_minutes` is not greater than 0, or if `start` is not a valid
        "HH:MM" string.

    Examples
    --------
    >>> every_n_minutes_for_duration("12:00", 60, 20)
    ['12:00', '12:20', '12:40', '13:00']

    The final time is omitted if the duration is not reached exactly by
    stepping.

    >>> every_n_minutes_for_duration("12:00", 45, 20)
    ['12:00', '12:20', '12:40']
    """
    if duration_minutes < 0:
        raise ValueError("duration_minutes must be >= 0")
    if duration_minutes > MAX_WINDOW_MINUTES:
        raise ValueError(f"duration_minutes must be <= {MAX_WINDOW_MINUTES}")
    if step_minutes <= 0:
        raise ValueError("step_minutes must be > 0")
    if step_minutes > MAX_STEP_MINUTES:
        raise ValueError(f"step_minutes must be <= {MAX_STEP_MINUTES}")

    times: list[str] = []
    current = datetime.strptime(start, "%H:%M")
    minutes_remaining = 23 * 60 + 59 - (current.hour * 60 + current.minute)
    if duration_minutes > minutes_remaining:
        raise ValueError("duration window must not cross midnight")
    end_dt = current + timedelta(minutes=duration_minutes)

    while current <= end_dt:
        times.append(current.strftime("%H:%M"))
        current += timedelta(minutes=step_minutes)

    return times


def centered_time_range(
    center: str,
    before_minutes: int,
    after_minutes: int,
    step_minutes: int,
) -> list[str]:
    """
    Generate capture times around a central time point.

    This is useful for creating a denser acquisition window around a treatment,
    watering event, stress application, or calibration time.

    Parameters
    ----------
    center : str
        Central time in 24-hour "HH:MM" format.
    before_minutes : int
        Number of minutes before `center` to include. Must be greater than or
        equal to 0.
    after_minutes : int
        Number of minutes after `center` to include. Must be greater than or
        equal to 0.
    step_minutes : int
        Interval between consecutive capture times, in minutes. Must be greater
        than 0.

    Returns
    -------
    list[str]
        Capture times in "HH:MM" format.

    Raises
    ------
    ValueError
        If `before_minutes` or `after_minutes` is negative, if `step_minutes`
        is not greater than 0, or if `center` is not a valid "HH:MM" string.

    Examples
    --------
    >>> centered_time_range("12:00", 60, 60, 30)
    ['11:00', '11:30', '12:00', '12:30', '13:00']

    The sequence is stepped from the calculated start time. The center is not
    forced into the output.

    >>> centered_time_range("12:00", 45, 45, 30)
    ['11:15', '11:45', '12:15', '12:45']
    """
    if before_minutes < 0:
        raise ValueError("before_minutes must be >= 0")
    if after_minutes < 0:
        raise ValueError("after_minutes must be >= 0")
    if step_minutes <= 0:
        raise ValueError("step_minutes must be > 0")
    if before_minutes > MAX_WINDOW_MINUTES or after_minutes > MAX_WINDOW_MINUTES:
        raise ValueError(f"centered window values must be <= {MAX_WINDOW_MINUTES}")
    if step_minutes > MAX_STEP_MINUTES:
        raise ValueError(f"step_minutes must be <= {MAX_STEP_MINUTES}")

    center_dt = datetime.strptime(center, "%H:%M")
    center_minutes = center_dt.hour * 60 + center_dt.minute
    if before_minutes > center_minutes or after_minutes > 1439 - center_minutes:
        raise ValueError("centered window must not cross midnight")
    start_dt = center_dt - timedelta(minutes=before_minutes)
    end_dt = center_dt + timedelta(minutes=after_minutes)

    times: list[str] = []
    current = start_dt

    while current <= end_dt:
        times.append(current.strftime("%H:%M"))
        current += timedelta(minutes=step_minutes)

    return times


def validate_unique_expanded_times(
    times: list[str],
    replicates: int,
    replicate_interval_seconds: int,
) -> None:
    """
    Check that the expanded daily capture schedule contains no duplicates.

    The check expands each base time according to the replicate settings and
    verifies that no two captures occur at the same clock time.

    Parameters
    ----------
    times : list[str]
        Base daily capture times in "HH:MM" format.
    replicates : int
        Number of captures per base time.
    replicate_interval_seconds : int
        Interval between repeated captures, in seconds.

    Raises
    ------
    ValueError
        If the expanded daily schedule contains duplicate capture times.
    """
    validate_schedule_size(
        num_days=1,
        daily_time_points=len(times),
        replicates=replicates,
        replicate_interval_seconds=replicate_interval_seconds,
    )
    base_datetimes = [datetime.strptime(value, "%H:%M") for value in times]
    validate_replicate_windows(
        [value.hour * 3600 + value.minute * 60 for value in base_datetimes],
        replicates=replicates,
        replicate_interval_seconds=replicate_interval_seconds,
    )
    expanded: list[str] = []

    for base in base_datetimes:

        for rep in range(replicates):
            capture_dt = base + timedelta(
                seconds=rep * replicate_interval_seconds
            )
            if capture_dt.date() != base.date():
                raise ValueError("replicate captures must not cross midnight")
            expanded.append(capture_dt.strftime("%H:%M:%S"))

    validate_unique_values(
        expanded,
        label="expanded schedule",
        value_name="capture time",
    )


def add_schedule_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start-date",
        required=True,
        help="Experiment start date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--num-days",
        type=int,
        required=True,
        help="Number of experiment days.",
    )
    parser.add_argument(
        "--replicates",
        type=int,
        default=1,
        help="Number of repeated captures per scheduled time point.",
    )
    parser.add_argument(
        "--replicate-interval-seconds",
        type=int,
        default=0,
        help="Interval between repeated captures, in seconds.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output schedule JSON path.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )


def write_schedule(
    output: Path,
    start_date: str,
    num_days: int,
    times: list[str],
    replicates: int = 1,
    replicate_interval_seconds: int = 0,
    run: dict | None = None,
    analysis: dict | None = None,
    daily_times: dict[str, list[str]] | None = None,
    overwrite: bool = False,
) -> None:
    for values in (daily_times or {"default": times}).values():
        validate_unique_expanded_times(
            times=values,
            replicates=replicates,
            replicate_interval_seconds=replicate_interval_seconds,
        )
    schedule = Schedule.create(
        start_date=start_date,
        num_days=num_days,
        times=times,
        replicates=replicates,
        replicate_interval_seconds=replicate_interval_seconds,
        run=run,
        analysis=analysis,
        daily_times=daily_times,
    )

    if output.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {output}. Use --overwrite to replace it."
        )

    atomic_write_text(output, schedule.to_json())


def schedule_json(schedule: dict | Schedule) -> str:
    """Serialize a schedule in the canonical on-disk representation."""
    if isinstance(schedule, Schedule):
        return schedule.to_json()
    return Schedule.from_dict(schedule).to_json()


def atomic_write_text(output: Path, contents: str) -> None:
    """Atomically replace a text file using a temporary sibling file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Phenara schedule JSON files."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    every = subparsers.add_parser(
        "every",
        help="Generate times between a start and end time.",
    )
    every.add_argument("--start", required=True, help="Start time, HH:MM.")
    every.add_argument("--end", required=True, help="End time, HH:MM.")
    every.add_argument(
        "--step-minutes",
        type=int,
        required=True,
        help="Interval between captures in minutes.",
    )
    add_schedule_output_args(every)

    duration = subparsers.add_parser(
        "duration",
        help="Generate times from a start time for a fixed duration.",
    )
    duration.add_argument("--start", required=True, help="Start time, HH:MM.")
    duration.add_argument(
        "--duration-minutes",
        type=int,
        required=True,
        help="Total duration in minutes.",
    )
    duration.add_argument(
        "--step-minutes",
        type=int,
        required=True,
        help="Interval between captures in minutes.",
    )
    add_schedule_output_args(duration)

    centered = subparsers.add_parser(
        "centered",
        help="Generate times around a central time point.",
    )
    centered.add_argument(
        "--center",
        required=True,
        help="Center time, HH:MM."
    )
    centered.add_argument(
        "--before-minutes",
        type=int,
        required=True,
        help="Minutes before center to include.",
    )
    centered.add_argument(
        "--after-minutes",
        type=int,
        required=True,
        help="Minutes after center to include.",
    )
    centered.add_argument(
        "--step-minutes",
        type=int,
        required=True,
        help="Interval between captures in minutes.",
    )
    add_schedule_output_args(centered)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        if args.command == "every":
            times = every_n_minutes(
                start=args.start,
                end=args.end,
                step_minutes=args.step_minutes,
            )
        elif args.command == "duration":
            times = every_n_minutes_for_duration(
                start=args.start,
                duration_minutes=args.duration_minutes,
                step_minutes=args.step_minutes,
            )
        elif args.command == "centered":
            times = centered_time_range(
                center=args.center,
                before_minutes=args.before_minutes,
                after_minutes=args.after_minutes,
                step_minutes=args.step_minutes,
            )
        else:
            raise ValueError(f"Unknown command: {args.command}")

        write_schedule(
            output=args.output,
            start_date=args.start_date,
            num_days=args.num_days,
            times=times,
            replicates=args.replicates,
            replicate_interval_seconds=args.replicate_interval_seconds,
            overwrite=args.overwrite,
        )

    except (ValueError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    daily_time_points = len(times)
    daily_captures = daily_time_points * args.replicates
    total_captures = daily_captures * args.num_days

    print(f"Wrote schedule: {args.output}")
    print(f"Daily time points: {daily_time_points}")
    print(f"Replicates per time point: {args.replicates}")
    print(f"Daily scheduled captures: {daily_captures}")
    print(f"Total scheduled captures: {total_captures}")


if __name__ == "__main__":
    main()
