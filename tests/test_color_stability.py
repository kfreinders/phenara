from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.analysis.color_stability import analyze_images, measure_rgb


def write_image(path: Path, rgb: tuple[int, int, int]) -> None:
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    image[2:6, 3:8] = rgb[::-1]
    assert cv2.imwrite(str(path), image)


def test_analysis_sorts_images_and_calculates_drift_from_first(tmp_path):
    later = tmp_path / "capture_20260602_120000.png"
    first = tmp_path / "capture_20260601_120000.png"
    write_image(first, (50, 60, 70))
    write_image(later, (55, 57, 80))

    table = analyze_images([later, first], (3, 2, 5, 4))

    assert list(table["image"]) == [first.name, later.name]
    assert table.loc[0, ["drift_red", "drift_green", "drift_blue"]].tolist() == [0, 0, 0]
    assert table.loc[1, ["drift_red", "drift_green", "drift_blue"]].to_numpy() == pytest.approx([5, -3, 10])


def test_measurement_rejects_roi_outside_image(tmp_path):
    path = tmp_path / "capture_20260601_120000.png"
    write_image(path, (50, 60, 70))

    with pytest.raises(ValueError, match="exceeds"):
        measure_rgb(path, (8, 7, 3, 2))


def test_analysis_excludes_black_images_and_reports_count(tmp_path):
    black = tmp_path / "capture_20260601_110000.png"
    illuminated = tmp_path / "capture_20260601_120000.png"
    write_image(black, (0, 0, 0))
    write_image(illuminated, (50, 60, 70))

    table = analyze_images([black, illuminated], (3, 2, 5, 4))

    assert list(table["image"]) == [illuminated.name]
    assert table.attrs["source_images"] == 2
    assert table.attrs["excluded_black_images"] == 1


def test_analysis_rejects_negative_black_threshold(tmp_path):
    path = tmp_path / "capture_20260601_120000.png"
    write_image(path, (50, 60, 70))

    with pytest.raises(ValueError, match="non-negative"):
        analyze_images([path], (3, 2, 5, 4), black_mean_threshold=-1)
