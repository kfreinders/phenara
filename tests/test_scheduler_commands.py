from types import SimpleNamespace

import pytest

from scripts.scheduling.commands import (
    clear_scheduler_command,
    read_schedule_cancellation,
    request_schedule_cancellation,
)
from scripts.scheduling import scheduler as scheduler_module


class FakeScheduler:
    def __init__(self):
        self.shutdown_calls = []

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


class FakeHeartbeat:
    def __init__(self):
        self.provider = "unchanged"
        self.states = []

    def set_capture_status_provider(self, provider):
        self.provider = provider

    def set_state(self, state, message, *, schedule=None):
        self.states.append((state, message, schedule))


def test_cancellation_request_round_trips_atomically(tmp_path):
    path = tmp_path / "scheduler-command.json"
    schedule_hash = "a" * 64

    request_schedule_cancellation(path, schedule_hash)
    request = read_schedule_cancellation(path)

    assert request.schedule_hash == schedule_hash
    assert request.requested_at.tzinfo is not None
    clear_scheduler_command(path)
    assert read_schedule_cancellation(path) is None


def test_cancellation_request_rejects_invalid_hash_or_payload(tmp_path):
    path = tmp_path / "scheduler-command.json"
    with pytest.raises(ValueError, match="hash"):
        request_schedule_cancellation(path, "not-a-hash")
    path.write_text("{}")
    with pytest.raises(ValueError, match="invalid"):
        read_schedule_cancellation(path)


def test_scheduler_accepts_only_matching_cancellation_request(tmp_path):
    schedule_hash = "b" * 64
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text("schedule")
    config = SimpleNamespace(runtime_dir=tmp_path, schedule_path=schedule_path)
    scheduler = FakeScheduler()
    heartbeat = FakeHeartbeat()
    archive = SimpleNamespace(states=[], mark_ended=lambda state: archive.states.append(state))
    request_schedule_cancellation(tmp_path / "scheduler-command.json", schedule_hash)

    scheduler_module.poll_scheduler_commands(
        scheduler,
        config,
        schedule_hash,
        heartbeat,
        archive,
        {"hash": schedule_hash, "run": {"id": "run-id"}},
    )

    assert scheduler.shutdown_calls == [False]
    assert archive.states == ["cancelled"]
    assert not schedule_path.exists()
    assert (tmp_path / f"cancelled-schedule-{schedule_hash[:12]}.json").exists()
    assert not (tmp_path / "scheduler-command.json").exists()
    assert heartbeat.provider is None
    assert heartbeat.states[-1][0] == "waiting_for_schedule"
    assert heartbeat.states[-1][2] == {
        "hash": schedule_hash,
        "run": {"id": "run-id"},
        "terminal_state": "cancelled",
    }


def test_scheduler_ignores_request_for_a_different_schedule(tmp_path):
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text("schedule")
    config = SimpleNamespace(runtime_dir=tmp_path, schedule_path=schedule_path)
    scheduler = FakeScheduler()
    request_schedule_cancellation(tmp_path / "scheduler-command.json", "a" * 64)

    scheduler_module.poll_scheduler_commands(scheduler, config, "b" * 64)

    assert scheduler.shutdown_calls == []
    assert schedule_path.exists()
    assert not (tmp_path / "scheduler-command.json").exists()


def test_failed_cancellation_archive_restores_the_active_schedule(tmp_path):
    schedule_hash = "c" * 64
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text("schedule")
    config = SimpleNamespace(runtime_dir=tmp_path, schedule_path=schedule_path)
    scheduler = FakeScheduler()
    archive = SimpleNamespace(
        mark_ended=lambda state: (_ for _ in ()).throw(OSError("archive failed"))
    )
    command_path = tmp_path / "scheduler-command.json"
    request_schedule_cancellation(command_path, schedule_hash)

    with pytest.raises(OSError, match="archive failed"):
        scheduler_module.poll_scheduler_commands(
            scheduler, config, schedule_hash, run_archive=archive
        )

    assert schedule_path.read_text() == "schedule"
    assert command_path.exists()
    assert scheduler.shutdown_calls == []
