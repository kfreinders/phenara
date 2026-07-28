import numpy as np

from scripts.analysis.parameter_sensitivity import (
    foreground_separability,
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
