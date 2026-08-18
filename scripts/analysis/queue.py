from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any


ANALYSIS_EVENT_VERSION = 1
MAX_ANALYSIS_ATTEMPTS = 3


class AnalysisQueue:
    """Restart-safe append-only analysis outcome ledger."""

    def __init__(self, analysis_dir: Path) -> None:
        self.analysis_dir = analysis_dir
        self.events_path = analysis_dir / "analysis-events.jsonl"
        self._lock = Lock()

    def record(
        self,
        *,
        capture_id: str,
        image_path: str,
        status: str,
        message: str,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        if status not in {"running", "succeeded", "failed"}:
            raise ValueError("Unsupported analysis status.")
        event = {
            "version": ANALYSIS_EVENT_VERSION,
            "capture_id": capture_id,
            "image_path": image_path,
            "status": status,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
        }
        if duration_seconds is not None:
            event["duration_seconds"] = round(duration_seconds, 3)
        line = json.dumps(event, separators=(",", ":")) + "\n"
        with self._lock:
            self.analysis_dir.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
        return event

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines(
                keepends=True
            )
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValueError("The analysis ledger could not be read.") from exc
        events = []
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
                if event.get("version") != ANALYSIS_EVENT_VERSION:
                    raise ValueError("unsupported event")
            except (json.JSONDecodeError, TypeError, ValueError):
                if index == len(lines) - 1 and not line.endswith("\n"):
                    break
                raise ValueError("The analysis ledger contains an invalid event.")
            events.append(event)
        return events

    def pending(self, capture_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events = self.events()
        latest = {event["capture_id"]: event for event in events}
        attempts: dict[str, int] = {}
        for event in events:
            if event["status"] == "running":
                attempts[event["capture_id"]] = (
                    attempts.get(event["capture_id"], 0) + 1
                )
        captures = {
            event["capture_id"]: event
            for event in capture_events
            if event["status"] == "succeeded" and event.get("image_path")
        }
        return [
            capture
            for capture_id, capture in sorted(
                captures.items(), key=lambda item: item[1]["scheduled_at"]
            )
            if latest.get(capture_id, {}).get("status") != "succeeded"
            and attempts.get(capture_id, 0) < MAX_ANALYSIS_ATTEMPTS
        ]

    def summary(self, capture_events: list[dict[str, Any]]) -> dict[str, int]:
        events = self.events()
        latest = {event["capture_id"]: event for event in events}
        attempts: dict[str, int] = {}
        for event in events:
            if event["status"] == "running":
                attempts[event["capture_id"]] = (
                    attempts.get(event["capture_id"], 0) + 1
                )
        eligible = {
            event["capture_id"]
            for event in capture_events
            if event["status"] == "succeeded" and event.get("image_path")
        }
        return {
            "total": len(eligible),
            "succeeded": sum(
                latest.get(capture_id, {}).get("status") == "succeeded"
                for capture_id in eligible
            ),
            "failed": sum(
                latest.get(capture_id, {}).get("status") == "failed"
                and attempts.get(capture_id, 0) >= MAX_ANALYSIS_ATTEMPTS
                for capture_id in eligible
            ),
            "running": sum(
                latest.get(capture_id, {}).get("status") == "running"
                for capture_id in eligible
            ),
            "pending": len(self.pending(capture_events)),
        }
