from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from phenara.development import write_development_mode
from scripts.capture import capture_once as capture_module


def development_paths(tmp_path):
    runtime = tmp_path / "runtime"
    samples = tmp_path / "development" / "sample-images"
    mode = runtime / "development-mode.json"
    samples.mkdir(parents=True)
    runtime.mkdir()
    write_development_mode(mode, True)
    return runtime, samples, mode


def test_production_capture_uses_camera_and_production_filename(
    tmp_path,
    monkeypatch,
):
    runtime = tmp_path / "runtime"
    mode = runtime / "development-mode.json"
    calls = []

    def fake_capture(destination, **options):
        calls.append((destination, options))
        destination.write_bytes(b"real-jpeg")

    monkeypatch.setattr(capture_module, "capture_image", fake_capture)
    result = capture_module.capture_once(
        output_dir=tmp_path / "captures",
        captured_at=datetime(2026, 7, 22, 15, 4, 9),
        development_mode_path=mode,
        development_image_dir=tmp_path / "unused",
        runtime_dir=runtime,
        warmup_time=2,
    )

    assert result.name == "capture_20260722_150409.jpg"
    assert result.read_bytes() == b"real-jpeg"
    assert len(calls) == 1
    assert calls[0][1]["warmup_time"] == 2
    assert not list(result.parent.glob(f".{result.stem}.*.jpg"))


def test_picamera_capture_is_configured_and_closed(tmp_path, monkeypatch):
    events = []

    class FakeCamera:
        def create_still_configuration(self, **options):
            events.append(("configure-request", options))
            return {"still": options}

        def configure(self, configuration):
            events.append(("configure", configuration))

        def start(self):
            events.append(("start",))

        def capture_file(self, destination, *, format):
            events.append(("capture", format))
            (tmp_path / "camera.jpg").write_bytes(b"ignored")
            # The real API writes to the supplied path.
            Path(destination).write_bytes(b"jpeg")

        def stop(self):
            events.append(("stop",))

        def close(self):
            events.append(("close",))

    monkeypatch.setitem(
        sys.modules,
        "picamera2",
        SimpleNamespace(Picamera2=lambda _index: FakeCamera()),
    )
    monkeypatch.setattr(capture_module.time, "sleep", lambda value: events.append(("sleep", value)))
    destination = tmp_path / "still.jpg"

    capture_module.capture_image(
        destination,
        size=(640, 480),
        warmup_time=1.5,
    )

    assert destination.read_bytes() == b"jpeg"
    assert ("configure-request", {"main": {"size": (640, 480)}}) in events
    assert events[-2:] == [("stop",), ("close",)]


def test_development_capture_uses_natural_order_and_marks_dataset(tmp_path):
    runtime, samples, mode = development_paths(tmp_path)
    (samples / "calibration.jpg").write_bytes(b"calibration")
    (samples / "capture-10.jpg").write_bytes(b"ten")
    (samples / "capture-2.jpg").write_bytes(b"two")
    output = tmp_path / "run"

    first = capture_module.capture_once(
        output_dir=output,
        captured_at=datetime(2026, 7, 22, 15, 4, 9),
        development_mode_path=mode,
        development_image_dir=samples,
        development_available=True,
        runtime_dir=runtime,
    )
    second = capture_module.capture_once(
        output_dir=output,
        captured_at=datetime(2026, 7, 22, 15, 5, 9),
        development_mode_path=mode,
        development_image_dir=samples,
        development_available=True,
        runtime_dir=runtime,
    )

    assert first.read_bytes() == b"two"
    assert second.read_bytes() == b"ten"
    assert (output / "DEVELOPMENT_DATA.txt").is_file()


def test_development_preview_uses_reserved_calibration_image(tmp_path):
    runtime, samples, mode = development_paths(tmp_path)
    (samples / "calibration.jpg").write_bytes(b"calibration")
    (samples / "capture-001.jpg").write_bytes(b"capture")

    result = capture_module.capture_once(
        output_path=tmp_path / "camera-preview.jpg",
        calibration_preview=True,
        development_mode_path=mode,
        development_image_dir=samples,
        development_available=True,
        runtime_dir=runtime,
    )

    assert result.read_bytes() == b"calibration"
    assert not (tmp_path / "DEVELOPMENT_DATA.txt").exists()


def test_development_capture_fails_when_sequence_is_exhausted(tmp_path):
    runtime, samples, mode = development_paths(tmp_path)
    (samples / "calibration.jpg").write_bytes(b"calibration")
    (samples / "capture-001.jpg").write_bytes(b"capture")
    output = tmp_path / "run"
    capture_module.capture_once(
        output_dir=output,
        development_mode_path=mode,
        development_image_dir=samples,
        development_available=True,
        runtime_dir=runtime,
    )

    with pytest.raises(RuntimeError, match="exhausted"):
        capture_module.capture_once(
            output_path=output / "capture_20990101_000001.jpg",
            development_mode_path=mode,
            development_image_dir=samples,
            development_available=True,
            runtime_dir=runtime,
        )


def test_unavailable_development_mode_ignores_stale_enabled_state(
    tmp_path,
    monkeypatch,
):
    runtime, samples, mode = development_paths(tmp_path)
    (samples / "calibration.jpg").write_bytes(b"calibration")
    (samples / "capture-001.jpg").write_bytes(b"sample")

    def fake_capture(destination, **_options):
        destination.write_bytes(b"real-camera")

    monkeypatch.setattr(capture_module, "capture_image", fake_capture)
    result = capture_module.capture_once(
        output_dir=tmp_path / "captures",
        development_mode_path=mode,
        development_image_dir=samples,
        development_available=False,
        runtime_dir=runtime,
    )

    assert result.read_bytes() == b"real-camera"
