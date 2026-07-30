import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
import logging
import tempfile

import cv2
import pandas as pd
from plantcv import plantcv as pcv  # type: ignore[import-not-found]
from .config import AnalysisConfig
from .image_preprocessing import (
    load_and_rotate_image,
    segment_plants,
)
from .measurements import (
    configure_plantcv,
    analyze_shape,
    observations_to_dataframe,
    add_metric_units
)
from .roi import RoiDefinition, detect_roi_definition


@dataclass(frozen=True)
class ImageAnalysisResult:
    """Outputs produced by one completed image analysis."""

    image_path: Path
    traits_path: Path
    overlay_path: Path
    config_fingerprint: str
    traits: pd.DataFrame


def setup_logging(verbose: bool = False) -> None:
    root_level = logging.INFO
    script_level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=root_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging.getLogger(__name__).setLevel(script_level)


def _analyze_image_worker(
    image_path: Path,
    output_dir: Path,
    cfg: AnalysisConfig,
    roi_definition: RoiDefinition,
) -> pd.DataFrame:
    result = analyze_image(image_path, output_dir, cfg, roi_definition)
    traits = result.traits.copy()
    traits.insert(0, "image", image_path.name)
    return traits


def analyze_image(
    image_path: Path,
    output_dir: Path,
    cfg: AnalysisConfig,
    roi_definition: RoiDefinition | None = None,
) -> ImageAnalysisResult:
    logger = logging.getLogger(__name__)

    if not image_path.is_file():
        raise ValueError(f"Image does not exist or is not a file: {image_path}")

    logger.info("Starting analysis: %s", image_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_plantcv(cfg, output_dir)

    logger.debug("Clearing previous PlantCV outputs")
    pcv.outputs.clear()

    logger.info(
        f"Reading "
        f"{'and rotating ' if cfg.rotate_angle != 0.0 else ''}"
        f"image: {image_path}"
    )
    img = load_and_rotate_image(image_path, cfg.rotate_angle)

    logger.info("Visualizing colorspaces")
    pcv.visualize.colorspaces(rgb_img=img, original_img=False)

    logger.info("Segmenting plants")
    mask = segment_plants(img, cfg)

    if roi_definition is None:
        logger.info("Calibrating ROI grid with PlantCV")
        roi_definition = detect_roi_definition(img, mask, cfg)
    _validate_roi_definition(roi_definition, cfg)
    labeled_mask, num_plants = roi_definition.labeled_mask(mask)
    logger.info("Detected %d plant labels", num_plants)

    stem = image_path.stem
    overlay_path = output_dir / f"{stem}_roi_overlay.png"

    logger.info("Saving ROI overlay")
    with tempfile.NamedTemporaryFile(
        prefix=f".{stem}_roi_overlay.",
        suffix=".png",
        dir=output_dir,
        delete=False,
    ) as temporary_overlay:
        temporary_overlay_path = Path(temporary_overlay.name)
    temporary_csv_path: Path | None = None
    try:
        overlay = roi_definition.draw_overlay(img)
        if not cv2.imwrite(
            str(temporary_overlay_path),
            cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR),
        ):
            raise ValueError("The ROI overlay could not be written.")

        logger.info("Measuring plant shape traits")
        analyze_shape(img, labeled_mask, num_plants)
        df = observations_to_dataframe()
        df = add_metric_units(df, cfg)

        csv_path = output_dir / f"{stem}_traits.csv"
        logger.info("Writing traits CSV: %s", csv_path)
        with tempfile.NamedTemporaryFile(
            prefix=f".{stem}_traits.",
            suffix=".csv",
            dir=output_dir,
            delete=False,
        ) as temporary_csv:
            temporary_csv_path = Path(temporary_csv.name)
        df.to_csv(temporary_csv_path, index=False)

        temporary_overlay_path.replace(overlay_path)
        temporary_csv_path.replace(csv_path)
    except BaseException:
        temporary_overlay_path.unlink(missing_ok=True)
        if temporary_csv_path is not None:
            temporary_csv_path.unlink(missing_ok=True)
        raise

    logger.info("Finished analysis: %s", image_path)

    return ImageAnalysisResult(
        image_path=image_path,
        traits_path=csv_path,
        overlay_path=overlay_path,
        config_fingerprint=cfg.fingerprint,
        traits=df,
    )


def analyze_images(
    image_paths: list[Path],
    output_dir: Path,
    cfg: AnalysisConfig,
    n_workers: int | None = None,
    roi_definition: RoiDefinition | None = None,
) -> pd.DataFrame:
    logger = logging.getLogger(__name__)
    all_results: list[pd.DataFrame] = []

    if not image_paths:
        raise ValueError("No images were provided for analysis.")

    output_dir.mkdir(parents=True, exist_ok=True)
    roi_path = output_dir / "roi-definition.json"
    if roi_definition is not None:
        logger.info("Using explicitly calibrated reusable ROI grid")
        _validate_roi_definition(roi_definition, cfg)
        roi_definition.save(roi_path)
    elif roi_path.exists():
        logger.info("Loading reusable ROI grid: %s", roi_path)
        roi_definition = RoiDefinition.load(roi_path)
        _validate_roi_definition(roi_definition, cfg)
    else:
        logger.info("Calibrating reusable ROI grid from %s", image_paths[0])
        roi_definition = calibrate_roi(image_paths[0], cfg)
        roi_definition.save(roi_path)

    logger.info(f"Starting batch analysis for {len(image_paths)} image(s)")
    logger.info(f"Using {n_workers} worker(s)")

    if n_workers and n_workers <= 1:
        for i, image_path in enumerate(image_paths, start=1):
            logger.info(
                f"Processing image {i}/{len(image_paths)}: {image_path}"
            )
            df = _analyze_image_worker(
                image_path, output_dir, cfg, roi_definition
            )
            all_results.append(df)

    else:
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    _analyze_image_worker,
                    image_path,
                    output_dir,
                    cfg,
                    roi_definition,
                ): image_path
                for image_path in image_paths
            }

            for i, future in enumerate(as_completed(futures), start=1):
                image_path = futures[future]

                try:
                    df = future.result()
                except Exception:
                    logger.exception("Failed to analyze image: %s", image_path)
                    raise

                logger.info(
                    "Finished image %d/%d: %s", i, len(image_paths), image_path
                )
                all_results.append(df)

    combined = pd.concat(all_results, ignore_index=True)
    combined_path = output_dir / "combined_traits.csv"

    logger.info("Writing combined results: %s", combined_path)
    combined.to_csv(combined_path, index=False)

    logger.info("Batch analysis complete")
    return combined


def calibrate_roi(image_path: Path, cfg: AnalysisConfig) -> RoiDefinition:
    if not image_path.is_file():
        raise ValueError(f"Image does not exist or is not a file: {image_path}")
    image = load_and_rotate_image(image_path, cfg.rotate_angle)
    mask = segment_plants(image, cfg)
    return detect_roi_definition(image, mask, cfg)


def _validate_roi_definition(
    definition: RoiDefinition, cfg: AnalysisConfig
) -> None:
    if definition.rows != cfg.roi_rows or definition.columns != cfg.roi_cols:
        raise ValueError(
            "The saved ROI grid dimensions do not match the analysis settings."
        )
    if definition.config_fingerprint != cfg.fingerprint:
        raise ValueError(
            "The saved ROI definition was calibrated with different settings."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze Arabidopsis canopy area from top-view images."
    )

    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="Input image path(s).",
    )

    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("results"),
        help="Output directory.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed debug logging.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=((n - 2) if (n := os.cpu_count()) is not None else 1),
        help="Number of parallel worker processes (default: cores - 2).",
    )

    parser.add_argument(
        "--sepchannel",
        choices=["l", "a", "b"],
        default="a",
        help=(
            "LAB channel to use: l=lightness, a=green-magenta, "
            "b=blue-yellow."
        ),
    )

    parser.add_argument("--rotate-angle", type=float, default=0.0)
    parser.add_argument("--threshold", type=int, default=145)
    parser.add_argument("--fill-size", type=int, default=200)
    parser.add_argument(
        "--frame-source",
        choices=["pot-grid", "plant-mask"],
        default="pot-grid",
        help="How to choose the automatic analysis frame.",
    )
    parser.add_argument(
        "--pot-frame-padding-x",
        type=int,
        default=0,
        help="Horizontal padding around pot-grid ROI bounds.",
    )
    parser.add_argument(
        "--pot-frame-padding-y",
        type=int,
        default=0,
        help="Vertical padding around pot-grid ROI bounds.",
    )
    parser.add_argument(
        "--grid-x",
        type=int,
        default=None,
        help="Manual ROI left edge in pixels on the rotated image.",
    )
    parser.add_argument(
        "--grid-y",
        type=int,
        default=None,
        help="Manual ROI top edge in pixels on the rotated image.",
    )
    parser.add_argument(
        "--grid-width",
        type=int,
        default=None,
        help="Manual ROI width in pixels on the rotated image.",
    )
    parser.add_argument(
        "--grid-height",
        type=int,
        default=None,
        help="Manual ROI height in pixels on the rotated image.",
    )
    parser.add_argument("--roi-rows", type=int, default=5)
    parser.add_argument("--roi-cols", type=int, default=9)
    parser.add_argument("--grid-margin-x", type=int, default=0)
    parser.add_argument("--grid-margin-y", type=int, default=0)
    parser.add_argument("--grid-cell-padding-x", type=int, default=0)
    parser.add_argument("--grid-cell-padding-y", type=int, default=0)
    parser.add_argument("--min-component-area", type=int, default=50)
    parser.add_argument("--pot-diameter-cm", type=float, default=5.0)
    parser.add_argument("--pot-diameter-px", type=float, default=250.0)
    parser.add_argument("--debug", default=None)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("Starting canopy analysis workflow")
    logger.info("Output directory: %s", args.outdir)

    cfg = AnalysisConfig(
        rotate_angle=args.rotate_angle,
        sepchannel=args.sepchannel,
        threshold=args.threshold,
        fill_size=args.fill_size,
        frame_source=args.frame_source,
        pot_frame_padding_x=args.pot_frame_padding_x,
        pot_frame_padding_y=args.pot_frame_padding_y,
        grid_x=args.grid_x,
        grid_y=args.grid_y,
        grid_width=args.grid_width,
        grid_height=args.grid_height,
        roi_rows=args.roi_rows,
        roi_cols=args.roi_cols,
        grid_margin_x=args.grid_margin_x,
        grid_margin_y=args.grid_margin_y,
        grid_cell_padding_x=args.grid_cell_padding_x,
        grid_cell_padding_y=args.grid_cell_padding_y,
        min_component_area=args.min_component_area,
        pot_diameter_cm=args.pot_diameter_cm,
        pot_diameter_px=args.pot_diameter_px,
        debug=args.debug,
    )
    args.outdir.mkdir(parents=True, exist_ok=True)

    config_path = args.outdir / "analysis_config.json"
    logger.info("Writing analysis config: %s", config_path)

    cfg.save(config_path)

    logger.info(f"Using {args.workers} workers")

    analyze_images(args.images, args.outdir, cfg, args.workers)
    logger.info("Workflow finished successfully")


if __name__ == "__main__":
    main()
