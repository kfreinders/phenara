from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from collections.abc import Callable


HEARTBEAT_FILENAME = "scheduler-heartbeat.json"
STATUS_FILENAME = "scheduler-status.json"
HEARTBEAT_INTERVAL_SECONDS = 10
STORAGE_REFRESH_INTERVAL = timedelta(minutes=5)
HEARTBEAT_STATES = {
    "running",
    "waiting_for_schedule",
    "invalid_schedule",
}
_KEEP_SCHEDULE = object()


class SchedulerHeartbeat:
    """Write the scheduler's current state to an atomic JSON heartbeat."""

    def __init__(
        self,
        runtime_dir: Path,
        storage_path: Path | None = None,
    ) -> None:
        self.path = runtime_dir / HEARTBEAT_FILENAME
        self.status_path = runtime_dir / STATUS_FILENAME
        self.storage_path = storage_path
        self._state = "waiting_for_schedule"
        self._message = "The scheduler is waiting for a schedule file."
        previous = self._load_previous_status()
        self._schedule: dict | None = previous.get("schedule")
        self._last_capture = previous.get("last_capture")
        self._capture_details = {
            "capture_summary": previous.get("capture_summary"),
            "recent_captures": previous.get("recent_captures", []),
            "daily_capture_progress": previous.get("daily_capture_progress"),
            "analysis_summary": previous.get("analysis_summary"),
        }
        self._last_status_content: str | None = (
            json.dumps(previous, sort_keys=True, separators=(",", ":"))
            if previous.get("version") == 1
            else None
        )
        previous_core = {
            key: value for key, value in previous.items() if key != "storage"
        }
        self._last_status_core: str | None = (
            json.dumps(previous_core, sort_keys=True, separators=(",", ":"))
            if previous.get("version") == 1
            else None
        )
        self._storage = previous.get("storage")
        self._storage_checked_at: datetime | None = None
        self._capture_status_provider: Callable[[], dict] | None = None
        self._lock = Lock()

    def set_capture_status_provider(
        self,
        provider: Callable[[], dict] | None,
    ) -> None:
        with self._lock:
            self._capture_status_provider = provider

    def set_state(
        self,
        state: str,
        message: str,
        *,
        schedule: dict | None | object = _KEEP_SCHEDULE,
    ) -> bool:
        """Set the current state and immediately publish a heartbeat."""
        if state not in HEARTBEAT_STATES:
            raise ValueError(f"Unsupported scheduler heartbeat state: {state}")

        with self._lock:
            self._state = state
            self._message = message
            if schedule is not _KEEP_SCHEDULE:
                self._schedule = schedule
                if schedule is None:
                    self._last_capture = None
                    self._capture_details = {
                        "capture_summary": None,
                        "recent_captures": [],
                        "daily_capture_progress": None,
                        "analysis_summary": None,
                    }
                elif (
                    self._last_capture is not None
                    and self._last_capture.get("schedule_hash")
                    != schedule.get("hash")
                ):
                    self._last_capture = None
            return self._write_locked()

    def record_capture(self, result: dict) -> bool:
        """Publish the latest actual capture-job outcome."""
        with self._lock:
            self._last_capture = result
            return self._write_locked()

    def write(self) -> bool:
        """Refresh the heartbeat timestamp without changing its state."""
        with self._lock:
            return self._write_locked()

    def _write_locked(self) -> bool:
        now = datetime.now(timezone.utc)
        heartbeat = {
            "version": 2,
            "timestamp": now.isoformat(),
            "state": self._state,
            "message": self._message,
        }
        status = {
            "version": 1,
            "schedule": self._schedule,
            "last_capture": self._last_capture,
            **self._capture_details,
        }
        if self._capture_status_provider is not None:
            capture_status = self._capture_status_provider()
            self._capture_details = {
                "capture_summary": capture_status.get("summary"),
                "recent_captures": capture_status.get("recent", []),
                "daily_capture_progress": capture_status.get("daily_progress"),
                "analysis_summary": capture_status.get("analysis"),
            }
            status.update(self._capture_details)
            status["last_capture"] = capture_status.get("last")

        content_without_storage = json.dumps(
            status,
            sort_keys=True,
            separators=(",", ":"),
        )
        status_changed = content_without_storage != self._last_status_core
        storage_due = (
            self._storage_checked_at is None
            or now - self._storage_checked_at >= STORAGE_REFRESH_INTERVAL
        )
        if status_changed or storage_due:
            self._storage = self._storage_payload()
            self._storage_checked_at = now
        status["storage"] = self._storage
        status_content = json.dumps(status, sort_keys=True, separators=(",", ":"))

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"[scheduler] Could not prepare heartbeat directory: {exc}",
                file=sys.stderr,
            )
            return False
        status_written = True
        if status_content != self._last_status_content:
            try:
                self._atomic_write(self.status_path, status_content + "\n")
                self._last_status_content = status_content
                self._last_status_core = content_without_storage
            except OSError as exc:
                status_written = False
                print(
                    f"[scheduler] Could not write scheduler status: {exc}",
                    file=sys.stderr,
                )
        try:
            self._atomic_write(self.path, json.dumps(heartbeat) + "\n")
        except OSError as exc:
            print(
                f"[scheduler] Could not write heartbeat: {exc}",
                file=sys.stderr,
            )
            return False

        return status_written

    @staticmethod
    def _atomic_write(path: Path, contents: str) -> None:
        temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary_path.write_text(contents)
            temporary_path.replace(path)
        except OSError:
            temporary_path.unlink(missing_ok=True)
            raise

    def _load_previous_status(self) -> dict:
        """Load split status or seed it from the legacy combined heartbeat."""
        try:
            payload = json.loads(self.status_path.read_text())
            if payload.get("version") != 1:
                return {}
            return payload
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        try:
            payload = json.loads(self.path.read_text())
            if payload.get("version") != 1:
                return {}
            detail_fields = {
                "schedule",
                "last_capture",
                "storage",
                "capture_summary",
                "recent_captures",
                "daily_capture_progress",
                "analysis_summary",
            }
            return {
                "version": 1,
                **{
                    key: payload.get(key)
                    for key in detail_fields
                },
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _storage_payload(self) -> dict | None:
        if self.storage_path is None:
            return None
        path = self.storage_path
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            return None
        used = usage.total - usage.free
        return {
            "total_bytes": usage.total,
            "used_bytes": used,
            "free_bytes": usage.free,
            "used_percent": round(used / usage.total * 100, 1),
        }
