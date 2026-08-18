import json

import pytest

from scripts.analysis.config import AnalysisConfig


def test_analysis_config_round_trips_and_has_stable_fingerprint(tmp_path):
    config = AnalysisConfig(threshold=121, roi_rows=4, roi_cols=7)
    path = tmp_path / "nested" / "analysis-config.json"

    config.save(path)
    restored = AnalysisConfig.load(path)

    assert restored == config
    assert restored.fingerprint == config.fingerprint
    assert json.loads(path.read_text())["schema_version"] == 1
    assert not list(path.parent.glob(f".{path.name}.*"))


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"sepchannel": "red"}, "LAB channel"),
        ({"threshold": 256}, "between 0 and 255"),
        ({"roi_rows": 0}, "ROI rows"),
        ({"roi_diameter_scale": 2.1}, "ROI diameter scale"),
        ({"fill_size": -1}, "Fill size"),
        ({"pot_diameter_px": 0}, "Pot diameter in pixels"),
        ({"grid_x": 10}, "require x, y, width, and height"),
        (
            {"grid_x": 0, "grid_y": 0, "grid_width": 0, "grid_height": 20},
            "width and height must be positive",
        ),
    ],
)
def test_analysis_config_rejects_invalid_values(values, message):
    with pytest.raises(ValueError, match=message):
        AnalysisConfig(**values)


def test_analysis_config_rejects_unknown_fields_and_versions():
    with pytest.raises(ValueError, match="Unknown.*surprise"):
        AnalysisConfig.from_dict({"surprise": True})
    with pytest.raises(ValueError, match="Unsupported.*2"):
        AnalysisConfig.from_dict({"schema_version": 2})


def test_analysis_config_reports_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        AnalysisConfig.from_json("")


def test_analysis_config_uses_safe_calibration_defaults():
    assert AnalysisConfig().threshold == 145
    assert AnalysisConfig().roi_diameter_scale == 1.0
