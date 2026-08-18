from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import linregress, spearmanr


DEFAULT_THRESHOLDS = tuple(range(110, 171, 5))
DEFAULT_FILL_SIZES = (0, 25, 50, 100, 200, 400, 800, 1600)
CAPTURE_DATE_PATTERN = re.compile(r"^capture_(\d{8})_\d{6}\.(?:jpg|jpeg)$", re.I)


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

    measurements = {
        (threshold, fill_size): ([], [])
        for threshold in threshold_values
        for fill_size in fill_values
    }
    for threshold in threshold_values:
        if not 0 <= threshold <= 255:
            raise ValueError("Threshold values must be between 0 and 255.")
    if any(fill_size < 0 for fill_size in fill_values):
        raise ValueError("Fill-size values must be non-negative.")

    for channel in channel_values:
        for threshold in threshold_values:
            labels, areas = _threshold_components(channel, threshold)
            for fill_size in fill_values:
                score = foreground_separability(
                    channel,
                    _retained_component_mask(labels, areas, fill_size),
                )
                separability, coverage = measurements[(threshold, fill_size)]
                separability.append(score.separability)
                coverage.append(score.foreground_fraction)

    rows = []
    for threshold in threshold_values:
        for fill_size in fill_values:
            separation_values, coverage_values = measurements[
                (threshold, fill_size)
            ]
            separability = np.array(
                separation_values,
                dtype=float,
            )
            coverage = np.array(
                coverage_values,
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
                    "images": len(separability),
                }
            )
    return pd.DataFrame(rows)


def canopy_area_sensitivity_table(
    channels: Iterable[np.ndarray],
    image_names: Iterable[str],
    thresholds: Iterable[int],
    fill_sizes: Iterable[int],
    *,
    selected_threshold: int = 145,
    selected_fill_size: int = 200,
) -> pd.DataFrame:
    """Relate per-image sweep effects to canopy area at the default settings.

    Canopy area is expressed as the percentage of the complete image retained
    as foreground at the selected operating point. Sensitivity is the range in
    retained foreground across one parameter axis while the other is fixed at
    that operating point.
    """
    channel_values = list(channels)
    names = list(image_names)
    threshold_values = list(thresholds)
    fill_values = list(fill_sizes)
    if len(channel_values) != len(names):
        raise ValueError("Each image channel must have one image name.")
    if selected_threshold not in threshold_values:
        raise ValueError("Selected threshold must occur in the threshold sweep.")
    if selected_fill_size not in fill_values:
        raise ValueError("Selected fill size must occur in the fill-size sweep.")

    rows = []
    for image_name, channel in zip(names, channel_values):
        coverage: dict[tuple[int, int], float] = {}
        for threshold in threshold_values:
            labels, areas = _threshold_components(channel, threshold)
            evaluated_fill_sizes = (
                fill_values
                if threshold == selected_threshold
                else [selected_fill_size]
            )
            for fill_size in evaluated_fill_sizes:
                coverage[(threshold, fill_size)] = foreground_separability(
                    channel,
                    _retained_component_mask(labels, areas, fill_size),
                ).foreground_fraction

        threshold_coverages = [
            coverage[(threshold, selected_fill_size)]
            for threshold in threshold_values
        ]
        fill_coverages = [
            coverage[(selected_threshold, fill_size)]
            for fill_size in fill_values
        ]
        canopy_area = coverage[(selected_threshold, selected_fill_size)] * 100
        threshold_sensitivity = (
            max(threshold_coverages) - min(threshold_coverages)
        ) * 100
        fill_sensitivity = (max(fill_coverages) - min(fill_coverages)) * 100
        rows.append(
            {
                "image": image_name,
                "canopy_area_percent": canopy_area,
                "threshold_sensitivity_pp": threshold_sensitivity,
                "fill_size_sensitivity_pp": fill_sensitivity,
                "threshold_relative_sensitivity_percent": (
                    threshold_sensitivity / canopy_area * 100
                ),
                "fill_size_relative_sensitivity_percent": (
                    fill_sensitivity / canopy_area * 100
                ),
            }
        )
    return pd.DataFrame(rows)


def canopy_area_effects(table: pd.DataFrame) -> pd.DataFrame:
    """Return linear and rank correlations for both sensitivity measures."""
    rows = []
    x = table["canopy_area_percent"].to_numpy(dtype=float)
    for parameter, scale, column in (
        ("threshold", "absolute", "threshold_sensitivity_pp"),
        ("fill_size", "absolute", "fill_size_sensitivity_pp"),
        (
            "threshold",
            "relative",
            "threshold_relative_sensitivity_percent",
        ),
        (
            "fill_size",
            "relative",
            "fill_size_relative_sensitivity_percent",
        ),
    ):
        y = table[column].to_numpy(dtype=float)
        linear = linregress(x, y)
        rank = spearmanr(x, y)
        power = linregress(np.log(x), np.log(y))
        rows.append(
            {
                "parameter": parameter,
                "scale": scale,
                "slope_pp_per_canopy_pp": linear.slope,
                "intercept_pp": linear.intercept,
                "pearson_r": linear.rvalue,
                "r_squared": linear.rvalue**2,
                "p_value": linear.pvalue,
                "spearman_rho": rank.statistic,
                "spearman_p_value": rank.pvalue,
                "power_exponent": power.slope,
                "power_r_squared": power.rvalue**2,
                "power_p_value": power.pvalue,
                "images": len(table),
            }
        )
    return pd.DataFrame(rows)


def plot_canopy_area_effect(
    table: pd.DataFrame,
    effects: pd.DataFrame,
    output_path: Path,
) -> None:
    """Plot parameter sensitivity against the canopy-area proxy."""
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), constrained_layout=True)
    panels = (
        (
            axes[0],
            "threshold",
            "threshold_relative_sensitivity_percent",
            "Threshold sensitivity",
            "#2878b5",
        ),
        (
            axes[1],
            "fill_size",
            "fill_size_relative_sensitivity_percent",
            "Fill-size sensitivity",
            "#d05a3a",
        ),
    )
    x = table["canopy_area_percent"].to_numpy(dtype=float)
    for axis, parameter, column, title, colour in panels:
        y = table[column].to_numpy(dtype=float)
        effect = effects.loc[
            (effects["parameter"] == parameter)
            & (effects["scale"] == "relative")
        ].iloc[0]
        axis.scatter(x, y, color=colour, s=42)
        x_line = np.geomspace(x.min(), x.max(), 100)
        coefficient = np.exp(
            np.log(y).mean()
            - effect["power_exponent"] * np.log(x).mean()
        )
        axis.plot(
            x_line,
            coefficient * x_line ** effect["power_exponent"],
            color=colour,
            linewidth=2,
        )
        axis.set_title(title, fontweight="bold")
        axis.set_xlabel("Canopy area at default settings (% of image)")
        axis.set_ylabel("Sweep-induced range relative to\ncanopy estimate (%)")
        axis.grid(alpha=0.2)
        p_text = (
            "< 0.001"
            if effect["power_p_value"] < 0.001
            else f"= {effect['power_p_value']:.3f}"
        )
        axis.text(
            0.96,
            0.96,
            f"Power $R^2$ = {effect['power_r_squared']:.2f}\n"
            f"$p$ {p_text}\n"
            f"$\\rho$ = {effect['spearman_rho']:.2f}",
            transform=axis.transAxes,
            ha="right",
            va="top",
        )
    figure.suptitle(
        "Effect of canopy area on segmentation parameter sensitivity",
        fontsize=14,
        fontweight="bold",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(figure)


def select_first_non_black_per_day(
    image_paths: Iterable[Path],
    *,
    black_mean_threshold: float = 10.0,
) -> list[Path]:
    """Select the earliest illuminated capture for each filename date."""
    if black_mean_threshold < 0:
        raise ValueError("Black-image mean threshold must be non-negative.")
    grouped: dict[str, list[Path]] = {}
    for image_path in sorted(image_paths):
        match = CAPTURE_DATE_PATTERN.match(image_path.name)
        if match is None:
            continue
        grouped.setdefault(match.group(1), []).append(image_path)

    selected = []
    for date, daily_paths in sorted(grouped.items()):
        for image_path in daily_paths:
            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            if float(image.mean()) > black_mean_threshold:
                selected.append(image_path)
                break
        else:
            raise ValueError(f"No non-black capture was found for {date}.")
    if not selected:
        raise ValueError("No dated, non-black capture images were found.")
    return selected


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

    image_count = int(table["images"].max())
    figure.suptitle(
        "Sensitivity of canopy segmentation parameters"
        f"\nMean across {image_count} representative image"
        f"{'' if image_count == 1 else 's'}",
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
        nargs="*",
        type=Path,
        help="Representative calibration image(s).",
    )
    parser.add_argument(
        "--daily-directory",
        type=Path,
        default=None,
        help="Select the first non-black capture for each date in this directory.",
    )
    parser.add_argument(
        "--black-mean-threshold",
        type=float,
        default=10.0,
        help="Images at or below this mean grayscale intensity are black frames.",
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
    parser.add_argument(
        "--canopy-effect-output",
        type=Path,
        default=Path("results/parameter_sensitivity_by_canopy_area.png"),
        help="Output figure relating sweep sensitivity to canopy area.",
    )
    parser.add_argument(
        "--canopy-effect-csv",
        type=Path,
        default=Path("results/parameter_sensitivity_by_canopy_area.csv"),
        help="Per-image canopy-area sensitivity measurements.",
    )
    parser.add_argument(
        "--canopy-effect-summary-csv",
        type=Path,
        default=Path("results/parameter_sensitivity_canopy_effects.csv"),
        help="Regression and correlation statistics for the canopy-area effect.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.daily_directory is not None and args.images:
        raise ValueError("Use either image paths or --daily-directory, not both.")
    image_paths = (
        select_first_non_black_per_day(
            args.daily_directory.glob("capture_*.jpg"),
            black_mean_threshold=args.black_mean_threshold,
        )
        if args.daily_directory is not None
        else args.images
    )
    if not image_paths:
        raise ValueError("Provide image paths or --daily-directory.")
    print(f"Selected {len(image_paths)} image(s):")
    for image_path in image_paths:
        print(f"  {image_path}")
    channels = [load_lab_channel(path, args.channel) for path in image_paths]
    table = sensitivity_table(channels, args.thresholds, args.fill_sizes)
    canopy_table = canopy_area_sensitivity_table(
        channels,
        [path.name for path in image_paths],
        args.thresholds,
        args.fill_sizes,
        selected_threshold=args.selected_threshold,
        selected_fill_size=args.selected_fill_size,
    )
    canopy_effects = canopy_area_effects(canopy_table)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.csv, index=False)
    args.canopy_effect_csv.parent.mkdir(parents=True, exist_ok=True)
    canopy_table.to_csv(args.canopy_effect_csv, index=False)
    args.canopy_effect_summary_csv.parent.mkdir(parents=True, exist_ok=True)
    canopy_effects.to_csv(args.canopy_effect_summary_csv, index=False)
    plot_sensitivity(
        table,
        args.output,
        selected_threshold=args.selected_threshold,
        selected_fill_size=args.selected_fill_size,
    )
    plot_canopy_area_effect(
        canopy_table,
        canopy_effects,
        args.canopy_effect_output,
    )
    best = table.loc[table["separability_mean"].idxmax()]
    print(f"Wrote {args.output}")
    print(f"Wrote {args.csv}")
    print(f"Wrote {args.canopy_effect_output}")
    print(f"Wrote {args.canopy_effect_csv}")
    print(f"Wrote {args.canopy_effect_summary_csv}")
    print(
        "Highest separability: "
        f"threshold={int(best['threshold'])}, "
        f"fill_size={int(best['fill_size'])}, "
        f"eta_squared={best['separability_mean']:.3f}, "
        f"foreground={best['foreground_fraction_mean']:.1%}"
    )


if __name__ == "__main__":
    main()
