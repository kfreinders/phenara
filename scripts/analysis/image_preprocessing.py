from pathlib import Path
from typing import cast

import numpy as np
from plantcv import plantcv as pcv  # type: ignore[import-not-found]

from .config import AnalysisConfig


def load_and_rotate_image(image_path: Path, angle: float) -> np.ndarray:
    image, _, _ = pcv.readimage(filename=str(image_path))  # type: ignore[misc]
    if angle != 0:
        image = pcv.transform.rotate(image, angle, crop=True)
    return cast(np.ndarray, image)


def segment_plants(
    image: np.ndarray,
    config: AnalysisConfig,
) -> np.ndarray:
    channel = pcv.rgb2gray_lab(
        rgb_img=image,
        channel=config.sepchannel,
    )
    pcv.visualize.histogram(img=channel, bins=25)
    mask = pcv.threshold.binary(
        gray_img=channel,
        threshold=config.threshold,
        object_type="dark",
    )
    return cast(np.ndarray, pcv.fill(bin_img=mask, size=config.fill_size))
