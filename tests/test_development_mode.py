import json
from datetime import datetime, timezone

import pytest

from gui.services.development_mode import (
    development_status,
    set_development_mode,
)
from phenopi.development import (
    read_development_mode,
    sequence_images,
    validate_development_images,
)


def write_waiting_heartbeat(path):
    path.write_text(json.dumps({
        "version": 2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": "waiting_for_schedule",
        "message": "Waiting for schedule.",
    }))
    path.with_name("scheduler-status.json").write_text(json.dumps({
        "version": 1,
        "schedule": None,
    }))


def sample_directory(tmp_path):
    images = tmp_path / "samples"
    images.mkdir()
    (images / "calibration.jpg").write_bytes(b"calibration")
    (images / "image-10.jpg").write_bytes(b"ten")
    (images / "image-2.jpeg").write_bytes(b"two")
    return images


def test_sample_images_are_validated_and_naturally_sorted(tmp_path):
    images = sample_directory(tmp_path)

    assert validate_development_images(images)["sequence_images"] == 2
    assert [path.name for path in sequence_images(images)] == [
        "image-2.jpeg",
        "image-10.jpg",
    ]


def test_development_mode_can_only_change_while_idle(tmp_path):
    images = sample_directory(tmp_path)
    mode = tmp_path / "runtime" / "development-mode.json"
    draft = tmp_path / "runtime" / "schedule-draft.json"
    heartbeat = tmp_path / "runtime" / "heartbeat.json"
    heartbeat.parent.mkdir()
    write_waiting_heartbeat(heartbeat)

    enabled = set_development_mode(
        True,
        mode_path=mode,
        image_dir=images,
        draft_path=draft,
        heartbeat_path=heartbeat,
    )
    assert enabled["enabled"] is True
    assert read_development_mode(mode) is True

    draft.write_text("{}")
    blocked = development_status(
        mode_path=mode,
        image_dir=images,
        draft_path=draft,
        heartbeat_path=heartbeat,
    )
    assert blocked["can_toggle"] is False
    with pytest.raises(ValueError, match="draft"):
        set_development_mode(
            False,
            mode_path=mode,
            image_dir=images,
            draft_path=draft,
            heartbeat_path=heartbeat,
        )


def test_enabling_requires_calibration_and_capture_samples(tmp_path):
    images = tmp_path / "empty-samples"
    images.mkdir()
    heartbeat = tmp_path / "heartbeat.json"
    write_waiting_heartbeat(heartbeat)

    with pytest.raises(ValueError, match="calibration"):
        set_development_mode(
            True,
            mode_path=tmp_path / "mode.json",
            image_dir=images,
            draft_path=tmp_path / "draft.json",
            heartbeat_path=heartbeat,
        )


def test_mode_state_write_is_atomic_and_creates_parent(tmp_path):
    mode = tmp_path / "missing" / "development-mode.json"

    from phenopi.development import write_development_mode

    write_development_mode(mode, True)

    assert read_development_mode(mode) is True
    assert not [
        path
        for path in mode.parent.iterdir()
        if path.name.startswith(f".{mode.name}.")
    ]
