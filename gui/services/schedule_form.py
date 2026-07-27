from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class ScheduleFormData(BaseModel):
    """Typed representation of the schedule builder's submitted fields."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    experiment_name: str
    researcher: str | None = None
    notes: str | None = None
    analysis_enabled: bool = False
    start_date: str
    num_days: int
    replicates: int
    replicate_interval_seconds: int
    every_start: str = "08:00"
    every_end: str = "19:30"
    every_step_minutes: int = 30
    duration_start: str = "08:00"
    duration_minutes: int = 720
    duration_step_minutes: int = 30
    centered_center: str = "12:00"
    centered_before_minutes: int = 120
    centered_after_minutes: int = 120
    centered_step_minutes: int = 30

    def preview_arguments(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={
                "experiment_name",
                "researcher",
                "notes",
                "analysis_enabled",
            }
        )

    def form_arguments(self) -> dict[str, Any]:
        return self.model_dump()

    @field_validator("experiment_name")
    @classmethod
    def validate_experiment_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Experiment name is required.")
        if len(value) > 80:
            raise ValueError("Experiment name must be 80 characters or fewer.")
        return value

    @field_validator("researcher", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        limit = 80 if info.field_name == "researcher" else 1000
        if len(value) > limit:
            label = "Researcher" if info.field_name == "researcher" else "Notes"
            raise ValueError(f"{label} must be {limit} characters or fewer.")
        return value


def form_defaults() -> dict[str, Any]:
    return {
        "mode": "every",
        "experiment_name": "",
        "researcher": "",
        "notes": "",
        "analysis_enabled": False,
        "start_date": date.today().isoformat(),
        "num_days": 14,
        "replicates": 1,
        "replicate_interval_seconds": 0,
        "every_start": "08:00",
        "every_end": "19:30",
        "every_step_minutes": 30,
        "duration_start": "08:00",
        "duration_minutes": 720,
        "duration_step_minutes": 30,
        "centered_center": "12:00",
        "centered_before_minutes": 120,
        "centered_after_minutes": 120,
        "centered_step_minutes": 30,
    }
