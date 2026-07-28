from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_THRESHOLDS = tuple(range(110, 171, 5))
DEFAULT_FILL_SIZES = (0, 25, 50, 100, 200, 400, 800, 1600)


@dataclass(frozen=True)
class SegmentationScore:
    """Quality measures for one binary foreground/background partition."""

    separability: float
    foreground_fraction: float


def foreground_separability(
    channel: np.ndarray,
    foreground_mask: np.ndarray,
) -> SegmentationScore:
    """Return Otsu's normalized between-class variance for a final mask.

    A value near one means that foreground and background have compact,
    well-separated channel intensities. A value near zero means the two
    classes overlap or one class is effectively absent.
    """
    if channel.shape != foreground_mask.shape:
        raise ValueError("Channel and foreground mask must have equal shapes.")
    values = channel.astype(np.float64, copy=False)
    foreground = foreground_mask.astype(bool, copy=False)
    foreground_fraction = float(foreground.mean())
    if foreground_fraction <= 0 or foreground_fraction >= 1:
        return SegmentationScore(0.0, foreground_fraction)

    total_variance = float(values.var())
    if total_variance <= 0:
        return SegmentationScore(0.0, foreground_fraction)

    foreground_mean = float(values[foreground].mean())
    background_mean = float(values[~foreground].mean())
    between_class_variance = (
        foreground_fraction
        * (1 - foreground_fraction)
        * (foreground_mean - background_mean) ** 2
    )
    return SegmentationScore(
        separability=float(between_class_variance / total_variance),
        foreground_fraction=foreground_fraction,
    )


def load_lab_channel(
    image_path: Path,
    channel: str = "a",
) -> np.ndarray:
    """Load one image and return its selected OpenCV LAB channel."""
    if channel not in {"l", "a", "b"}:
        raise ValueError("LAB channel must be one of: l, a, b.")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Image could not be decoded: {image_path}")
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    return lab[:, :, {"l": 0, "a": 1, "b": 2}[channel]]


def sensitivity_table(
    channels: Iterable[np.ndarray],
    thresholds: Iterable[int],
    fill_sizes: Iterable[int],
) -> pd.DataFrame:
    """Evaluate all threshold/fill-size combinations across input channels."""
    channel_values = list(channels)
    threshold_values = list(thresholds)
    fill_values = list(fill_sizes)
    if not channel_values:
        raise ValueError("At least one image channel is required.")
    if not threshold_values or not fill_values:
        raise ValueError("Threshold and fill-size grids cannot be empty.")

    rows = []
    for threshold in threshold_values:
        if not 0 <= threshold <= 255:
            raise ValueError("Threshold values must be between 0 and 255.")
        per_image_components = [
            _threshold_components(channel, threshold)
            for channel in channel_values
        ]
        for fill_size in fill_values:
            if fill_size < 0:
                raise ValueError("Fill-size values must be non-negative.")
            scores = [
                foreground_separability(
                    channel,
                    _retained_component_mask(labels, areas, fill_size),
                )
                for channel, (labels, areas) in zip(
                    channel_values,
                    per_image_components,
                    strict=True,
                )
            ]
            separability = np.array(
                [score.separability for score in scores],
                dtype=float,
            )
            coverage = np.array(
                [score.foreground_fraction for score in scores],
                dtype=float,
            )
            rows.append(
                {
                    "threshold": threshold,
                    "fill_size": fill_size,
                    "separability_mean": separability.mean(),
                    "separability_sd": separability.std(ddof=0),
                    "foreground_fraction_mean": coverage.mean(),
                    "foreground_fraction_sd": coverage.std(ddof=0),
                    "images": len(scores),
                }
            )
    return pd.DataFrame(rows)


def plot_sensitivity(
    table: pd.DataFrame,
    output_path: Path,
    *,
    selected_threshold: int = 145,
    selected_fill_size: int = 200,
) -> None:
    """Plot separability and retained foreground across the parameter grid."""
    thresholds = sorted(table["threshold"].unique())
    fill_sizes = sorted(table["fill_size"].unique())
    separation = _matrix(
        table,
        "separability_mean",
        thresholds,
        fill_sizes,
    )
    coverage = _matrix(
        table,
        "foreground_fraction_mean",
        thresholds,
        fill_sizes,
    ) * 100

    figure, axes = plt.subplots(1, 2, figsize=(12.4, 5.2), constrained_layout=True)
    panels = (
        (axes[0], separation, "Foreground–background separability", "η²", "viridis", 0, 1),
        (axes[1], coverage, "Retained foreground", "Image area (%)", "magma", 0, None),
    )
    for axis, values, title, colorbar_label, colour_map, lower, upper in panels:
        image = axis.imshow(
            values,
            origin="lower",
            aspect="auto",
            cmap=colour_map,
            vmin=lower,
            vmax=upper,
        )
        axis.set_title(title, fontweight="bold")
        axis.set_xlabel("LAB threshold")
        axis.set_ylabel("Minimum component area (pixels)")
        axis.set_xticks(range(len(thresholds)), thresholds, rotation=45)
        axis.set_yticks(range(len(fill_sizes)), fill_sizes)
        colorbar = figure.colorbar(image, ax=axis, shrink=0.88)
        colorbar.set_label(colorbar_label)
        if (
            selected_threshold in thresholds
            and selected_fill_size in fill_sizes
        ):
            axis.scatter(
                thresholds.index(selected_threshold),
                fill_sizes.index(selected_fill_size),
                marker="s",
                s=125,
                facecolors="none",
                edgecolors="white",
                linewidths=2,
                label="Current default",
            )
            axis.legend(loc="upper left", frameon=True)

    figure.suptitle(
        "Sensitivity of canopy segmentation parameters",
        fontsize=14,
        fontweight="bold",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(figure)


def _threshold_components(
    channel: np.ndarray,
    threshold: int,
) -> tuple[np.ndarray, np.ndarray]:
    binary = (channel <= threshold).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    return labels, stats[:, cv2.CC_STAT_AREA]


def _retained_component_mask(
    labels: np.ndarray,
    areas: np.ndarray,
    minimum_area: int,
) -> np.ndarray:
    retained = areas >= max(minimum_area, 1)
    retained[0] = False
    return retained[labels]


def _matrix(
    table: pd.DataFrame,
    column: str,
    thresholds: list[int],
    fill_sizes: list[int],
) -> np.ndarray:
    return (
        table.pivot(index="fill_size", columns="threshold", values=column)
        .reindex(index=fill_sizes, columns=thresholds)
        .to_numpy()
    )


def _parse_values(value: str) -> list[int]:
    """Parse comma lists or inclusive start:stop:step ranges."""
    if ":" not in value:
        return [int(item) for item in value.split(",") if item.strip()]
    parts = [int(item) for item in value.split(":")]
    if len(parts) != 3 or parts[2] <= 0 or parts[1] < parts[0]:
        raise argparse.ArgumentTypeError(
            "Ranges must use start:stop:positive-step."
        )
    start, stop, step = parts
    return list(range(start, stop + 1, step))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep threshold and fill size and plot foreground/background "
            "separability."
        )
    )
    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="Representative calibration image(s).",
    )
    parser.add_argument(
        "--channel",
        choices=("l", "a", "b"),
        default="a",
        help="LAB channel used by the segmentation pipeline.",
    )
    parser.add_argument(
        "--thresholds",
        type=_parse_values,
        default=list(DEFAULT_THRESHOLDS),
        help="Comma list or inclusive start:stop:step range.",
    )
    parser.add_argument(
        "--fill-sizes",
        type=_parse_values,
        default=list(DEFAULT_FILL_SIZES),
        help="Comma-separated minimum connected-component areas.",
    )
    parser.add_argument(
        "--selected-threshold",
        type=int,
        default=145,
        help="Threshold to mark as the current/default operating point.",
    )
    parser.add_argument(
        "--selected-fill-size",
        type=int,
        default=200,
        help="Fill size to mark as the current/default operating point.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/parameter_sensitivity.png"),
        help="Output figure.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("results/parameter_sensitivity.csv"),
        help="Output table containing every evaluated combination.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    channels = [load_lab_channel(path, args.channel) for path in args.images]
    table = sensitivity_table(channels, args.thresholds, args.fill_sizes)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.csv, index=False)
    plot_sensitivity(
        table,
        args.output,
        selected_threshold=args.selected_threshold,
        selected_fill_size=args.selected_fill_size,
    )
    best = table.loc[table["separability_mean"].idxmax()]
    print(f"Wrote {args.output}")
    print(f"Wrote {args.csv}")
    print(
        "Highest separability: "
        f"threshold={int(best['threshold'])}, "
        f"fill_size={int(best['fill_size'])}, "
        f"eta_squared={best['separability_mean']:.3f}, "
        f"foreground={best['foreground_fraction_mean']:.1%}"
    )


if __name__ == "__main__":
    main()
