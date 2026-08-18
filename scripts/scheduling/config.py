from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from phenara.config import SETTINGS


@dataclass(frozen=True)
class SchedulerConfig:
    schedule_path: Path
    capture_script: Path
    python_bin: Path
    output_dir: Path
    runtime_dir: Path
    misfire_grace: timedelta
    reload_interval: timedelta
    tz: ZoneInfo


def default_scheduler_config() -> SchedulerConfig:
    return SchedulerConfig(
        schedule_path=SETTINGS.schedule_path,
        capture_script=SETTINGS.capture_script,
        python_bin=SETTINGS.python_bin,
        output_dir=SETTINGS.capture_dir,
        runtime_dir=SETTINGS.runtime_dir,
        misfire_grace=timedelta(minutes=10),
        reload_interval=timedelta(seconds=30),
        tz=SETTINGS.timezone,
    )
