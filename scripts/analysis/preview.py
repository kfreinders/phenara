from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import AnalysisConfig
from .roi import AnalysisCrop


@dataclass(frozen=True)
class AnalysisPreview:
    original: np.ndarray
    channel: np.ndarray
    mask: np.ndarray
    overlay: np.ndarray


@dataclass(frozen=True)
class PreparedAnalysisImage:
    image: np.ndarray
    channel: np.ndarray
    mask: np.ndarray


def prepare_analysis_image(
    image_bytes: bytes,
    config: AnalysisConfig,
) -> PreparedAnalysisImage:
    if not image_bytes:
        raise ValueError("The calibration image is empty.")
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("The calibration image could not be decoded.")

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rotated = _rotate_image(rgb, config.rotate_angle)
    lab = cv2.cvtColor(rotated, cv2.COLOR_RGB2LAB)
    channel_index = {"l": 0, "a": 1, "b": 2}[config.sepchannel]
    channel = lab[:, :, channel_index]
    mask = np.where(channel <= config.threshold, 255, 0).astype(np.uint8)
    mask = _remove_small_components(mask, config.fill_size)
    return PreparedAnalysisImage(image=rotated, channel=channel, mask=mask)


def generate_analysis_preview(
    image_bytes: bytes,
    config: AnalysisConfig,
    *,
    max_dimension: int = 960,
    analysis_crop: AnalysisCrop | None = None,
    mask_exclusions: list[dict] | None = None,
) -> AnalysisPreview:
    """Generate display-sized segmentation stages without measuring traits."""
    prepared = prepare_analysis_image(image_bytes, config)
    rotated, channel, mask = (
        prepared.image,
        prepared.channel,
        prepared.mask,
    )
    crop = analysis_crop or AnalysisCrop()
    mask = apply_mask_exclusions(mask, crop, mask_exclusions or [])

    overlay = rotated.copy()
    selected = mask > 0
    green = np.array([67, 190, 113], dtype=np.float32)
    overlay[selected] = (
        overlay[selected].astype(np.float32) * 0.45 + green * 0.55
    ).astype(np.uint8)
    x0, y0, x1, y1 = crop.pixel_bounds(rotated.shape)

    return AnalysisPreview(
        original=fit_for_display(rotated, max_dimension),
        channel=fit_for_display(channel[y0:y1, x0:x1], max_dimension),
        mask=fit_for_display(
            mask[y0:y1, x0:x1],
            max_dimension,
            interpolation=cv2.INTER_NEAREST,
        ),
        overlay=fit_for_display(overlay[y0:y1, x0:x1], max_dimension),
    )


def apply_mask_exclusions(
    mask: np.ndarray,
    analysis_crop: AnalysisCrop,
    strokes: list[dict],
) -> np.ndarray:
    """Erase calibration-only brush strokes from a segmentation mask."""
    if not strokes:
        return mask
    edited = mask.copy()
    x0, y0, x1, y1 = analysis_crop.pixel_bounds(mask.shape)
    crop_width = x1 - x0
    crop_height = y1 - y0
    radius_scale = min(crop_width, crop_height)

    for stroke in strokes:
        radius = float(stroke["radius"])
        points = stroke["points"]
        pixel_points = [
            (
                x0 + round(float(point["x"]) * crop_width),
                y0 + round(float(point["y"]) * crop_height),
            )
            for point in points
        ]
        brush_radius = max(1, round(radius * radius_scale))
        for point in pixel_points:
            cv2.circle(edited, point, brush_radius, 0, thickness=-1)
        for start, end in zip(pixel_points, pixel_points[1:]):
            cv2.line(
                edited,
                start,
                end,
                0,
                thickness=brush_radius * 2,
                lineType=cv2.LINE_8,
            )
    return edited


def encode_png(image: np.ndarray) -> bytes:
    """Encode an RGB or grayscale preview as PNG."""
    source = (
        cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if image.ndim == 3
        else image
    )
    success, encoded = cv2.imencode(".png", source)
    if not success:
        raise ValueError("An analysis preview image could not be encoded.")
    return encoded.tobytes()


def _rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
    if angle == 0:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def _remove_small_components(mask: np.ndarray, minimum_area: int) -> np.ndarray:
    if minimum_area <= 1:
        return mask
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    cleaned = np.zeros_like(mask)
    for label_id in range(1, count):
        if stats[label_id, cv2.CC_STAT_AREA] >= minimum_area:
            cleaned[labels == label_id] = 255
    return cleaned


def fit_for_display(
    image: np.ndarray,
    max_dimension: int,
    *,
    interpolation: int = cv2.INTER_AREA,
) -> np.ndarray:
    if max_dimension <= 0:
        raise ValueError("Preview maximum dimension must be positive.")
    height, width = image.shape[:2]
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1:
        return image
    return cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=interpolation,
    )
