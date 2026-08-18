from __future__ import annotations

import argparse
from pathlib import Path

from scripts.analysis.analyze_canopy import analyze_image, setup_logging
from scripts.analysis.config import AnalysisConfig
from scripts.analysis.roi import RoiDefinition


def analyze_run_image(image_path: Path, analysis_dir: Path) -> None:
    """Analyze one capture with the immutable calibration stored for its run."""
    config = AnalysisConfig.load(analysis_dir / "analysis-config.json")
    roi = RoiDefinition.load(analysis_dir / "roi-definition.json")
    analyze_image(image_path, analysis_dir / "results", config, roi)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze one experiment capture using its saved calibration."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    args = parser.parse_args()
    setup_logging()
    analyze_run_image(args.image, args.analysis_dir)


if __name__ == "__main__":
    main()
