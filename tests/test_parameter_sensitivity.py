import numpy as np
import cv2

from scripts.analysis.parameter_sensitivity import (
    canopy_area_effects,
    canopy_area_sensitivity_table,
    foreground_separability,
    select_first_non_black_per_day,
    sensitivity_table,
)


def test_separability_is_high_for_distinct_foreground_and_background():
    channel = np.array([
        [20, 20, 220, 220],
        [20, 20, 220, 220],
    ], dtype=np.uint8)
    foreground = channel < 100

    score = foreground_separability(channel, foreground)

    assert score.separability == 1
    assert score.foreground_fraction == 0.5


def test_separability_is_zero_for_degenerate_mask():
    channel = np.arange(9, dtype=np.uint8).reshape(3, 3)

    score = foreground_separability(
        channel,
        np.zeros_like(channel, dtype=bool),
    )

    assert score.separability == 0
    assert score.foreground_fraction == 0


def test_fill_size_removes_small_components_and_changes_coverage():
    channel = np.full((8, 8), 220, dtype=np.uint8)
    channel[1, 1] = 20
    channel[3:6, 3:6] = 20

    table = sensitivity_table(
        [channel],
        thresholds=[100],
        fill_sizes=[0, 2],
    ).set_index("fill_size")

    assert table.loc[0, "foreground_fraction_mean"] == 10 / 64
    assert table.loc[2, "foreground_fraction_mean"] == 9 / 64
    assert set(table["images"]) == {1}


def test_selects_first_non_black_capture_for_each_day(tmp_path):
    paths = [
        tmp_path / "capture_20260601_080000.jpg",
        tmp_path / "capture_20260601_080100.jpg",
        tmp_path / "capture_20260602_080000.jpg",
    ]
    cv2.imwrite(str(paths[0]), np.zeros((10, 10), dtype=np.uint8))
    cv2.imwrite(str(paths[1]), np.full((10, 10), 80, dtype=np.uint8))
    cv2.imwrite(str(paths[2]), np.full((10, 10), 90, dtype=np.uint8))

    selected = select_first_non_black_per_day(paths)

    assert selected == [paths[1], paths[2]]


def test_quantifies_sweep_sensitivity_against_canopy_area():
    small = np.full((20, 20), 220, dtype=np.uint8)
    small[5:10, 5:10] = 120
    large = np.full((20, 20), 220, dtype=np.uint8)
    large[3:17, 3:17] = 120

    table = canopy_area_sensitivity_table(
        [small, large],
        ["small.jpg", "large.jpg"],
        thresholds=[110, 145, 170],
        fill_sizes=[0, 10, 200],
        selected_threshold=145,
        selected_fill_size=10,
    )

    assert list(table["image"]) == ["small.jpg", "large.jpg"]
    assert table.loc[0, "canopy_area_percent"] < table.loc[1, "canopy_area_percent"]
    effects = canopy_area_effects(table)
    assert set(effects["parameter"]) == {
        "threshold",
        "fill_size",
    }
    assert set(effects["scale"]) == {"absolute", "relative"}
