#!/usr/bin/env python3
"""Canopy-size-dependent measurement-noise analysis for one repeated dataset."""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import statsmodels.api as sm


@dataclass(frozen=True)
class Columns:
    """Names of the input columns used by the analysis."""

    time: str
    replicate: str
    measurement: str
    canopy: str


@dataclass
class ValidationReport:
    """Counts and messages describing input-row validation."""

    total_rows: int
    valid_rows: int
    reason_counts: dict[str, int]
    ordering_method: str

    @property
    def excluded_rows(self) -> int:
        return self.total_rows - self.valid_rows


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line settings."""
    parser = argparse.ArgumentParser(
        description="Analyze canopy-size-dependent replicate measurement noise."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input CSV file.")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Directory for analysis outputs."
    )
    parser.add_argument("--time-column", default="timepoint")
    parser.add_argument("--replicate-column", default="replicate")
    parser.add_argument("--measurement-column", default="measurement")
    parser.add_argument("--canopy-column", default="canopy_size")
    return parser.parse_args(argv)


def _ordering_key(values: pd.Series) -> tuple[pd.Series, str]:
    """Return a sortable chronological key and a description of its derivation."""
    text = values.astype(str)
    numeric = pd.to_numeric(text, errors="coerce")
    if numeric.notna().all():
        return numeric, "numeric timepoint values"

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        datetimes = pd.to_datetime(text, errors="coerce")
    if datetimes.notna().all():
        return datetimes, "datetime timepoint values"

    embedded_timestamp = text.str.extract(
        r"(?P<date>\d{8})[_T-]?(?P<time>\d{6})", expand=True
    )
    embedded_datetimes = pd.to_datetime(
        embedded_timestamp["date"] + embedded_timestamp["time"],
        format="%Y%m%d%H%M%S",
        errors="coerce",
    )
    if embedded_datetimes.notna().all():
        return embedded_datetimes, "embedded YYYYMMDD_HHMMSS timestamps"

    print(
        "WARNING: timepoints are neither uniformly numeric nor datetime-like; "
        "using their first-appearance order.",
        file=sys.stderr,
    )
    first_order = {value: index for index, value in enumerate(pd.unique(text))}
    return text.map(first_order), "first appearance (non-numeric/non-datetime labels)"


def _datetime_values(values: pd.Series) -> pd.Series:
    """Parse complete or filename-embedded timestamps, returning missing on failure."""
    text = values.astype(str)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(text, errors="coerce")
    missing = parsed.isna()
    if missing.any():
        embedded = text.loc[missing].str.extract(
            r"(?P<date>\d{8})[_T-]?(?P<time>\d{6})", expand=True
        )
        parsed.loc[missing] = pd.to_datetime(
            embedded["date"] + embedded["time"],
            format="%Y%m%d%H%M%S",
            errors="coerce",
        )
    return parsed


def load_and_validate_data(
    input_path: Path, columns: Columns
) -> tuple[pd.DataFrame, ValidationReport]:
    """Load the CSV, reject invalid rows, and attach a chronological order key."""
    if not input_path.exists():
        raise ValueError(f"Input file does not exist: {input_path}")
    try:
        data = pd.read_csv(input_path)
    except Exception as exc:
        raise ValueError(f"Could not read input CSV {input_path}: {exc}") from exc

    required = [columns.time, columns.replicate, columns.measurement, columns.canopy]
    missing_columns = [name for name in required if name not in data.columns]
    if missing_columns:
        raise ValueError(
            "Input CSV is missing required column(s): " + ", ".join(missing_columns)
        )

    measurement = pd.to_numeric(data[columns.measurement], errors="coerce")
    canopy = pd.to_numeric(data[columns.canopy], errors="coerce")
    reasons: dict[str, pd.Series] = {
        "missing timepoint": data[columns.time].isna(),
        "missing replicate identifier": data[columns.replicate].isna(),
        "missing or non-numeric measurement": measurement.isna(),
        "non-finite measurement": measurement.notna() & ~np.isfinite(measurement),
        "missing or non-numeric canopy size": canopy.isna(),
        "non-finite canopy size": canopy.notna() & ~np.isfinite(canopy),
    }
    invalid = pd.Series(False, index=data.index)
    reason_counts: dict[str, int] = {}
    for name, mask in reasons.items():
        count = int(mask.sum())
        reason_counts[name] = count
        invalid |= mask
        if count:
            print(f"WARNING: {count} row(s) have {name}.", file=sys.stderr)

    required_unique = list(dict.fromkeys(required))
    valid = data.loc[~invalid, required_unique].copy()
    valid[columns.measurement] = measurement.loc[~invalid].astype(float)
    valid[columns.canopy] = canopy.loc[~invalid].astype(float)
    if valid.empty:
        raise ValueError("No valid replicate rows remain after validation.")

    time_key, ordering_method = _ordering_key(valid[columns.time])
    valid["_time_order_key"] = time_key.to_numpy()
    valid["_row_order"] = np.arange(len(valid))
    valid = valid.sort_values(
        ["_time_order_key", "_row_order"], kind="stable"
    ).reset_index(drop=True)

    report = ValidationReport(
        total_rows=len(data),
        valid_rows=len(valid),
        reason_counts=reason_counts,
        ordering_method=ordering_method,
    )
    if report.excluded_rows:
        print(
            f"WARNING: excluded {report.excluded_rows} of {report.total_rows} input "
            "row(s). A row may be represented in more than one reason count.",
            file=sys.stderr,
        )
    return valid, report


def calculate_timepoint_statistics(
    data: pd.DataFrame, columns: Columns
) -> pd.DataFrame:
    """Calculate replicate summaries for each timepoint in chronological order."""
    records: list[dict[str, Any]] = []
    for order, (timepoint, group) in enumerate(
        data.groupby(columns.time, sort=False, dropna=False)
    ):
        measurements = group[columns.measurement]
        n = int(measurements.count())
        sd = float(measurements.std(ddof=1)) if n >= 2 else np.nan
        mean = float(measurements.mean())
        if n < 2:
            print(
                f"WARNING: timepoint {timepoint!r} has {n} valid replicate(s); "
                "standard deviation and variance are unavailable.",
                file=sys.stderr,
            )
        records.append(
            {
                columns.time: timepoint,
                "number_of_valid_replicates": n,
                "mean_measurement": mean,
                "median_measurement": float(measurements.median()),
                "replicate_standard_deviation": sd,
                "replicate_variance": sd**2 if np.isfinite(sd) else np.nan,
                "standard_error": sd / np.sqrt(n) if np.isfinite(sd) else np.nan,
                "coefficient_of_variation": (
                    sd / mean if np.isfinite(sd) and mean != 0 else np.nan
                ),
                "mean_canopy_size": float(group[columns.canopy].mean()),
                "_time_order": order,
            }
        )
    return pd.DataFrame.from_records(records)


def fit_noise_model(
    statistics: pd.DataFrame,
) -> tuple[Any, pd.DataFrame]:
    """Fit log(sd) = alpha + p*log(canopy size) and create predictions."""
    n_ok = statistics["number_of_valid_replicates"] >= 2
    canopy_ok = (
        np.isfinite(statistics["mean_canopy_size"])
        & (statistics["mean_canopy_size"] > 0)
    )
    sd_ok = (
        np.isfinite(statistics["replicate_standard_deviation"])
        & (statistics["replicate_standard_deviation"] > 0)
    )
    included = n_ok & canopy_ok & sd_ok
    if int(included.sum()) < 2:
        raise ValueError(
            "At least two timepoints with >=2 valid replicates, positive mean canopy "
            "size, and positive replicate standard deviation are required to fit "
            f"the noise model; found {int(included.sum())}."
        )

    fit_data = statistics.loc[included]
    x = sm.add_constant(np.log(fit_data["mean_canopy_size"]), has_constant="add")
    result = sm.OLS(np.log(fit_data["replicate_standard_deviation"]), x).fit()

    predictions = statistics.copy()
    predictions["included_in_noise_model"] = included

    def exclusion_reason(index: int) -> str:
        reasons = []
        if not n_ok.loc[index]:
            reasons.append("fewer than two valid replicates")
        if not canopy_ok.loc[index]:
            reasons.append("mean canopy size is not finite and positive")
        if not sd_ok.loc[index]:
            reasons.append("replicate standard deviation is not finite and positive")
        return "; ".join(reasons)

    predictions["noise_model_exclusion_reason"] = [
        "" if included.loc[i] else exclusion_reason(i) for i in predictions.index
    ]
    alpha, exponent = (float(result.params.iloc[0]), float(result.params.iloc[1]))
    positive_canopy = canopy_ok
    predictions["predicted_replicate_standard_deviation"] = np.nan
    predictions.loc[positive_canopy, "predicted_replicate_standard_deviation"] = (
        np.exp(alpha)
        * predictions.loc[positive_canopy, "mean_canopy_size"].pow(exponent)
    )
    return result, predictions


def calculate_successive_changes(
    predictions: pd.DataFrame, time_column: str
) -> pd.DataFrame:
    """Calculate raw and noise-standardized changes between adjacent timepoints."""
    records: list[dict[str, Any]] = []
    parsed_times = _datetime_values(predictions[time_column])
    for index in range(len(predictions) - 1):
        start = predictions.iloc[index]
        end = predictions.iloc[index + 1]
        difference = float(end["mean_measurement"] - start["mean_measurement"])
        start_sd = float(start["predicted_replicate_standard_deviation"])
        end_sd = float(end["predicted_replicate_standard_deviation"])
        variance = (
            start_sd**2 / float(start["number_of_valid_replicates"])
            + end_sd**2 / float(end["number_of_valid_replicates"])
        )
        expected_sd = np.sqrt(variance) if np.isfinite(variance) and variance > 0 else np.nan
        elapsed_hours = (
            (parsed_times.iloc[index + 1] - parsed_times.iloc[index]).total_seconds()
            / 3600
            if pd.notna(parsed_times.iloc[index])
            and pd.notna(parsed_times.iloc[index + 1])
            else np.nan
        )
        if not np.isfinite(elapsed_hours) or elapsed_hours < 0:
            interval_class = "unknown"
        elif elapsed_hours < 5 / 60:
            interval_class = "technical replicate (<5 min)"
        elif elapsed_hours <= 2:
            interval_class = "within-day (5 min–2 h)"
        else:
            interval_class = "overnight (>2 h)"
        records.append(
            {
                "starting_timepoint": start[time_column],
                "ending_timepoint": end[time_column],
                "starting_mean": start["mean_measurement"],
                "ending_mean": end["mean_measurement"],
                "raw_difference": difference,
                "absolute_difference": abs(difference),
                "relative_difference": (
                    difference / float(start["mean_measurement"])
                    if start["mean_measurement"] != 0
                    else np.nan
                ),
                "elapsed_hours": elapsed_hours,
                "interval_class": interval_class,
                "predicted_standard_deviation_at_starting_timepoint": start_sd,
                "predicted_standard_deviation_at_ending_timepoint": end_sd,
                "expected_standard_deviation_of_the_difference": expected_sd,
                "standardized_difference_z": (
                    difference / expected_sd if np.isfinite(expected_sd) else np.nan
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def _save_figure(figure: plt.Figure, output_dir: Path, stem: str) -> None:
    """Save a Matplotlib figure as PNG and PDF."""
    figure.tight_layout()
    for suffix in ("png", "pdf"):
        figure.savefig(output_dir / f"{stem}.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(figure)


def _display_ticks(length: int, maximum: int = 20) -> np.ndarray:
    """Choose readable, evenly spaced categorical tick positions."""
    if length <= maximum:
        return np.arange(length)
    return np.unique(np.linspace(0, length - 1, maximum, dtype=int))


def _concise_time_labels(values: pd.Series) -> pd.Series:
    """Shorten datetime-like or timestamp-bearing timepoint labels for plots."""
    text = values.astype(str)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(text, errors="coerce")
    if parsed.isna().any():
        embedded = text.str.extract(
            r"(?P<date>\d{8})[_T-]?(?P<time>\d{6})", expand=True
        )
        parsed = pd.to_datetime(
            embedded["date"] + embedded["time"],
            format="%Y%m%d%H%M%S",
            errors="coerce",
        )
    if parsed.notna().all():
        return parsed.dt.strftime("%m-%d\n%H:%M")
    return text.str.replace(r"\.[^.]+$", "", regex=True).str.slice(0, 20)


def create_plots(
    data: pd.DataFrame,
    predictions: pd.DataFrame,
    changes: pd.DataFrame,
    model: Any,
    columns: Columns,
    output_dir: Path,
) -> None:
    """Create the three requested diagnostic plots."""
    plant_replicates = columns.replicate.strip().lower() in {
        "plant",
        "plant_id",
        "plantid",
    }
    standard_deviation_label = (
        "Between-plant standard deviation"
        if plant_replicates
        else "Replicate standard deviation"
    )
    standard_deviation_band_label = (
        "± one between-plant SD"
        if plant_replicates
        else "± one replicate SD"
    )
    usable = predictions["included_in_noise_model"]
    figure, axis = plt.subplots(figsize=(7, 5))
    axis.scatter(
        predictions.loc[usable, "mean_canopy_size"],
        predictions.loc[usable, "replicate_standard_deviation"],
        alpha=0.35,
        edgecolors="none",
        label="Included timepoints",
    )
    excluded_plot = (
        ~usable
        & (predictions["mean_canopy_size"] > 0)
        & (predictions["replicate_standard_deviation"] > 0)
    )
    if excluded_plot.any():
        axis.scatter(
            predictions.loc[excluded_plot, "mean_canopy_size"],
            predictions.loc[excluded_plot, "replicate_standard_deviation"],
            marker="x",
            alpha=0.5,
            label="Excluded timepoints",
        )
    minimum = float(predictions.loc[usable, "mean_canopy_size"].min())
    maximum = float(predictions.loc[usable, "mean_canopy_size"].max())
    grid = (
        np.geomspace(minimum, maximum, 200)
        if minimum < maximum
        else np.array([minimum * 0.9, maximum * 1.1])
    )
    alpha, exponent = float(model.params.iloc[0]), float(model.params.iloc[1])
    axis.plot(
        grid,
        np.exp(alpha) * grid**exponent,
        color="tab:orange",
        linewidth=2.5,
        label="Fitted noise model",
    )
    axis.set(xscale="log", yscale="log", xlabel="Mean canopy size",
             ylabel=standard_deviation_label)
    axis.legend()
    _save_figure(figure, output_dir, "noise_vs_canopy_size")

    x = np.arange(len(predictions))
    labels = _concise_time_labels(predictions[columns.time])
    figure, axis = plt.subplots(figsize=(12, 5))
    means = predictions["mean_measurement"].to_numpy(dtype=float)
    standard_deviations = predictions["replicate_standard_deviation"].to_numpy(
        dtype=float
    )
    if len(predictions) > 100:
        axis.fill_between(
            x,
            means - standard_deviations,
            means + standard_deviations,
            color="tab:blue",
            alpha=0.18,
            linewidth=0,
            label=standard_deviation_band_label,
        )
        axis.plot(x, means, color="tab:blue", linewidth=1.25, label="Timepoint mean")
    else:
        axis.errorbar(
            x,
            means,
            yerr=standard_deviations,
            fmt="o-",
            capsize=3,
            label=(
                "Mean ± between-plant SD"
                if plant_replicates
                else "Mean ± replicate SD"
            ),
        )
        time_positions = dict(zip(predictions[columns.time].astype(str), x))
        replicate_x = data[columns.time].astype(str).map(time_positions)
        axis.scatter(
            replicate_x,
            data[columns.measurement],
            alpha=0.25,
            s=16,
            label="Replicate observations",
        )
    axis.set(xlabel="Timepoint", ylabel="Measurement")
    ticks = _display_ticks(len(x), maximum=12)
    axis.set_xticks(ticks, labels.iloc[ticks], rotation=45, ha="right")
    axis.legend()
    _save_figure(figure, output_dir, "measurement_over_time")

    interval_styles = [
        ("technical replicate (<5 min)", "tab:blue"),
        ("within-day (5 min–2 h)", "tab:green"),
        ("overnight (>2 h)", "tab:orange"),
        ("unknown", "tab:gray"),
    ]
    ending_datetimes = _datetime_values(changes["ending_timepoint"])
    available = [
        (label, color)
        for label, color in interval_styles
        if (changes["interval_class"] == label).any()
    ]
    if not available:
        available = [("unknown", "tab:gray")]
    figure, axes = plt.subplots(
        len(available),
        1,
        figsize=(12, 2.7 * len(available) + 1),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    for axis, (label, color) in zip(axes[:, 0], available):
        selected = changes["interval_class"] == label
        x_values = ending_datetimes.loc[selected]
        if x_values.isna().all():
            x_values = changes.index[selected]
        z_values = changes.loc[selected, "standardized_difference_z"]
        axis.vlines(x_values, 0, z_values, color=color, alpha=0.55, linewidth=0.8)
        axis.scatter(x_values, z_values, color=color, s=18, alpha=0.8)
        for reference, style in ((0, "-"), (-1.96, "--"), (1.96, "--")):
            axis.axhline(reference, color="black", linestyle=style, linewidth=1)
        display_label = label[:1].upper() + label[1:]
        axis.set_title(
            f"{display_label} (n={int(selected.sum())})",
            loc="left",
            fontsize=10,
        )
    if ending_datetimes.notna().all():
        locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
        axes[-1, 0].xaxis.set_major_locator(locator)
        axes[-1, 0].xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(locator)
        )
    axes[-1, 0].set_xlabel("Ending timepoint")
    figure.supylabel("Standardized difference z", x=0.01)
    _save_figure(figure, output_dir, "standardized_successive_changes")


def _format_metric(value: float) -> str:
    """Format a numeric summary value, including missing values."""
    return "NA" if not np.isfinite(value) else f"{value:.10g}"


def write_model_summary(
    path: Path, model: Any, predictions: pd.DataFrame
) -> None:
    """Write the requested canopy-size noise-model summary."""
    included = predictions["included_in_noise_model"]
    lines = [
        "Canopy-size-dependent replicate noise model",
        "Model: log(s_t) = alpha + p log(S_t)",
        "",
        f"intercept alpha: {_format_metric(float(model.params.iloc[0]))}",
        f"scaling exponent p: {_format_metric(float(model.params.iloc[1]))}",
        f"R-squared: {_format_metric(float(model.rsquared))}",
        f"number of timepoints used: {int(included.sum())}",
        "minimum canopy size used: "
        + _format_metric(float(predictions.loc[included, "mean_canopy_size"].min())),
        "maximum canopy size used: "
        + _format_metric(float(predictions.loc[included, "mean_canopy_size"].max())),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def calculate_summary_metrics(
    predictions: pd.DataFrame, changes: pd.DataFrame
) -> dict[str, float | int]:
    """Calculate temporal and within-timepoint summary metrics."""
    within_sd = predictions["replicate_standard_deviation"].dropna()
    differences = changes["raw_difference"].dropna()
    z = changes["standardized_difference_z"].dropna()
    metrics: dict[str, float | int] = {
        "rmssd": float(np.sqrt(np.mean(differences**2))) if len(differences) else np.nan,
        "masd": float(np.mean(np.abs(differences))) if len(differences) else np.nan,
        "rmsz": float(np.sqrt(np.mean(z**2))) if len(z) else np.nan,
        "median_within_sd": float(within_sd.median()) if len(within_sd) else np.nan,
        "mean_within_sd": float(within_sd.mean()) if len(within_sd) else np.nan,
        "usable_timepoints": int(predictions["included_in_noise_model"].sum()),
        "successive_comparisons": int(len(changes)),
        "standardized_comparisons": int(len(z)),
        "fraction_abs_z_gt_1": float((np.abs(z) > 1).mean()) if len(z) else np.nan,
        "fraction_abs_z_gt_1_96": (
            float((np.abs(z) > 1.96).mean()) if len(z) else np.nan
        ),
    }
    interval_names = {
        "technical": "technical replicate (<5 min)",
        "within_day": "within-day (5 min–2 h)",
        "overnight": "overnight (>2 h)",
    }
    for key, label in interval_names.items():
        interval_z = changes.loc[
            changes["interval_class"] == label, "standardized_difference_z"
        ].dropna()
        metrics[f"{key}_comparisons"] = int(len(interval_z))
        metrics[f"{key}_rmsz"] = (
            float(np.sqrt(np.mean(interval_z**2))) if len(interval_z) else np.nan
        )
    return metrics


def write_summary(
    path: Path,
    args: argparse.Namespace,
    columns: Columns,
    report: ValidationReport,
    metrics: dict[str, float | int],
) -> None:
    """Write settings, validation counts, metrics, and cautious interpretation."""
    reason_lines = [
        f"  {reason}: {count}" for reason, count in report.reason_counts.items()
    ]
    lines = [
        "Noise analysis summary",
        "",
        "Command-line settings",
        f"input: {args.input.resolve()}",
        f"output directory: {args.output_dir.resolve()}",
        f"time column: {columns.time}",
        f"replicate column: {columns.replicate}",
        f"measurement column: {columns.measurement}",
        f"canopy column: {columns.canopy}",
        "",
        "Input validation",
        f"total input rows: {report.total_rows}",
        f"valid rows: {report.valid_rows}",
        f"excluded rows: {report.excluded_rows}",
        f"timepoint ordering: {report.ordering_method}",
        "row issue counts (a row can have multiple issues):",
        *reason_lines,
        "",
        "Temporal variation",
        f"RMSSD: {_format_metric(float(metrics['rmssd']))}",
        f"MASD: {_format_metric(float(metrics['masd']))}",
        f"RMSZ: {_format_metric(float(metrics['rmsz']))}",
        "median within-timepoint standard deviation: "
        + _format_metric(float(metrics["median_within_sd"])),
        "mean within-timepoint standard deviation: "
        + _format_metric(float(metrics["mean_within_sd"])),
        f"number of usable timepoints: {metrics['usable_timepoints']}",
        f"number of successive comparisons: {metrics['successive_comparisons']}",
        "number of successive comparisons with defined z: "
        f"{metrics['standardized_comparisons']}",
        "fraction of successive changes with abs(z) > 1: "
        + _format_metric(float(metrics["fraction_abs_z_gt_1"])),
        "fraction of successive changes with abs(z) > 1.96: "
        + _format_metric(float(metrics["fraction_abs_z_gt_1_96"])),
        "",
        "Variation by elapsed-time class",
        "technical replicates (<5 min): "
        f"{metrics['technical_comparisons']} comparisons; RMSZ "
        + _format_metric(float(metrics["technical_rmsz"])),
        "within-day changes (5 min–2 h): "
        f"{metrics['within_day_comparisons']} comparisons; RMSZ "
        + _format_metric(float(metrics["within_day_rmsz"])),
        "overnight changes (>2 h): "
        f"{metrics['overnight_comparisons']} comparisons; RMSZ "
        + _format_metric(float(metrics["overnight_rmsz"])),
        "",
        "Interpretation",
        "z is a descriptive measure of how large an observed successive change is "
        "relative to expected measurement noise; it is not presented as a formal "
        "hypothesis test.",
        "RMSZ near 1 suggests successive changes are broadly similar in magnitude "
        "to expected measurement noise. RMSZ substantially above 1 suggests "
        "additional temporal variation, drift, or an inadequate noise model. RMSZ "
        "below 1 may indicate conservative noise estimates or correlation between "
        "measurements.",
        "Adjacent standardized differences should not be treated as independent, "
        "because consecutive differences share a timepoint.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the complete command-line analysis."""
    args = parse_args(argv)
    columns = Columns(
        args.time_column,
        args.replicate_column,
        args.measurement_column,
        args.canopy_column,
    )
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == input_path or (
        output_dir.exists() and output_dir.is_file()
    ):
        raise ValueError(f"Output directory path is a file: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = {
        output_dir / "timepoint_statistics.csv",
        output_dir / "noise_model_predictions.csv",
        output_dir / "noise_model_summary.txt",
        output_dir / "successive_timepoint_changes.csv",
        output_dir / "noise_analysis_summary.txt",
    }
    if input_path in output_files:
        raise ValueError("Refusing to overwrite the input file with an output file.")

    data, report = load_and_validate_data(input_path, columns)
    statistics = calculate_timepoint_statistics(data, columns)
    model, predictions = fit_noise_model(statistics)
    changes = calculate_successive_changes(predictions, columns.time)
    metrics = calculate_summary_metrics(predictions, changes)

    statistics.drop(columns="_time_order").to_csv(
        output_dir / "timepoint_statistics.csv", index=False
    )
    predictions.drop(columns="_time_order").to_csv(
        output_dir / "noise_model_predictions.csv", index=False
    )
    changes.to_csv(output_dir / "successive_timepoint_changes.csv", index=False)
    write_model_summary(output_dir / "noise_model_summary.txt", model, predictions)
    write_summary(
        output_dir / "noise_analysis_summary.txt",
        args,
        columns,
        report,
        metrics,
    )
    create_plots(data, predictions, changes, model, columns, output_dir)

    included = predictions["included_in_noise_model"]
    print(f"number of timepoints: {len(predictions)}")
    print(f"number of usable noise estimates: {int(included.sum())}")
    print(
        "canopy-size range: "
        f"{_format_metric(float(predictions.loc[included, 'mean_canopy_size'].min()))} "
        "to "
        f"{_format_metric(float(predictions.loc[included, 'mean_canopy_size'].max()))}"
    )
    print(
        "estimated noise-scaling exponent: "
        f"{_format_metric(float(model.params.iloc[1]))}"
    )
    print(
        "median within-timepoint standard deviation: "
        f"{_format_metric(float(metrics['median_within_sd']))}"
    )
    print(f"RMSSD: {_format_metric(float(metrics['rmssd']))}")
    print(f"RMSZ: {_format_metric(float(metrics['rmsz']))}")
    print(f"output directory: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
