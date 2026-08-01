from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any
from uuid import UUID

from scripts.scheduling.run_store import deleted_run_marker, run_directory_name
from scripts.scheduling.make_schedule import atomic_write_text


class ExperimentExportError(ValueError):
    """A finished experiment cannot safely be exported or removed."""


def validate_finished_experiment(
    status: dict[str, Any],
    run_id: UUID,
) -> dict[str, Any]:
    schedule = status.get("schedule")
    run = (schedule or {}).get("run")
    if (
        not schedule
        or schedule.get("lifecycle") != "finished"
        or not run
        or run.get("id") != str(run_id)
    ):
        raise ExperimentExportError(
            "This finished experiment is no longer available."
        )
    return schedule


def experiment_paths(
    output_root: Path,
    schedule: dict[str, Any],
) -> tuple[Path, Path]:
    root = output_root.resolve()
    directory = output_root / run_directory_name(
        schedule["start_date"],
        schedule["run"],
    )
    if directory.parent.resolve() != root or directory.is_symlink():
        raise ExperimentExportError("The experiment dataset path is unsafe.")
    return directory, directory.with_suffix(".zip")


def export_details(
    output_root: Path,
    schedule: dict[str, Any],
) -> dict[str, Any]:
    directory, archive = experiment_paths(output_root, schedule)
    manifest = _read_matching_manifest(directory, schedule)
    archive_ready = archive.is_file() and not archive.is_symlink()
    return {
        "run": schedule["run"],
        "schedule_hash": schedule["hash"],
        "start_date": schedule["start_date"],
        "end_date": schedule["end_date"],
        "capture_summary": None,
        "state": manifest["state"] if manifest else "deleted",
        "archive_ready": archive_ready,
        "archive_size_bytes": archive.stat().st_size if archive_ready else None,
        "data_present": (
            directory.is_dir()
            and manifest is not None
            and manifest.get("state") != "deleted"
        ),
    }


def download_path(output_root: Path, schedule: dict[str, Any]) -> Path:
    directory, archive = experiment_paths(output_root, schedule)
    manifest = _read_matching_manifest(directory, schedule)
    if manifest is None or manifest.get("state") != "completed":
        raise ExperimentExportError("The completed experiment data is unavailable.")
    if not archive.is_file() or archive.is_symlink():
        raise ExperimentExportError(
            "The experiment archive is not ready. Please try again shortly."
        )
    return archive


def capture_image_path(
    output_root: Path,
    schedule: dict[str, Any],
    scheduled_at: datetime,
) -> Path:
    """Resolve one successful capture without exposing arbitrary run files."""
    if scheduled_at.tzinfo is None:
        raise ExperimentExportError("The capture timestamp must include a timezone.")
    directory, _ = experiment_paths(output_root, schedule)
    manifest = _read_matching_manifest(directory, schedule)
    if manifest is None or manifest.get("state") == "deleted":
        raise ExperimentExportError("The experiment dataset is unavailable.")
    try:
        lines = (directory / "capture-events.jsonl").read_text().splitlines()
    except (FileNotFoundError, OSError) as exc:
        raise ExperimentExportError("The capture ledger is unavailable.") from exc

    matching = None
    for line in lines:
        try:
            event = json.loads(line)
            event_time = datetime.fromisoformat(str(event["capture_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if event_time == scheduled_at:
            matching = event
    relative = (matching or {}).get("image_path")
    if (matching or {}).get("status") != "succeeded":
        raise ExperimentExportError("No image is available for this capture.")

    # Older ledgers did not always persist image_path. Capture names are derived
    # from the scheduled timestamp, so the archive can still resolve them safely.
    if relative is None:
        image = directory / f"capture_{scheduled_at.strftime('%Y%m%d_%H%M%S')}.jpg"
    elif not isinstance(relative, str):
        raise ExperimentExportError("No image is available for this capture.")
    else:
        image = directory / relative
    try:
        image.resolve().relative_to(directory.resolve())
    except ValueError as exc:
        raise ExperimentExportError("The capture image path is unsafe.") from exc
    if image.is_symlink() or not image.is_file():
        raise ExperimentExportError("The capture image is unavailable.")
    return image


def delete_experiment_data(
    output_root: Path,
    schedule: dict[str, Any],
) -> None:
    directory, archive = experiment_paths(output_root, schedule)
    manifest = _read_matching_manifest(directory, schedule)
    if manifest is None or manifest.get("state") != "completed":
        raise ExperimentExportError("The completed experiment data is unavailable.")
    if archive.is_symlink():
        raise ExperimentExportError("The experiment archive path is unsafe.")
    marker = deleted_run_marker(output_root, schedule["run"]["id"])
    atomic_write_text(
        marker,
        json.dumps(
            {
                "run_id": schedule["run"]["id"],
                "schedule_hash": schedule["hash"],
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
    )
    archive.unlink(missing_ok=True)
    shutil.rmtree(directory)


def _read_matching_manifest(
    directory: Path,
    schedule: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        manifest = json.loads((directory / "run.json").read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise ExperimentExportError(
            "The experiment manifest could not be verified."
        ) from exc
    if (
        (manifest.get("run") or {}).get("id") != schedule["run"]["id"]
        or manifest.get("schedule_hash") != schedule["hash"]
    ):
        raise ExperimentExportError(
            "The experiment dataset does not match the finished schedule."
        )
    return manifest
