"""SAM droplet detection: osam session, point/grid segmentation, and
candidate conversion. Qt-free (numpy/cv2 in-and-out), importable with or
without the optional ``osam`` package — ``sam_available()`` reports which.

Ported from the standalone droplet_roi prototype (labelme-derived); see
docs/superpowers/specs/2026-08-07-automatic-roi-identification-design.md.
"""
import numpy as np

from logger.logger_service import get_logger

from .consts import (
    AI_DETECT_GRID_TARGET_POINTS, AI_DETECT_MAX_MASK_AREA_FRACTION,
    AI_DETECT_MIN_MASK_AREA_PX, AI_ENCODE_WORK_WIDTH_PX,
    AI_NORMALIZE_HIGH_PERCENTILE, AI_NORMALIZE_LOW_PERCENTILE,
)

logger = get_logger(__name__)

try:
    import osam
except ImportError:          # optional dependency: Help menu installs it
    osam = None

#: (model_name, display_name) — PROTO sam.py MODEL_OPTIONS, labelme's
#: point-prompt AI-assist list, speed -> accuracy within each family.
AI_MODEL_OPTIONS = (
    ("efficientsam:10m", "EfficientSam (speed)"),
    ("efficientsam:latest", "EfficientSam (accuracy)"),
    ("sam:100m", "Sam (speed)"),
    ("sam:300m", "Sam (balanced)"),
    ("sam:latest", "Sam (accuracy)"),
    ("sam2:small", "Sam2 (speed)"),
    ("sam2:latest", "Sam2 (balanced)"),
    ("sam2:large", "Sam2 (accuracy)"),
)
DEFAULT_AI_MODEL = "efficientsam:latest"


def sam_available():
    """Whether the optional osam stack imported."""
    return osam is not None


def normalize_to_uint8(array, low_pct=AI_NORMALIZE_LOW_PERCENTILE,
                       high_pct=AI_NORMALIZE_HIGH_PERCENTILE):
    """Percentile-clip contrast stretch to uint8 (PROTO imaging.py)."""
    if array.dtype == np.uint8 and array.max() > 200:
        return array
    array = array.astype(np.float64)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return np.zeros(array.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [low_pct, high_pct])
    if high - low <= 0:
        return np.zeros(array.shape, dtype=np.uint8)
    normalized = (array - low) / (high - low) * 255
    return np.nan_to_num(np.clip(normalized, 0, 255),
                         nan=0.0).astype(np.uint8)


def to_rgb(gray_u8):
    """Stack grayscale to (H, W, 3) as the SAM encoder requires."""
    return np.stack([gray_u8] * 3, axis=-1)
