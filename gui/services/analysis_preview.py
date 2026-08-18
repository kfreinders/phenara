from __future__ import annotations

import base64
import binascii

from scripts.analysis.config import AnalysisConfig
from scripts.analysis.preview import (
    apply_mask_exclusions,
    encode_png,
    fit_for_display,
    generate_analysis_preview,
    prepare_analysis_image,
)
from scripts.analysis.roi import AnalysisCrop, detect_roi_definition


MAX_CALIBRATION_IMAGE_BYTES = 10_000_000


def build_analysis_preview(
    image_data: str,
    config_data: dict,
    crop_data: dict | None = None,
    mask_exclusions: list[dict] | None = None,
) -> dict:
    image_bytes = _decode_image_data(image_data)
    config = AnalysisConfig.from_dict(config_data)
    preview = generate_analysis_preview(
        image_bytes,
        config,
        analysis_crop=(
            AnalysisCrop.from_dict(crop_data)
            if crop_data is not None
            else None
        ),
        mask_exclusions=mask_exclusions,
    )
    return {
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint,
        "stages": {
            "original": _png_data_url(encode_png(preview.original)),
            "channel": _png_data_url(encode_png(preview.channel)),
            "mask": _png_data_url(encode_png(preview.mask)),
            "overlay": _png_data_url(encode_png(preview.overlay)),
        },
    }


def build_roi_preview(
    image_data: str,
    config_data: dict,
    crop_data: dict,
    mask_exclusions: list[dict] | None = None,
) -> dict:
    image_bytes = _decode_image_data(image_data)
    config = AnalysisConfig.from_dict(config_data)
    prepared = prepare_analysis_image(image_bytes, config)
    crop = AnalysisCrop.from_dict(crop_data)
    calibration_mask = apply_mask_exclusions(
        prepared.mask, crop, mask_exclusions or []
    )
    definition = detect_roi_definition(
        prepared.image,
        calibration_mask,
        config,
        crop,
    )
    overlay = fit_for_display(definition.draw_overlay(prepared.image), 960)
    return {
        "definition": definition.to_dict(),
        "definition_fingerprint": definition.fingerprint,
        "overlay": _png_data_url(encode_png(overlay)),
    }


def _decode_image_data(value: str) -> bytes:
    prefix, separator, payload = value.partition(",")
    if not separator or not prefix.startswith("data:image/"):
        raise ValueError("Provide a valid image data URL.")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The calibration image is not valid base64 data.") from exc
    if not decoded:
        raise ValueError("The calibration image is empty.")
    if len(decoded) > MAX_CALIBRATION_IMAGE_BYTES:
        raise ValueError("The calibration image must be 10 MB or smaller.")
    return decoded


def _png_data_url(value: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(value).decode('ascii')}"
