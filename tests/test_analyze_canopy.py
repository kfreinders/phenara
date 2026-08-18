from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

# Keep orchestration tests independent of the optional PlantCV runtime.
plantcv_package = ModuleType("plantcv")
plantcv_package.plantcv = SimpleNamespace(
    outputs=SimpleNamespace(clear=lambda: None, observations={}),
    visualize=SimpleNamespace(colorspaces=lambda **_: None),
    params=SimpleNamespace(),
)
sys.modules.setdefault("plantcv", plantcv_package)

from scripts.analysis import analyze_canopy
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.roi import RoiCircle, RoiDefinition


def test_analyze_image_returns_identified_atomic_outputs(tmp_path, monkeypatch):
    image_path = tmp_path / "capture.jpg"
    image_path.touch()
    output_dir = tmp_path / "analysis"
    traits = pd.DataFrame([{"plant": "plant_1", "area": 42}])

    monkeypatch.setattr(analyze_canopy, "configure_plantcv", lambda *_: None)
    monkeypatch.setattr(analyze_canopy.pcv.outputs, "clear", lambda: None)
    monkeypatch.setattr(
        analyze_canopy,
        "load_and_rotate_image",
        lambda *_: np.zeros((2, 2, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        analyze_canopy.pcv.visualize, "colorspaces", lambda **_: None
    )
    monkeypatch.setattr(
        analyze_canopy, "segment_plants", lambda *_: np.zeros((2, 2))
    )
    monkeypatch.setattr(analyze_canopy, "analyze_shape", lambda *_: None)
    monkeypatch.setattr(
        analyze_canopy, "observations_to_dataframe", lambda: traits
    )
    monkeypatch.setattr(
        analyze_canopy, "add_metric_units", lambda frame, _cfg: frame
    )

    config = AnalysisConfig(roi_rows=1, roi_cols=1)
    roi = RoiDefinition(
        schema_version=1,
        rows=1,
        columns=1,
        source_width=2,
        source_height=2,
        config_fingerprint=config.fingerprint,
        circles=(RoiCircle(0, 0, 0.5, 0.5, 0.4),),
    )
    result = analyze_canopy.analyze_image(
        image_path, output_dir, config, roi
    )

    assert result.image_path == image_path
    assert result.traits_path == output_dir / "capture_traits.csv"
    assert result.overlay_path == output_dir / "capture_roi_overlay.png"
    assert result.config_fingerprint == config.fingerprint
    pd.testing.assert_frame_equal(result.traits, traits)
    assert result.overlay_path.stat().st_size > 0
    assert not list(output_dir.glob(".*"))


def test_analyze_image_rejects_missing_input(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        analyze_canopy.analyze_image(
            tmp_path / "missing.jpg",
            tmp_path / "analysis",
            AnalysisConfig(),
        )


def test_batch_calibrates_and_saves_roi_only_once(tmp_path, monkeypatch):
    images = [tmp_path / "one.jpg", tmp_path / "two.jpg"]
    for image in images:
        image.touch()
    output_dir = tmp_path / "analysis"
    config = AnalysisConfig(roi_rows=1, roi_cols=1)
    roi = RoiDefinition(
        schema_version=1,
        rows=1,
        columns=1,
        source_width=100,
        source_height=100,
        config_fingerprint=config.fingerprint,
        circles=(RoiCircle(0, 0, 0.5, 0.5, 0.4),),
    )
    monkeypatch.setattr(analyze_canopy, "calibrate_roi", lambda *_: roi)
    worker_calls = []

    def worker(image_path, _output_dir, _config, definition):
        worker_calls.append((image_path, definition))
        return pd.DataFrame([{"image": image_path.name, "area": 1}])

    monkeypatch.setattr(analyze_canopy, "_analyze_image_worker", worker)

    result = analyze_canopy.analyze_images(
        images, output_dir, config, n_workers=1
    )

    assert len(result) == 2
    assert worker_calls == [(images[0], roi), (images[1], roi)]
    assert RoiDefinition.load(output_dir / "roi-definition.json") == roi

    monkeypatch.setattr(
        analyze_canopy,
        "calibrate_roi",
        lambda *_: pytest.fail("saved ROI should have been reused"),
    )
    worker_calls.clear()
    analyze_canopy.analyze_images(images, output_dir, config, n_workers=1)
    assert worker_calls == [(images[0], roi), (images[1], roi)]
