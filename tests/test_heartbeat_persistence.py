import json
import shutil

from scripts.scheduling.heartbeat import SchedulerHeartbeat


def test_heartbeat_is_compact_and_status_is_written_separately(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)
    heartbeat.set_state("running", "Scheduler is running.", schedule={"hash": "a"})

    payload = json.loads(heartbeat.path.read_text())
    status = json.loads(heartbeat.status_path.read_text())

    assert set(payload) == {"version", "timestamp", "state", "message"}
    assert payload["version"] == 2
    assert heartbeat.path.stat().st_size < 512
    assert status["schedule"] == {"hash": "a"}


def test_unchanged_heartbeat_does_not_replace_status(tmp_path):
    heartbeat = SchedulerHeartbeat(tmp_path)
    heartbeat.write()
    first_mtime = heartbeat.status_path.stat().st_mtime_ns

    heartbeat.write()

    assert heartbeat.status_path.stat().st_mtime_ns == first_mtime


def test_capture_status_change_replaces_detailed_status(tmp_path):
    current = {"summary": {"succeeded": 0}}
    heartbeat = SchedulerHeartbeat(tmp_path)
    heartbeat.set_capture_status_provider(lambda: current)
    heartbeat.write()
    first_mtime = heartbeat.status_path.stat().st_mtime_ns

    current["summary"]["succeeded"] = 1
    heartbeat.write()

    assert heartbeat.status_path.stat().st_mtime_ns > first_mtime
    status = json.loads(heartbeat.status_path.read_text())
    assert status["capture_summary"] == {"succeeded": 1}


def test_legacy_heartbeat_seeds_split_status(tmp_path):
    legacy = {
        "version": 1,
        "schedule": {"hash": "legacy"},
        "last_capture": {"schedule_hash": "legacy", "status": "succeeded"},
        "storage": {"free_bytes": 100},
    }
    (tmp_path / "scheduler-heartbeat.json").write_text(json.dumps(legacy))

    heartbeat = SchedulerHeartbeat(tmp_path)
    heartbeat.write()
    status = json.loads(heartbeat.status_path.read_text())

    assert status["schedule"] == legacy["schedule"]
    assert status["last_capture"] == legacy["last_capture"]


def test_storage_is_not_sampled_on_every_heartbeat(tmp_path, monkeypatch):
    calls = []
    usage = shutil._ntuple_diskusage(1000, 600, 400)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: calls.append(path) or usage,
    )
    heartbeat = SchedulerHeartbeat(tmp_path, storage_path=tmp_path / "captures")

    heartbeat.write()
    heartbeat.write()

    assert len(calls) == 1
