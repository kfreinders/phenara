from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from phenopi.config import (
    DEVELOPMENT_IMAGE_DIR,
    DEVELOPMENT_MODE_PATH,
    RUNTIME_DIR,
)
from phenopi.development import (
    DEVELOPMENT_MARKER_NAME,
    calibration_image,
    read_development_mode,
    sequence_images,
)


DEFAULT_SIZE = (4608, 2592)
DEFAULT_WARMUP_SECONDS = 10.0


def capture_image(
    destination: Path,
    *,
    size: tuple[int, int] = DEFAULT_SIZE,
    warmup_time: float = DEFAULT_WARMUP_SECONDS,
) -> None:
    """Capture one Raspberry Pi still directly to a temporary JPEG."""
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError(
            "Picamera2 is not installed; install python3-picamera2 on the Raspberry Pi."
        ) from exc

    camera = Picamera2(0)
    started = False
    try:
        configuration = camera.create_still_configuration(
            main={"size": size}
        )
        camera.configure(configuration)
        camera.start()
        started = True
        time.sleep(warmup_time)
        camera.capture_file(str(destination), format="jpeg")
    finally:
        try:
            if started:
                camera.stop()
        finally:
            camera.close()


def capture_once(
    *,
    output_dir: Path | None = None,
    output_path: Path | None = None,
    captured_at: datetime | None = None,
    warmup_time: float = DEFAULT_WARMUP_SECONDS,
    calibration_preview: bool = False,
    development_mode_path: Path = DEVELOPMENT_MODE_PATH,
    development_image_dir: Path = DEVELOPMENT_IMAGE_DIR,
    runtime_dir: Path = RUNTIME_DIR,
) -> Path:
    """Produce one real or simulated JPEG using the production filename."""
    if output_dir is None and output_path is None:
        raise ValueError("An output directory or output path is required.")
    timestamp = (captured_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
    destination = (
        output_path
        if output_path is not None
        else output_dir / f"capture_{timestamp}.jpg"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    with camera_lock(runtime_dir / "camera.lock"):
        temporary = _temporary_jpeg(destination)
        try:
            if read_development_mode(development_mode_path):
                _write_development_capture(
                    temporary,
                    destination=destination,
                    image_dir=development_image_dir,
                    calibration_preview=calibration_preview,
                )
            else:
                capture_image(temporary, warmup_time=warmup_time)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("Capture did not produce a non-empty JPEG.")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def _write_development_capture(
    temporary: Path,
    *,
    destination: Path,
    image_dir: Path,
    calibration_preview: bool,
) -> None:
    if calibration_preview:
        source = calibration_image(image_dir)
    else:
        images = sequence_images(image_dir)
        completed = len(
            [
                path
                for path in destination.parent.glob("capture_*.jpg")
                if path.is_file() and path != destination
            ]
        )
        if completed >= len(images):
            raise RuntimeError(
                "Development capture sequence is exhausted "
                f"({len(images)} sample images)."
            )
        source = images[completed]
        marker = destination.parent / DEVELOPMENT_MARKER_NAME
        if not marker.exists():
            marker.write_text(
                "This dataset was generated in Phenopi development mode.\n"
                "Capture images were copied from the configured sample-image directory.\n"
            )
    shutil.copyfile(source, temporary)


def _temporary_jpeg(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=".jpg",
        dir=destination.parent,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


@contextmanager
def camera_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture one Phenopi image."
    )
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir", type=Path)
    destination.add_argument("--output-path", type=Path)
    parser.add_argument("--warmup-time", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument(
        "--calibration-preview",
        action="store_true",
        help="Use the reserved development calibration image when simulating.",
    )
    args = parser.parse_args()
    result = capture_once(
        output_dir=args.output_dir,
        output_path=args.output_path,
        warmup_time=args.warmup_time,
        calibration_preview=args.calibration_preview,
    )
    print(f"[capture] Saved image to {result}")


if __name__ == "__main__":
    main()
