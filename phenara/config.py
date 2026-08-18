from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping
from zoneinfo import ZoneInfo


SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _path(
    environment: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    value = environment.get(name)
    return (
        Path(value).expanduser().resolve()
        if value
        else default.expanduser().resolve()
    )


def _executable_path(value: str | Path) -> Path:
    """Make an interpreter path absolute without dereferencing a venv symlink."""
    return Path(os.path.abspath(Path(value).expanduser()))


def _boolean(environment: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = environment.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean.")


@dataclass(frozen=True)
class PhenaraSettings:
    project_root: Path
    runtime_dir: Path
    capture_dir: Path
    venv_dir: Path
    python_bin: Path
    schedule_path: Path
    schedule_draft_path: Path
    scheduler_heartbeat_path: Path
    scheduler_command_path: Path
    capture_script: Path
    development_image_dir: Path
    development_mode_path: Path
    development_available: bool
    camera_preview_path: Path
    timezone: ZoneInfo
    gui_host: str
    gui_port: int


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> PhenaraSettings:
    """Load all installation paths from one environment-driven source."""
    env = environment if environment is not None else os.environ
    project_root = _path(env, "PHENARA_ROOT", SOURCE_ROOT)
    runtime_dir = _path(
        env,
        "PHENARA_RUNTIME_DIR",
        project_root / "runtime",
    )
    capture_dir = _path(
        env,
        "PHENARA_CAPTURE_DIR",
        project_root / "captures",
    )
    venv_dir = _path(
        env,
        "PHENARA_VENV_DIR",
        project_root / ".venv",
    )
    configured_python = env.get("PHENARA_PYTHON")
    python_bin = (
        _executable_path(configured_python)
        if configured_python
        else _executable_path(sys.executable)
    )
    timezone_name = env.get("PHENARA_TIMEZONE", "Europe/Amsterdam")
    try:
        timezone = ZoneInfo(timezone_name)
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"PHENARA_TIMEZONE is not a valid timezone: {timezone_name}"
        ) from exc
    try:
        gui_port = int(env.get("PHENARA_GUI_PORT", "8000"))
    except ValueError as exc:
        raise ValueError("PHENARA_GUI_PORT must be an integer.") from exc
    if not 1 <= gui_port <= 65535:
        raise ValueError("PHENARA_GUI_PORT must be between 1 and 65535.")

    return PhenaraSettings(
        project_root=project_root,
        runtime_dir=runtime_dir,
        capture_dir=capture_dir,
        venv_dir=venv_dir,
        python_bin=python_bin,
        schedule_path=runtime_dir / "schedule.json",
        schedule_draft_path=runtime_dir / "schedule-draft.json",
        scheduler_heartbeat_path=runtime_dir / "scheduler-heartbeat.json",
        scheduler_command_path=runtime_dir / "scheduler-command.json",
        capture_script=project_root / "scripts" / "capture" / "capture_once.py",
        development_image_dir=_path(
            env,
            "PHENARA_DEVELOPMENT_IMAGE_DIR",
            project_root / "development" / "sample-images",
        ),
        development_mode_path=runtime_dir / "development-mode.json",
        development_available=_boolean(
            env,
            "PHENARA_DEVELOPMENT_AVAILABLE",
        ),
        camera_preview_path=runtime_dir / "camera-preview.jpg",
        timezone=timezone,
        gui_host=env.get("PHENARA_GUI_HOST", "0.0.0.0"),
        gui_port=gui_port,
    )


SETTINGS = load_settings()

PROJECT_ROOT = SETTINGS.project_root
RUNTIME_DIR = SETTINGS.runtime_dir
CAPTURE_OUTPUT_ROOT = SETTINGS.capture_dir
VENV_DIR = SETTINGS.venv_dir
PYTHON_BIN = SETTINGS.python_bin
DEFAULT_SCHEDULE_PATH = SETTINGS.schedule_path
SCHEDULE_DRAFT_PATH = SETTINGS.schedule_draft_path
SCHEDULER_HEARTBEAT_PATH = SETTINGS.scheduler_heartbeat_path
SCHEDULER_COMMAND_PATH = SETTINGS.scheduler_command_path
CAPTURE_SCRIPT_PATH = SETTINGS.capture_script
DEVELOPMENT_IMAGE_DIR = SETTINGS.development_image_dir
DEVELOPMENT_MODE_PATH = SETTINGS.development_mode_path
DEVELOPMENT_AVAILABLE = SETTINGS.development_available
CAMERA_PREVIEW_PATH = SETTINGS.camera_preview_path
TIMEZONE = SETTINGS.timezone
GUI_HOST = SETTINGS.gui_host
GUI_PORT = SETTINGS.gui_port
