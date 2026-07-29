from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from scripts.scheduling.make_schedule import (
    centered_time_range,
    every_n_minutes,
    every_n_minutes_for_duration,
)
from scripts.scheduling.schedule import Schedule


class PastStartDateError(ValueError):
    """Raised when a schedule's start date has already passed."""


@dataclass
class SchedulePreview:
    mode: str
    schedule: Schedule

    @property
    def start_date(self) -> str:
        return self.schedule.start_date.isoformat()

    @property
    def num_days(self) -> int:
        return self.schedule.num_days

    @property
    def times(self) -> list[str]:
        return [value.strftime("%H:%M") for value in self.schedule.times]

    @property
    def replicates(self) -> int:
        return self.schedule.replicates

    @property
    def replicate_interval_seconds(self) -> int:
        return self.schedule.replicate_interval_seconds

    @property
    def daily_time_points(self) -> int:
        return self.schedule.daily_time_points

    @property
    def varies_by_day(self) -> bool:
        return bool(self.schedule.daily_times)

    @property
    def daily_captures(self) -> int:
        return self.schedule.daily_captures

    @property
    def total_captures(self) -> int:
        return self.schedule.total_captures

    @property
    def first_time(self) -> str:
        return self.times[0] if self.times else "—"

    @property
    def last_time(self) -> str:
        return self.times[-1] if self.times else "—"

    @property
    def end_date(self) -> str:
        return self.schedule.end_date.isoformat()

    @property
    def date_range_label(self) -> str:
        return (
            self.start_date
            if self.num_days == 1
            else f"{self.start_date} → {self.end_date}"
        )

    @property
    def summary_sentence(self) -> str:
        if self.varies_by_day:
            return (
                f"Capture timing varies by date, with up to "
                f"{self.daily_captures} images on a scheduled day and "
                f"{self.total_captures} images across the experiment."
            )
        time_point_word = "time point" if self.daily_time_points == 1 else "time points"
        replicate_word = "replicate" if self.replicates == 1 else "replicates"
        return (
            f"Phenopi will capture {self.daily_captures} images per day "
            f"across {self.daily_time_points} {time_point_word}, with "
            f"{self.replicates} technical {replicate_word} per time point."
        )

    @property
    def replicate_offsets(self) -> list[dict[str, int]]:
        return [
            {
                "number": index + 1,
                "offset_seconds": index * self.replicate_interval_seconds,
            }
            for index in range(self.replicates)
        ]

    @property
    def timeline_points(self) -> list[dict[str, float | str]]:
        if not self.times:
            return []
        start_minutes = _time_to_minutes(self.times[0])
        end_minutes = _time_to_minutes(self.times[-1])
        span = max(end_minutes - start_minutes, 1)
        return [
            {
                "time": time,
                "percent": round(
                    ((_time_to_minutes(time) - start_minutes) / span) * 100,
                    3,
                ),
            }
            for time in self.times
        ]

    def as_schedule_dict(self) -> dict[str, Any]:
        return self.schedule.to_dict()


def build_schedule_preview(
    *,
    mode: str,
    start_date: str,
    num_days: int,
    replicates: int,
    replicate_interval_seconds: int,
    every_start: str | None = None,
    every_end: str | None = None,
    every_step_minutes: int | None = None,
    duration_start: str | None = None,
    duration_minutes: int | None = None,
    duration_step_minutes: int | None = None,
    centered_center: str | None = None,
    centered_before_minutes: int | None = None,
    centered_after_minutes: int | None = None,
    centered_step_minutes: int | None = None,
    custom_days: list[dict[str, Any]] | None = None,
) -> SchedulePreview:
    _validate_start_date(start_date)
    times, daily_times = _build_times(
        mode=mode,
        every_start=every_start,
        every_end=every_end,
        every_step_minutes=every_step_minutes,
        duration_start=duration_start,
        duration_minutes=duration_minutes,
        duration_step_minutes=duration_step_minutes,
        centered_center=centered_center,
        centered_before_minutes=centered_before_minutes,
        centered_after_minutes=centered_after_minutes,
        centered_step_minutes=centered_step_minutes,
        custom_days=custom_days,
    )
    try:
        schedule = Schedule.create(
            start_date=start_date,
            num_days=num_days,
            times=times,
            replicates=replicates,
            replicate_interval_seconds=replicate_interval_seconds,
            daily_times=daily_times,
        )
    except ValueError as exc:
        if "supported calendar" in str(exc):
            raise ValueError(
                "The experiment date range exceeds the supported calendar."
            ) from exc
        raise

    return SchedulePreview(
        mode=mode,
        schedule=schedule,
    )


def _build_times(
    *,
    mode: str,
    every_start: str | None,
    every_end: str | None,
    every_step_minutes: int | None,
    duration_start: str | None,
    duration_minutes: int | None,
    duration_step_minutes: int | None,
    centered_center: str | None,
    centered_before_minutes: int | None,
    centered_after_minutes: int | None,
    centered_step_minutes: int | None,
    custom_days: list[dict[str, Any]] | None,
) -> tuple[list[str], dict[str, list[str]] | None]:
    if mode == "every":
        if every_start is None or every_end is None or every_step_minutes is None:
            raise ValueError("Every mode requires start, end, and step minutes.")
        return every_n_minutes(every_start, every_end, every_step_minutes), None
    if mode == "duration":
        if duration_start is None or duration_minutes is None or duration_step_minutes is None:
            raise ValueError("Duration mode requires start, duration, and step minutes.")
        return every_n_minutes_for_duration(
            duration_start, duration_minutes, duration_step_minutes
        ), None
    if mode == "centered":
        if (
            centered_center is None
            or centered_before_minutes is None
            or centered_after_minutes is None
            or centered_step_minutes is None
        ):
            raise ValueError(
                "Centered mode requires center, before, after, and step minutes."
            )
        return centered_time_range(
            centered_center,
            centered_before_minutes,
            centered_after_minutes,
            centered_step_minutes,
        ), None
    if mode == "custom":
        if not custom_days:
            raise ValueError("Custom mode requires at least one day block.")
        by_date: dict[str, list[str]] = {}
        for day_index, block in enumerate(custom_days, start=1):
            try:
                first = date.fromisoformat(str(block["start_date"]))
                last = date.fromisoformat(str(block["end_date"]))
                windows = block["windows"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Day block {day_index} has invalid dates.") from exc
            if last < first:
                raise ValueError(f"Day block {day_index} ends before it starts.")
            if not windows:
                raise ValueError(f"Day block {day_index} requires a capture range.")
            block_times = []
            for window_index, window in enumerate(windows, start=1):
                try:
                    block_times.extend(every_n_minutes(
                        str(window["start"]), str(window["end"]),
                        int(window["step_minutes"]),
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Day block {day_index}, capture range {window_index} "
                        f"is invalid: {exc}"
                    ) from exc
            current = first
            while current <= last:
                key = current.isoformat()
                if key in by_date:
                    raise ValueError(f"Day blocks overlap on {key}.")
                by_date[key] = sorted(set(block_times))
                current += timedelta(days=1)
        union = sorted({value for values in by_date.values() for value in values})
        return union, by_date
    raise ValueError(f"Unknown schedule mode: {mode!r}.")


def _validate_start_date(start_date: str) -> None:
    try:
        parsed = date.fromisoformat(start_date)
    except ValueError as exc:
        raise ValueError("Start date must use YYYY-MM-DD format.") from exc
    if parsed < date.today():
        raise PastStartDateError("Start date cannot be in the past.")


def _time_to_minutes(value: str) -> int:
    hour, minute = value.split(":", maxsplit=1)
    return int(hour) * 60 + int(minute)
