from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_FILENAME = "experiment-registry.sqlite"
TERMINAL_EXPERIMENT_LIMIT = 200
TERMINAL_STATES = {"completed", "cancelled", "failed", "superseded"}


class ExperimentRegistry:
    """Compact operational index of current and historical experiments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    run_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    researcher TEXT,
                    notes TEXT,
                    schedule_hash TEXT NOT NULL,
                    schedule_json TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    loaded_at TEXT,
                    ended_at TEXT,
                    capture_summary_json TEXT,
                    analysis_summary_json TEXT,
                    dataset_name TEXT NOT NULL,
                    data_present INTEGER NOT NULL DEFAULT 1,
                    archive_ready INTEGER NOT NULL DEFAULT 0,
                    archive_name TEXT,
                    archive_size_bytes INTEGER,
                    archive_sha256 TEXT,
                    archive_created_at TEXT,
                    exported_at TEXT,
                    deleted_at TEXT,
                    superseded_by TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS experiments_terminal_order
                    ON experiments(ended_at, created_at);
                PRAGMA user_version = 1;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=5)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA busy_timeout=5000")
        database.execute("PRAGMA auto_vacuum=INCREMENTAL")
        return database

    def register(
        self,
        *,
        schedule: dict[str, Any],
        schedule_hash: str,
        dataset_name: str,
        state: str = "active",
        loaded_at: str | None = None,
        ended_at: str | None = None,
        superseded_by: str | None = None,
        data_present: bool = True,
    ) -> None:
        run = schedule["run"]
        start_date = str(schedule["start_date"])
        end_date = _end_date(schedule)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as database:
            database.execute(
                """
                INSERT INTO experiments (
                    run_id, name, researcher, notes, schedule_hash,
                    schedule_json, start_date, end_date, state, created_at,
                    loaded_at, ended_at, dataset_name, data_present,
                    superseded_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    name=excluded.name,
                    researcher=excluded.researcher,
                    notes=excluded.notes,
                    schedule_hash=excluded.schedule_hash,
                    schedule_json=excluded.schedule_json,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    state=excluded.state,
                    loaded_at=COALESCE(experiments.loaded_at, excluded.loaded_at),
                    ended_at=COALESCE(excluded.ended_at, experiments.ended_at),
                    dataset_name=excluded.dataset_name,
                    data_present=excluded.data_present,
                    superseded_by=excluded.superseded_by,
                    updated_at=excluded.updated_at
                """,
                (
                    run["id"], run["name"], run.get("researcher"),
                    run.get("notes"), schedule_hash,
                    json.dumps(schedule, sort_keys=True, separators=(",", ":")),
                    start_date, end_date, state, run["created_at"], loaded_at,
                    ended_at, dataset_name, int(data_present), superseded_by, now,
                ),
            )

    def update_terminal(
        self,
        run_id: str,
        *,
        state: str,
        ended_at: str,
        capture_summary: dict[str, Any],
        analysis_summary: dict[str, Any] | None = None,
        superseded_by: str | None = None,
    ) -> None:
        if state not in TERMINAL_STATES:
            raise ValueError("Unsupported terminal experiment state.")
        with self._connect() as database:
            database.execute(
                """
                UPDATE experiments SET state=?, ended_at=?,
                    capture_summary_json=?, analysis_summary_json=?,
                    superseded_by=?, updated_at=? WHERE run_id=?
                """,
                (
                    state, ended_at, json.dumps(capture_summary),
                    json.dumps(analysis_summary) if analysis_summary else None,
                    superseded_by, datetime.now(timezone.utc).isoformat(), run_id,
                ),
            )
        self.prune()

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as database:
            row = database.execute(
                "SELECT * FROM experiments WHERE run_id=?", (run_id,)
            ).fetchone()
        return _row_payload(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as database:
            rows = database.execute(
                """SELECT * FROM experiments
                   ORDER BY COALESCE(ended_at, created_at) DESC, created_at DESC"""
            ).fetchall()
        return [_row_payload(row) for row in rows]

    def retention(self) -> dict[str, Any]:
        rows = self.list()
        terminal = [row for row in rows if row["state"] in TERMINAL_STATES]
        blockers = [row for row in terminal if row["data_present"]]
        return {
            "retained_terminal_count": len(terminal),
            "terminal_limit": TERMINAL_EXPERIMENT_LIMIT,
            "overflow": max(0, len(terminal) - TERMINAL_EXPERIMENT_LIMIT),
            "raw_data_blockers": blockers,
            "can_activate": not blockers,
        }

    def mark_deleted(
        self,
        run_id: str,
        *,
        archive_name: str,
        archive_size_bytes: int,
        archive_sha256: str,
        exported_at: str,
        deleted_at: str,
    ) -> None:
        with self._connect() as database:
            database.execute(
                """UPDATE experiments SET data_present=0, archive_ready=0,
                   archive_name=?, archive_size_bytes=?, archive_sha256=?,
                   exported_at=?, deleted_at=?, updated_at=? WHERE run_id=?""",
                (
                    archive_name, archive_size_bytes, archive_sha256,
                    exported_at, deleted_at, deleted_at, run_id,
                ),
            )
        self.prune()

    def prune(self) -> None:
        with self._connect() as database:
            database.execute(
                """
                DELETE FROM experiments WHERE run_id IN (
                    SELECT run_id FROM experiments
                    WHERE state IN ('completed','cancelled','failed','superseded')
                      AND data_present=0
                    ORDER BY COALESCE(ended_at, created_at) DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (TERMINAL_EXPERIMENT_LIMIT,),
            )
            database.execute("PRAGMA incremental_vacuum(16)")

    def reconcile(self, output_root: Path) -> list[str]:
        warnings = []
        for manifest_path in sorted(output_root.glob("*/run.json")):
            try:
                manifest = json.loads(manifest_path.read_text())
                schedule = manifest["schedule"]
                self.register(
                    schedule=schedule,
                    schedule_hash=manifest["schedule_hash"],
                    dataset_name=manifest_path.parent.name,
                    state=manifest.get("state", "active"),
                    loaded_at=manifest.get("loaded_at"),
                    ended_at=manifest.get("ended_at"),
                    superseded_by=manifest.get("superseded_by"),
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                warnings.append(f"{manifest_path.parent.name}: {exc}")
        return warnings


def _end_date(schedule: dict[str, Any]) -> str:
    from datetime import date, timedelta

    start = date.fromisoformat(str(schedule["start_date"]))
    return (start + timedelta(days=int(schedule["num_days"]) - 1)).isoformat()


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["schedule"] = json.loads(payload.pop("schedule_json"))
    capture_summary = payload.pop("capture_summary_json")
    analysis_summary = payload.pop("analysis_summary_json")
    payload["capture_summary"] = (
        json.loads(capture_summary) if capture_summary else None
    )
    payload["analysis_summary"] = (
        json.loads(analysis_summary) if analysis_summary else None
    )
    payload["data_present"] = bool(payload["data_present"])
    payload["archive_ready"] = bool(payload["archive_ready"])
    return payload
