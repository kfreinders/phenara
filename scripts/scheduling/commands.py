from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .make_schedule import atomic_write_text


SCHEDULER_COMMAND_FILENAME = "scheduler-command.json"
COMMAND_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CancelScheduleRequest:
    schedule_hash: str
    requested_at: datetime

    def to_dict(self) -> dict[str, str | int]:
        return {
            "version": COMMAND_VERSION,
            "command": "cancel_schedule",
            "schedule_hash": self.schedule_hash,
            "requested_at": self.requested_at.isoformat(),
        }


def request_schedule_cancellation(path: Path, schedule_hash: str) -> None:
    if not _HASH_PATTERN.fullmatch(schedule_hash):
        raise ValueError("A valid active schedule hash is required.")
    request = CancelScheduleRequest(
        schedule_hash=schedule_hash,
        requested_at=datetime.now(timezone.utc),
    )
    atomic_write_text(path, json.dumps(request.to_dict(), indent=2) + "\n")


def read_schedule_cancellation(path: Path) -> CancelScheduleRequest | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        requested_at = datetime.fromisoformat(str(payload["requested_at"]))
        schedule_hash = str(payload["schedule_hash"])
        if (
            payload.get("version") != COMMAND_VERSION
            or payload.get("command") != "cancel_schedule"
            or requested_at.tzinfo is None
            or not _HASH_PATTERN.fullmatch(schedule_hash)
        ):
            raise ValueError("invalid scheduler command")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("The scheduler cancellation request is invalid.") from exc
    return CancelScheduleRequest(schedule_hash, requested_at)


def clear_scheduler_command(path: Path) -> None:
    path.unlink(missing_ok=True)
