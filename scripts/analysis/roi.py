from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .config import AnalysisConfig


@dataclass(frozen=True)
class RoiCircle:
    row: int
    column: int
    center_x: float
    center_y: float
    radius: float


@dataclass(frozen=True)
class AnalysisCrop:
    """Normalized analysis-area bounds in the rotated source image."""

    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Analysis area must use finite coordinates.")
        if (
            self.x < 0
            or self.y < 0
            or self.width <= 0
            or self.height <= 0
            or self.x + self.width > 1.000001
            or self.y + self.height > 1.000001
        ):
            raise ValueError("Analysis area must fit within the image.")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnalysisCrop:
        try:
            return cls(
                x=float(value["x"]),
                y=float(value["y"]),
                width=float(value["width"]),
                height=float(value["height"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Analysis area is invalid.") from exc

    def pixel_bounds(
        self, image_shape: tuple[int, ...]
    ) -> tuple[int, int, int, int]:
        image_height, image_width = image_shape[:2]
        x0 = min(image_width - 1, round(self.x * image_width))
        y0 = min(image_height - 1, round(self.y * image_height))
        x1 = min(
            image_width, max(x0 + 1, round((self.x + self.width) * image_width))
        )
        y1 = min(
            image_height,
            max(y0 + 1, round((self.y + self.height) * image_height)),
        )
        return x0, y0, x1, y1


@dataclass(frozen=True)
class RoiDefinition:
    """A resolution-independent ROI grid calibrated from one run image."""

    schema_version: int
    rows: int
    columns: int
    source_width: int
    source_height: int
    config_fingerprint: str
    circles: tuple[RoiCircle, ...]
    analysis_crop: AnalysisCrop = AnalysisCrop()

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2}:
            raise ValueError("Unsupported ROI definition version.")
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("ROI rows and columns must be positive.")
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError("ROI source dimensions must be positive.")
        if len(self.circles) != self.rows * self.columns:
            raise ValueError("ROI definition does not contain the expected grid.")
        for circle in self.circles:
            if not (
                0 <= circle.row < self.rows
                and 0 <= circle.column < self.columns
                and 0 <= circle.center_x <= 1
                and 0 <= circle.center_y <= 1
                and 0 < circle.radius <= 1
                and all(
                    math.isfinite(value)
                    for value in (
                        circle.center_x,
                        circle.center_y,
                        circle.radius,
                    )
                )
            ):
                raise ValueError("ROI definition contains an invalid circle.")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rows": self.rows,
            "columns": self.columns,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "config_fingerprint": self.config_fingerprint,
            "circles": [asdict(circle) for circle in self.circles],
            "analysis_crop": asdict(self.analysis_crop),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RoiDefinition:
        try:
            circles = tuple(
                RoiCircle(
                    row=int(circle["row"]),
                    column=int(circle["column"]),
                    center_x=float(circle["center_x"]),
                    center_y=float(circle["center_y"]),
                    radius=float(circle["radius"]),
                )
                for circle in value["circles"]
            )
            return cls(
                schema_version=int(value["schema_version"]),
                rows=int(value["rows"]),
                columns=int(value["columns"]),
                source_width=int(value["source_width"]),
                source_height=int(value["source_height"]),
                config_fingerprint=str(value["config_fingerprint"]),
                circles=circles,
                analysis_crop=AnalysisCrop.from_dict(
                    value.get(
                        "analysis_crop",
                        {"x": 0, "y": 0, "width": 1, "height": 1},
                    )
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("ROI definition is invalid.") from exc

    def save(self, path: Path) -> None:
        from scripts.scheduling.make_schedule import atomic_write_text

        atomic_write_text(
            path, json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        )

    @classmethod
    def load(cls, path: Path) -> RoiDefinition:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("ROI definition could not be read.") from exc
        if not isinstance(value, dict):
            raise ValueError("ROI definition must be a JSON object.")
        return cls.from_dict(value)

    def pixel_circles(
        self, image_shape: tuple[int, ...]
    ) -> list[tuple[int, int, int]]:
        height, width = image_shape[:2]
        radius_scale = min(width, height)
        return [
            (
                round(circle.center_x * width),
                round(circle.center_y * height),
                max(1, round(circle.radius * radius_scale)),
            )
            for circle in self.circles
        ]

    def labeled_mask(self, mask: np.ndarray) -> tuple[np.ndarray, int]:
        labels = np.zeros(mask.shape[:2], dtype=np.int32)
        for label_id, (center_x, center_y, radius) in enumerate(
            self.pixel_circles(mask.shape), start=1
        ):
            roi_mask = np.zeros(mask.shape[:2], dtype=np.uint8)
            cv2.circle(
                roi_mask, (center_x, center_y), radius, 255, thickness=-1
            )
            labels[(roi_mask > 0) & (mask > 0)] = label_id
        return labels, len(self.circles)

    def draw_overlay(self, image: np.ndarray) -> np.ndarray:
        overlay = image.copy()
        crop_x0, crop_y0, crop_x1, crop_y1 = self.analysis_crop.pixel_bounds(
            image.shape
        )
        cv2.rectangle(
            overlay,
            (crop_x0, crop_y0),
            (crop_x1 - 1, crop_y1 - 1),
            (255, 255, 255),
            max(2, round(min(image.shape[:2]) / 600)),
        )
        for label_id, (center_x, center_y, radius) in enumerate(
            self.pixel_circles(image.shape), start=1
        ):
            cv2.circle(
                overlay,
                (center_x, center_y),
                radius,
                (35, 196, 116),
                max(2, round(min(image.shape[:2]) / 500)),
            )
            cv2.putText(
                overlay,
                str(label_id),
                (center_x - 8, center_y + 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.4, min(image.shape[:2]) / 1600),
                (255, 255, 255),
                max(1, round(min(image.shape[:2]) / 700)),
                cv2.LINE_AA,
            )
        return overlay


def detect_roi_definition(
    image: np.ndarray,
    mask: np.ndarray,
    config: AnalysisConfig,
    analysis_crop: AnalysisCrop | None = None,
) -> RoiDefinition:
    """Use PlantCV once to locate the ROI grid in a calibration image."""
    from plantcv import plantcv as pcv  # type: ignore[import-not-found]

    crop = analysis_crop or AnalysisCrop()
    x0, y0, x1, y1 = crop.pixel_bounds(image.shape)
    calibration_image = image[y0:y1, x0:x1]
    calibration_mask = remove_square_calibration_components(
        mask[y0:y1, x0:x1]
    )
    try:
        objects = pcv.roi.auto_grid(
            mask=calibration_mask,
            nrows=config.roi_rows,
            ncols=config.roi_cols,
            img=calibration_image,
        )
    except (RuntimeError, ValueError) as exc:
        raise ValueError(
            "PlantCV could not detect the requested ROI grid inside the "
            "analysis area. Adjust the crop, segmentation, rows, or columns."
        ) from exc
    detected: list[tuple[float, float, float]] = []
    for contours in objects.contours:
        contour = np.asarray(contours[0])
        (center_x, center_y), radius = cv2.minEnclosingCircle(contour)
        detected.append((center_x, center_y, radius))
    expected = config.roi_rows * config.roi_cols
    if len(detected) != expected:
        raise ValueError(
            f"PlantCV detected {len(detected)} ROIs; expected {expected}."
        )

    ordered: list[tuple[float, float, float]] = []
    by_y = sorted(detected, key=lambda circle: circle[1])
    for row in range(config.roi_rows):
        start = row * config.roi_cols
        ordered.extend(
            sorted(
                by_y[start : start + config.roi_cols],
                key=lambda circle: circle[0],
            )
        )

    height, width = image.shape[:2]
    radius_scale = min(width, height)
    circles = tuple(
        RoiCircle(
            row=index // config.roi_cols,
            column=index % config.roi_cols,
            center_x=(x0 + center_x) / width,
            center_y=(y0 + center_y) / height,
            radius=(radius * config.roi_diameter_scale) / radius_scale,
        )
        for index, (center_x, center_y, radius) in enumerate(ordered)
    )
    return RoiDefinition(
        schema_version=2,
        rows=config.roi_rows,
        columns=config.roi_cols,
        source_width=width,
        source_height=height,
        config_fingerprint=config.fingerprint,
        circles=circles,
        analysis_crop=crop,
    )


def remove_square_calibration_components(mask: np.ndarray) -> np.ndarray:
    """Exclude ColorChecker-like squares from the ROI detection mask."""
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    cleaned = binary.copy()
    image_area = mask.shape[0] * mask.shape[1]
    minimum_area = max(64, round(image_area * 0.00002))
    maximum_area = round(image_area * 0.025)

    for label_id in range(1, count):
        width = stats[label_id, cv2.CC_STAT_WIDTH]
        height = stats[label_id, cv2.CC_STAT_HEIGHT]
        area = stats[label_id, cv2.CC_STAT_AREA]
        if (
            area < minimum_area
            or area > maximum_area
            or width == 0
            or height == 0
        ):
            continue
        aspect_ratio = width / height
        rectangularity = area / (width * height)
        if 0.72 <= aspect_ratio <= 1.38 and rectangularity >= 0.86:
            cleaned[labels == label_id] = 0

    return (cleaned * 255).astype(mask.dtype)
