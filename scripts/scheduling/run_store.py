from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from threading import Lock, Thread
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .make_schedule import atomic_write_text
from .schedule import RunMetadata, Schedule


RUN_MANIFEST_VERSION = 1
CAPTURE_EVENT_VERSION = 1
_SAFE_NAME = re.compile(r"[^a-z0-9]+")
DELETED_RUNS_DIRECTORY = ".phenopi-deleted-runs"


def validate_run_metadata(value: Any) -> dict[str, Any] | None:
    """Validate optional run metadata while retaining legacy compatibility."""
    if value is None:
        return None
    if isinstance(value, RunMetadata):
        return value.to_dict()
    if not isinstance(value, dict):
        raise ValueError("run must be an object")
    return RunMetadata.from_dict(value).to_dict()


def run_directory_name(start_date: str, run: dict[str, Any]) -> str:
    slug = _SAFE_NAME.sub("-", run["name"].lower()).strip("-") or "experiment"
    return f"{start_date}_{slug[:48]}_{run['id'].replace('-', '')[:8]}"


def deleted_run_marker(output_root: Path, run_id: str) -> Path:
    """Return the private tombstone that prevents recreation after deletion."""
    return output_root / DELETED_RUNS_DIRECTORY / f"{run_id}.json"


class RunArchive:
    """Portable run manifest and append-only capture outcome ledger."""

    def __init__(
        self,
        output_root: Path,
        schedule: dict[str, Any] | Schedule,
        schedule_hash: str,
        expected_times: list[datetime],
    ) -> None:
        schedule_data = schedule.to_dict() if isinstance(schedule, Schedule) else schedule
        run = validate_run_metadata(schedule_data.get("run"))
        if run is None:
            raise ValueError("A run archive requires run metadata.")
        self.run = run
        self.schedule = (
            schedule if isinstance(schedule, Schedule) else Schedule.from_dict(schedule_data)
        )
        self.schedule_hash = schedule_hash
        self.expected_times = expected_times
        self.directory = output_root / run_directory_name(schedule_data["start_date"], run)
        self.manifest_path = self.directory / "run.json"
        self.events_path = self.directory / "capture-events.jsonl"
        self.analysis_dir = self.directory / "analysis"
        self.archive_path = self.directory.with_suffix(".zip")
        self._lock = Lock()
        self._archive_lock = Lock()
        self._archive_thread: Thread | None = None
        self._state = "active"
        self._initialize(schedule_data)

    def _initialize(self, schedule: dict[str, Any]) -> None:
        if deleted_run_marker(self.directory.parent, self.run["id"]).is_file():
            self._state = "deleted"
            return
        existing_path = self._find_existing_manifest(self.directory.parent)
        if existing_path is not None and existing_path != self.manifest_path:
            raise ValueError("This run ID is already used by another dataset directory.")
        if self.manifest_path.exists():
            manifest = self._read_manifest()
            if (manifest.get("run") or {}).get("id") != self.run["id"]:
                raise ValueError("The dataset directory belongs to another run.")
            if manifest.get("schedule_hash") != self.schedule_hash:
                raise ValueError("This run ID is already associated with another schedule.")
            self._state = manifest.get("state", "active")
            self._write_analysis_profile()
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._write_analysis_profile()
        manifest = {
            "version": RUN_MANIFEST_VERSION,
            "run": self.run,
            "schedule_hash": self.schedule_hash,
            "schedule": schedule,
            "dataset_directory": str(self.directory),
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "state": "active",
            "ended_at": None,
            "superseded_by": None,
        }
        atomic_write_text(self.manifest_path, json.dumps(manifest, indent=2) + "\n")

    def _write_analysis_profile(self) -> None:
        if self.schedule.analysis is None:
            return
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.schedule.analysis.config.save(
            self.analysis_dir / "analysis-config.json"
        )
        self.schedule.analysis.roi.save(
            self.analysis_dir / "roi-definition.json"
        )

    def _find_existing_manifest(self, output_root: Path) -> Path | None:
        for path in output_root.glob("*/run.json") if output_root.exists() else []:
            try:
                manifest = json.loads(path.read_text())
            except (OSError, ValueError, TypeError):
                continue
            if (manifest.get("run") or {}).get("id") == self.run["id"]:
                return path
        return None

    def _read_manifest(self) -> dict[str, Any]:
        try:
            manifest = json.loads(self.manifest_path.read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("The run manifest could not be read.") from exc
        if manifest.get("version") != RUN_MANIFEST_VERSION:
            raise ValueError("The run manifest version is unsupported.")
        return manifest

    def mark_ended(self, state: str, *, superseded_by: str | None = None) -> None:
        if state not in {"completed", "superseded", "cancelled"}:
            raise ValueError("Unsupported terminal run state.")
        with self._lock:
            if self._state == "deleted" or (
                not self.manifest_path.exists()
                and deleted_run_marker(
                    self.directory.parent,
                    self.run["id"],
                ).is_file()
            ):
                self._state = "deleted"
                return
            if state == "completed" and not self.manifest_path.exists():
                # Older GUI versions removed the entire completed dataset.
                # Nothing remains to finalize, and this must not block loading
                # the operator's next schedule.
                self._state = "deleted"
                return
            manifest = self._read_manifest()
            if manifest.get("state") in {
                "completed",
                "superseded",
                "cancelled",
                "deleted",
            }:
                self._state = manifest["state"]
                if manifest.get("state") == "completed":
                    self._start_download_archive()
                return
            manifest["state"] = state
            manifest["ended_at"] = datetime.now(timezone.utc).isoformat()
            manifest["superseded_by"] = superseded_by if state == "superseded" else None
            atomic_write_text(
                self.manifest_path,
                json.dumps(manifest, indent=2) + "\n",
            )
            self._state = state
            if state == "completed":
                self._start_download_archive()

    def _start_download_archive(self) -> None:
        if self.archive_path.exists():
            return
        with self._archive_lock:
            if self._archive_thread is not None and self._archive_thread.is_alive():
                return
            self._archive_thread = Thread(
                target=self._create_download_archive_safely,
                name=f"archive-{self.run['id'][:8]}",
                daemon=True,
            )
            self._archive_thread.start()

    def _create_download_archive_safely(self) -> None:
        try:
            self._create_download_archive()
        except (OSError, ValueError) as exc:
            print(
                f"[scheduler] Could not create experiment archive: {exc}",
                file=sys.stderr,
            )

    def _create_download_archive(self) -> Path:
        """Create an atomic, portable ZIP after all run files are final."""
        if self.archive_path.exists():
            return self.archive_path
        temporary_path = self.archive_path.with_name(
            f".{self.archive_path.name}.{os.getpid()}.tmp"
        )
        try:
            with ZipFile(
                temporary_path,
                mode="w",
                compression=ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for path in sorted(self.directory.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(
                            "The run dataset contains a symbolic link and cannot be archived."
                        )
                    if path.is_file():
                        archive.write(
                            path,
                            Path(self.directory.name) / path.relative_to(self.directory),
                        )
            temporary_path.replace(self.archive_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return self.archive_path

    def record(
        self,
        *,
        scheduled_at: datetime,
        status: str,
        message: str,
        image_path: Path | None = None,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "missed"}:
            raise ValueError("Unsupported capture result status.")
        event = {
            "version": CAPTURE_EVENT_VERSION,
            "run_id": self.run["id"],
            "schedule_hash": self.schedule_hash,
            "capture_id": scheduled_at.isoformat(),
            "scheduled_at": scheduled_at.isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "message": message,
        }
        if image_path is not None:
            try:
                event["image_path"] = str(
                    image_path.resolve().relative_to(self.directory.resolve())
                )
            except ValueError as exc:
                raise ValueError(
                    "Capture image must be inside the run directory."
                ) from exc
        line = json.dumps(event, separators=(",", ":")) + "\n"
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
        return event

    def capture_path(self, scheduled_at: datetime) -> Path:
        """Return the deterministic image path for one scheduled capture."""
        return self.directory / (
            f"capture_{scheduled_at.strftime('%Y%m%d_%H%M%S')}.jpg"
        )

    def events(self) -> list[dict[str, Any]]:
        try:
            contents = self.events_path.read_text()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValueError("The capture ledger could not be read.") from exc
        events = []
        lines = contents.splitlines(keepends=True)
        for index, line in enumerate(lines):
            try:
                event = json.loads(line)
                if event.get("version") != CAPTURE_EVENT_VERSION:
                    raise ValueError("unsupported event")
            except (ValueError, TypeError):
                if index == len(lines) - 1 and not line.endswith("\n"):
                    break
                raise ValueError("The capture ledger contains an invalid event.")
            events.append(event)
        return events

    def latest_events(self) -> dict[str, dict[str, Any]]:
        return {event["capture_id"]: event for event in self.events()}

    def record_unreported_past(
        self,
        now: datetime,
        *,
        cutoff: datetime | None = None,
    ) -> None:
        """Record captures too old to be recovered by the scheduler."""
        if self._state == "deleted":
            return
        recorded = self.latest_events()
        missed_before = cutoff or now
        for scheduled_at in self.expected_times:
            capture_id = scheduled_at.isoformat()
            if scheduled_at < missed_before and capture_id not in recorded:
                self.record(
                    scheduled_at=scheduled_at,
                    status="missed",
                    message="The schedule was loaded after this capture time.",
                )

    def status_payload(self, now: datetime) -> dict[str, Any]:
        latest = self.latest_events()
        events = list(latest.values())
        counts = {status: 0 for status in ("succeeded", "failed", "missed")}
        for event in events:
            counts[event["status"]] += 1
        expected_ids = {value.isoformat() for value in self.expected_times}
        remaining = sum(value >= now for value in self.expected_times)
        elapsed_unreported = sum(
            value < now and value.isoformat() not in latest
            for value in self.expected_times
        )
        recent = sorted(
            (event for event in events if event["capture_id"] in expected_ids),
            key=lambda event: event["recorded_at"],
            reverse=True,
        )[:5]
        return {
            "summary": {
                "total": len(self.expected_times),
                **counts,
                "remaining": remaining,
                "elapsed_unreported": elapsed_unreported,
            },
            "recent": recent,
            "last": recent[0] if recent else None,
            "daily_progress": self._daily_progress(now, latest),
        }

    def _daily_progress(
        self,
        now: datetime,
        latest: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.expected_times:
            return None
        grouped = [
            self.expected_times[index:index + self.schedule.replicates]
            for index in range(0, len(self.expected_times), self.schedule.replicates)
        ]
        available_dates = sorted({group[0].date() for group in grouped})
        today = now.date()
        focus_date = (
            today
            if today in available_dates
            else next((value for value in available_dates if value > today), available_dates[-1])
        )
        points = []
        for group in (value for value in grouped if value[0].date() == focus_date):
            statuses = []
            messages = []
            captures = []
            for replicate_index, scheduled_at in enumerate(group):
                event = latest.get(scheduled_at.isoformat())
                if event is not None:
                    capture_status = event["status"]
                    statuses.append(capture_status)
                    if event["status"] != "succeeded" and event.get("message"):
                        messages.append(event["message"])
                else:
                    capture_status = "pending" if scheduled_at < now else "remaining"
                    statuses.append(capture_status)
                captures.append({
                    "scheduled_at": scheduled_at.isoformat(),
                    "time": scheduled_at.strftime("%H:%M:%S"),
                    "replicate": replicate_index + 1,
                    "status": capture_status,
                    "message": event.get("message") if event is not None else None,
                    "image_available": bool(
                        event is not None
                        and event.get("status") == "succeeded"
                        and event.get("image_path")
                    ),
                })
            counts = {
                status: statuses.count(status)
                for status in ("succeeded", "failed", "missed", "pending", "remaining")
            }
            if counts["failed"]:
                status = "failed"
            elif counts["missed"]:
                status = "missed"
            elif counts["pending"] or (counts["succeeded"] and counts["remaining"]):
                status = "pending"
            elif counts["succeeded"] == len(statuses):
                status = "succeeded"
            else:
                status = "remaining"
            points.append({
                "time": group[0].strftime("%H:%M"),
                "scheduled_at": group[0].isoformat(),
                "status": status,
                "counts": counts,
                "message": messages[0] if messages else None,
                "captures": captures,
            })
        return {
            "date": focus_date.isoformat(),
            "is_today": focus_date == today,
            "points": points,
        }
