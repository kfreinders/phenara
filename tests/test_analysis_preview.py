import base64

import cv2
import numpy as np
import pytest

from gui.services.analysis_preview import build_analysis_preview
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.preview import (
    apply_mask_exclusions,
    generate_analysis_preview,
)
from scripts.analysis.roi import AnalysisCrop


def encoded_test_image() -> bytes:
    image = np.full((80, 120, 3), 240, dtype=np.uint8)
    cv2.circle(image, (60, 40), 20, (20, 80, 20), thickness=-1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def test_preview_generates_display_stages_without_trait_analysis():
    preview = generate_analysis_preview(
        encoded_test_image(),
        AnalysisConfig(threshold=120, fill_size=10),
        max_dimension=60,
    )

    assert preview.original.shape == (40, 60, 3)
    assert preview.channel.shape == (40, 60)
    assert preview.mask.shape == (40, 60)
    assert preview.overlay.shape == (40, 60, 3)
    assert set(np.unique(preview.mask)).issubset({0, 255})


def test_processing_previews_use_crop_while_input_remains_complete():
    preview = generate_analysis_preview(
        encoded_test_image(),
        AnalysisConfig(fill_size=10),
        max_dimension=120,
        analysis_crop=AnalysisCrop(x=0.25, y=0, width=0.5, height=1),
    )

    assert preview.original.shape == (80, 120, 3)
    assert preview.channel.shape == (80, 60)
    assert preview.mask.shape == (80, 60)
    assert preview.overlay.shape == (80, 60, 3)


def test_calibration_brush_erases_only_selected_crop_coordinates():
    mask = np.full((100, 200), 255, dtype=np.uint8)
    crop = AnalysisCrop(x=0.5, y=0, width=0.5, height=1)

    edited = apply_mask_exclusions(
        mask,
        crop,
        [{"radius": 0.1, "points": [{"x": 0.5, "y": 0.5}]}],
    )

    assert edited[50, 150] == 0
    assert edited[50, 50] == 255
    assert mask[50, 150] == 255


def test_preview_service_returns_browser_safe_images_and_config_identity():
    encoded = base64.b64encode(encoded_test_image()).decode()
    result = build_analysis_preview(
        f"data:image/jpeg;base64,{encoded}",
        {"threshold": 111},
    )

    assert result["config"]["threshold"] == 111
    assert result["config_fingerprint"] == AnalysisConfig(
        threshold=111
    ).fingerprint
    assert set(result["stages"]) == {
        "original",
        "channel",
        "mask",
        "overlay",
    }
    assert all(
        value.startswith("data:image/png;base64,")
        for value in result["stages"].values()
    )


@pytest.mark.parametrize(
    "value",
    ["", "not-a-data-url", "data:image/jpeg;base64,not base64"],
)
def test_preview_service_rejects_invalid_image_data(value):
    with pytest.raises(ValueError):
        build_analysis_preview(value, {})
