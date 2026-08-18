import argparse
import hashlib
import json
import subprocess
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from uuid import uuid4

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from scripts.scheduling.config import SchedulerConfig
from scripts.scheduling.schedule_validation import ScheduleValidationError
from scripts.scheduling import scheduler as scheduler_module


TZ = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def scheduler_config(tmp_path):
    return SchedulerConfig(
        schedule_path=tmp_path / "schedule.json",
        capture_script=tmp_path / "capture_once.py",
        python_bin=Path("/test/python"),
        output_dir=tmp_path / "captures",
        runtime_dir=tmp_path / "runtime",
        misfire_grace=timedelta(minutes=10),
        reload_interval=timedelta(seconds=30),
        tz=TZ,
    )


def write_schedule(path, **overrides):
    payload = {
        "start_date": "2026-07-18",
        "num_days": 1,
        "times": ["09:00"],
        "replicates": 1,
        "replicate_interval_seconds": 0,
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return payload


def test_schedule_hash_depends_on_file_contents(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_bytes(b"schedule contents")

    assert scheduler_module.schedule_content_hash(path) == hashlib.sha256(
        b"schedule contents"
    ).hexdigest()


def test_expand_schedule_orders_days_times_and_replicates():
    jobs = scheduler_module.expand_schedule(
        {
            "start_date": "2026-07-18",
            "num_days": 2,
            "times": ["10:00", "09:00", "09:00"],
            "replicates": 2,
            "replicate_interval_seconds": 10,
        },
        TZ,
    )

    assert [job.strftime("%Y-%m-%d %H:%M:%S%z") for job in jobs] == [
        "2026-07-18 09:00:00+0200",
        "2026-07-18 09:00:10+0200",
        "2026-07-18 10:00:00+0200",
        "2026-07-18 10:00:10+0200",
        "2026-07-19 09:00:00+0200",
        "2026-07-19 09:00:10+0200",
        "2026-07-19 10:00:00+0200",
        "2026-07-19 10:00:10+0200",
    ]


def test_expand_schedule_uses_replicate_defaults():
    jobs = scheduler_module.expand_schedule(
        {"start_date": "2026-07-18", "num_days": 1, "times": ["09:00"]},
        TZ,
    )

    assert jobs == [datetime(2026, 7, 18, 9, 0, tzinfo=TZ)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"num_days": 0},
        {"replicates": 0},
        {"replicate_interval_seconds": -1},
        {"num_days": 10**100},
        {"replicates": 10**100},
        {"replicate_interval_seconds": 10**100},
    ],
)
def test_expand_schedule_rejects_invalid_settings(overrides):
    config = {
        "start_date": "2026-07-18",
        "num_days": 1,
        "times": ["09:00"],
    }
    config.update(overrides)

    with pytest.raises(ValueError):
        scheduler_module.expand_schedule(config, TZ)


@pytest.mark.parametrize("interval", [60, 61])
def test_expand_schedule_rejects_replicates_at_or_after_next_capture(interval):
    with pytest.raises(ScheduleValidationError, match="finish before"):
        scheduler_module.expand_schedule(
            {
                "start_date": "2026-07-18",
                "num_days": 1,
                "times": ["09:00", "09:01"],
                "replicates": 2,
                "replicate_interval_seconds": interval,
            },
            TZ,
        )


def test_run_capture_invokes_configured_command(scheduler_config, monkeypatch):
    calls = []

    def fake_run(command, check):
        calls.append((command, check))

    monkeypatch.setattr(scheduler_module.subprocess, "run", fake_run)

    scheduler_module.run_capture(scheduler_config)

    assert calls == [
        (
            [
                "/test/python",
                str(scheduler_config.capture_script),
                "--output-dir",
                str(scheduler_config.output_dir),
            ],
            True,
        )
    ]


def test_run_capture_propagates_failure(scheduler_config, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "capture")

    monkeypatch.setattr(scheduler_module.subprocess, "run", fail)

    with pytest.raises(subprocess.CalledProcessError):
        scheduler_module.run_capture(scheduler_config)


@pytest.mark.parametrize(
    ("event_code", "expected"),
    [
        (scheduler_module.EVENT_JOB_EXECUTED, "succeeded"),
        (scheduler_module.EVENT_JOB_ERROR, "failed"),
        (scheduler_module.EVENT_JOB_MISSED, "missed"),
    ],
)
def test_capture_events_are_published(event_code, expected):
    results = []
    heartbeat = SimpleNamespace(record_capture=results.append)
    event = SimpleNamespace(
        job_id="capture_2026-07-18T09:00:00+02:00",
        code=event_code,
        exception=RuntimeError("camera error") if expected == "failed" else None,
        scheduled_run_time=datetime(2026, 7, 18, 9, 0, tzinfo=TZ),
    )

    scheduler_module.record_capture_event(event, heartbeat, "schedule-hash")

    assert results[0]["status"] == expected
    assert results[0]["schedule_hash"] == "schedule-hash"


def test_control_job_events_are_ignored():
    results = []
    heartbeat = SimpleNamespace(record_capture=results.append)
    event = SimpleNamespace(job_id="write_heartbeat")

    scheduler_module.record_capture_event(event, heartbeat, "schedule-hash")

    assert results == []


def test_make_scheduler_configures_persistent_and_control_stores(
    scheduler_config,
):
    jobstore_path = scheduler_config.runtime_dir / "jobs.sqlite"

    configured = scheduler_module.make_scheduler(
        scheduler_config,
        jobstore_path,
    )

    assert isinstance(configured._jobstores["default"], SQLAlchemyJobStore)
    assert isinstance(configured._jobstores["control"], MemoryJobStore)
    assert configured.timezone == TZ
    assert jobstore_path.parent.is_dir()


def test_jobstore_paths_and_stale_cleanup(tmp_path):
    current = scheduler_module.jobstore_path_for_schedule(
        tmp_path,
        "abcdef1234567890",
    )
    current.touch()
    stale = tmp_path / "apscheduler-old.sqlite"
    stale.touch()
    unrelated = tmp_path / "other.sqlite"
    unrelated.touch()

    deleted = scheduler_module.delete_stale_jobstores(tmp_path, current)

    assert current.name == "apscheduler-abcdef123456.sqlite"
    assert deleted == 1
    assert current.exists()
    assert not stale.exists()
    assert unrelated.exists()


class FakeHeartbeat:
    def __init__(self):
        self.states = []
        self.capture_status_provider = None

    def set_state(self, state, message, **kwargs):
        self.states.append((state, message, kwargs))
        return True

    def write(self):
        return True

    def set_capture_status_provider(self, provider):
        self.capture_status_provider = provider


def test_run_capture_can_use_an_isolated_run_directory(
    scheduler_config, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        scheduler_module.subprocess,
        "run",
        lambda command, check: calls.append((command, check)),
    )
    run_directory = tmp_path / "captures" / "run-one"

    scheduler_module.run_capture(scheduler_config, run_directory)

    assert calls[0][0][-1] == str(run_directory)


class FakeScheduler:
    def __init__(self):
        self.jobs = []
        self.shutdown_calls = []
        self.started = False
        self.listeners = []

    def add_job(self, function, **kwargs):
        self.jobs.append((function, kwargs))

    def add_listener(self, function, mask):
        self.listeners.append((function, mask))

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)

    def start(self):
        self.started = True


def test_poll_schedule_does_nothing_when_contents_are_unchanged(
    scheduler_config,
):
    write_schedule(scheduler_config.schedule_path)
    active_hash = scheduler_module.schedule_content_hash(
        scheduler_config.schedule_path
    )
    fake_scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()

    scheduler_module.poll_schedule_for_changes(
        fake_scheduler,
        scheduler_config,
        active_hash,
        heartbeat,
    )

    assert fake_scheduler.shutdown_calls == []
    assert heartbeat.states[-1][0] == "running"


def test_poll_schedule_keeps_running_for_invalid_update(scheduler_config):
    scheduler_config.schedule_path.write_text("not json")
    fake_scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()

    scheduler_module.poll_schedule_for_changes(
        fake_scheduler,
        scheduler_config,
        "different-hash",
        heartbeat,
    )

    assert fake_scheduler.shutdown_calls == []
    assert heartbeat.states[-1][0] == "invalid_schedule"


def test_poll_schedule_reloads_valid_update(scheduler_config):
    write_schedule(scheduler_config.schedule_path)
    fake_scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()

    scheduler_module.poll_schedule_for_changes(
        fake_scheduler,
        scheduler_config,
        "different-hash",
        heartbeat,
    )

    assert fake_scheduler.shutdown_calls == [False]
    assert heartbeat.states[-1][0] == "running"


@pytest.mark.parametrize(
    ("contents", "expected_message"),
    [
        ("", "schedule file is empty"),
        ("not json", "does not contain valid JSON"),
        ("{}", "missing required field 'start_date'"),
        (
            '{"start_date": null, "num_days": 1, "times": null}',
            "start_date must use YYYY-MM-DD format",
        ),
    ],
)
def test_malformed_schedule_is_reported_through_heartbeat(
    scheduler_config, contents, expected_message, capsys
):
    scheduler_config.schedule_path.write_text(contents)
    heartbeat = FakeHeartbeat()

    scheduler_started = scheduler_module.run_scheduler_until_reload(
        scheduler_config,
        heartbeat,
    )

    assert scheduler_started is False
    assert heartbeat.states[-1][0] == "invalid_schedule"
    assert expected_message in heartbeat.states[-1][1]
    assert expected_message in capsys.readouterr().out


def test_scheduler_setup_adds_control_and_future_capture_jobs(
    scheduler_config, monkeypatch
):
    tomorrow = date.today() + timedelta(days=1)
    write_schedule(
        scheduler_config.schedule_path,
        start_date=tomorrow.isoformat(),
        times=["09:00"],
        replicates=2,
        replicate_interval_seconds=10,
    )
    fake_scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()
    monkeypatch.setattr(
        scheduler_module,
        "make_scheduler",
        lambda config, path: fake_scheduler,
    )

    scheduler_module.run_scheduler_until_reload(scheduler_config, heartbeat)

    jobs_by_id = {kwargs["id"]: kwargs for _, kwargs in fake_scheduler.jobs}
    assert "poll_schedule" in jobs_by_id
    assert "poll_commands" in jobs_by_id
    assert jobs_by_id["poll_commands"]["seconds"] == 2
    assert "write_heartbeat" in jobs_by_id
    capture_jobs = [
        kwargs for _, kwargs in fake_scheduler.jobs
        if kwargs["id"].startswith("capture_")
    ]
    assert len(capture_jobs) == 2
    assert all(job["misfire_grace_time"] == 600 for job in capture_jobs)
    assert all(job["max_instances"] == 1 for job in capture_jobs)
    assert fake_scheduler.started is True
    assert len(fake_scheduler.listeners) == 1
    assert heartbeat.states[0][0] == "running"
    assert heartbeat.states[0][2]["schedule"]["times"] == ["09:00"]


def test_scheduler_keeps_jobs_inside_misfire_grace_and_drops_older_jobs(
    scheduler_config, monkeypatch
):
    fixed_now = datetime(2026, 7, 23, 12, 20, 30, tzinfo=TZ)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    write_schedule(
        scheduler_config.schedule_path,
        start_date=fixed_now.date().isoformat(),
        times=["12:10", "12:15", "12:25"],
    )
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        scheduler_module,
        "make_scheduler",
        lambda config, path: fake_scheduler,
    )

    scheduler_module.run_scheduler_until_reload(scheduler_config)

    capture_jobs = [
        kwargs
        for _, kwargs in fake_scheduler.jobs
        if kwargs["id"].startswith("capture_")
    ]
    assert [job["run_date"].strftime("%H:%M") for job in capture_jobs] == [
        "12:15",
        "12:25",
    ]
    assert all(job["misfire_grace_time"] == 600 for job in capture_jobs)


def test_named_run_uses_isolated_capture_directory_and_status_provider(
    scheduler_config, monkeypatch
):
    tomorrow = date.today() + timedelta(days=1)
    run = {
        "id": str(uuid4()),
        "name": "Tray A drought response",
        "researcher": None,
        "notes": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_schedule(
        scheduler_config.schedule_path,
        start_date=tomorrow.isoformat(),
        run=run,
    )
    fake_scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()
    monkeypatch.setattr(
        scheduler_module,
        "make_scheduler",
        lambda config, path: fake_scheduler,
    )

    scheduler_module.run_scheduler_until_reload(scheduler_config, heartbeat)

    capture_job = next(
        kwargs
        for _, kwargs in fake_scheduler.jobs
        if kwargs["id"].startswith("capture_")
    )
    run_directory = capture_job["args"][1]
    assert run_directory.parent == scheduler_config.output_dir
    assert run_directory.name.startswith(tomorrow.isoformat())
    assert (run_directory / "run.json").exists()
    assert heartbeat.capture_status_provider()["summary"]["total"] == 1
    assert heartbeat.states[0][2]["schedule"]["run"]["name"] == run["name"]


def test_config_from_args_uses_explicit_values(monkeypatch, scheduler_config):
    monkeypatch.setattr(
        scheduler_module,
        "default_scheduler_config",
        lambda: scheduler_config,
    )
    args = argparse.Namespace(
        schedule=Path("custom-schedule.json"),
        capture_script=Path("custom-capture.py"),
        python_bin=Path("custom-python"),
        output_dir=Path("custom-captures"),
        runtime_dir=Path("custom-runtime"),
        timezone="UTC",
        misfire_grace_seconds=12,
        reload_interval_seconds=3.5,
    )

    result = scheduler_module.config_from_args(args)

    assert result.schedule_path == Path("custom-schedule.json")
    assert result.misfire_grace == timedelta(seconds=12)
    assert result.reload_interval == timedelta(seconds=3.5)
    assert result.tz == ZoneInfo("UTC")
