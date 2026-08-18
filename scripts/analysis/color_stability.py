"""Measure RGB drift in a fixed image region relative to the first capture."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")


def timestamp_from_path(path: Path) -> pd.Timestamp:
    match = TIMESTAMP_PATTERN.search(path.name)
    if match is None:
        raise ValueError(f"No YYYYMMDD_HHMMSS timestamp in {path.name}")
    return pd.to_datetime(match.group(1), format="%Y%m%d_%H%M%S")


def _load_measurement(
    image_path: Path, roi: tuple[int, int, int, int]
) -> tuple[np.ndarray, float]:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")

    x, y, width, height = roi
    image_height, image_width = image.shape[:2]
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"Invalid ROI {roi}")
    if x + width > image_width or y + height > image_height:
        raise ValueError(
            f"ROI {roi} exceeds {image_width}x{image_height} image {image_path.name}"
        )

    patch = image[y : y + height, x : x + width]
    rgb_mean = patch.mean(axis=(0, 1))[::-1]  # OpenCV BGR -> RGB
    grayscale_mean = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())
    return rgb_mean, grayscale_mean


def measure_rgb(image_path: Path, roi: tuple[int, int, int, int]) -> np.ndarray:
    return _load_measurement(image_path, roi)[0]


def analyze_images(
    image_paths: list[Path],
    roi: tuple[int, int, int, int],
    *,
    black_mean_threshold: float = 10.0,
) -> pd.DataFrame:
    if not image_paths:
        raise ValueError("No images were supplied")
    if black_mean_threshold < 0:
        raise ValueError("Black-image mean threshold must be non-negative")

    ordered = sorted(image_paths, key=timestamp_from_path)
    rows = []
    for path in ordered:
        rgb_mean, grayscale_mean = _load_measurement(path, roi)
        if grayscale_mean <= black_mean_threshold:
            continue
        red, green, blue = rgb_mean
        rows.append(
            {
                "image": path.name,
                "timestamp": timestamp_from_path(path),
                "mean_red": red,
                "mean_green": green,
                "mean_blue": blue,
                "image_grayscale_mean": grayscale_mean,
            }
        )

    if not rows:
        raise ValueError(
            "No non-black images remain above the configured mean threshold"
        )
    table = pd.DataFrame(rows)
    for channel in ("red", "green", "blue"):
        table[f"drift_{channel}"] = (
            table[f"mean_{channel}"] - table.loc[0, f"mean_{channel}"]
        )
    table["drift_magnitude"] = np.sqrt(
        sum(table[f"drift_{channel}"] ** 2 for channel in ("red", "green", "blue"))
    )
    table.attrs["source_images"] = len(ordered)
    table.attrs["excluded_black_images"] = len(ordered) - len(table)
    table.attrs["black_mean_threshold"] = black_mean_threshold
    return table


def summarize(table: pd.DataFrame, roi: tuple[int, int, int, int]) -> dict:
    elapsed_days = (
        table["timestamp"] - table.loc[0, "timestamp"]
    ).dt.total_seconds().to_numpy() / 86400
    result = {
        "images": len(table),
        "source_images": table.attrs.get("source_images", len(table)),
        "excluded_black_images": table.attrs.get("excluded_black_images", 0),
        "black_mean_threshold": table.attrs.get("black_mean_threshold"),
        "roi": dict(zip(("x", "y", "width", "height"), roi)),
        "baseline_image": table.loc[0, "image"],
        "baseline_timestamp": table.loc[0, "timestamp"].isoformat(),
        "ending_timestamp": table.loc[len(table) - 1, "timestamp"].isoformat(),
        "duration_days": float(elapsed_days[-1]),
        "channels": {},
        "maximum_drift_magnitude": float(table["drift_magnitude"].max()),
    }
    for channel in ("red", "green", "blue"):
        values = table[f"drift_{channel}"].to_numpy()
        slope = float(np.polyfit(elapsed_days, values, 1)[0]) if len(table) > 1 else 0.0
        result["channels"][channel] = {
            "baseline_mean": float(table.loc[0, f"mean_{channel}"]),
            "ending_drift": float(values[-1]),
            "minimum_drift": float(values.min()),
            "maximum_drift": float(values.max()),
            "mean_drift": float(values.mean()),
            "slope_per_day": slope,
        }
    return result


def save_plot(table: pd.DataFrame, output_path: Path) -> None:
    colors = {"red": "#c62828", "green": "#2e7d32", "blue": "#1565c0"}
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for channel, color in colors.items():
        axes[0].plot(table["timestamp"], table[f"mean_{channel}"], color=color,
                     label=channel.capitalize(), linewidth=1.4)
        axes[1].plot(table["timestamp"], table[f"drift_{channel}"], color=color,
                     label=channel.capitalize(), linewidth=1.4)
    axes[0].set_ylabel("Mean intensity (8-bit)")
    axes[0].set_title("Fixed-reference RGB intensity")
    axes[0].legend(ncol=3)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("Drift from first image")
    axes[1].set_xlabel("Capture time")
    axes[1].set_title("Channel-specific colour drift")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def save_roi_preview(
    image_path: Path, roi: tuple[int, int, int, int], output_path: Path
) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    x, y, width, height = roi
    cv2.rectangle(image, (x, y), (x + width, y + height), (0, 255, 0), 10)
    if not cv2.imwrite(str(output_path), image):
        raise OSError(f"Could not save ROI preview: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--glob", default="capture_*.jpg")
    parser.add_argument("--roi", nargs=4, type=int, required=True,
                        metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument(
        "--black-mean-threshold",
        type=float,
        default=10.0,
        help=(
            "Exclude images whose full-image mean grayscale intensity is at or "
            "below this value (default: 10)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roi = tuple(args.roi)
    paths = list(args.image_directory.glob(args.glob))
    table = analyze_images(
        paths, roi, black_mean_threshold=args.black_mean_threshold
    )
    args.output_directory.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output_directory / "color_stability.csv", index=False)
    summary = summarize(table, roi)
    (args.output_directory / "color_stability_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    save_plot(table, args.output_directory / "color_stability.png")
    save_roi_preview(
        args.image_directory / table.loc[0, "image"],
        roi,
        args.output_directory / "color_stability_roi.jpg",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
