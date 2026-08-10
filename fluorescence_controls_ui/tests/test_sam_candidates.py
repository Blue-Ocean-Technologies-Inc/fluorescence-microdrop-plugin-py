"""Tests for SAM candidate conversion and filtering (no osam needed)."""
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.sam_detect import (
    AI_MODEL_OPTIONS, DEFAULT_AI_MODEL, normalize_to_uint8, sam_available,
)


def test_default_model_is_one_of_the_options():
    assert DEFAULT_AI_MODEL in {name for name, _ in AI_MODEL_OPTIONS}
    assert isinstance(sam_available(), bool)


def test_normalize_stretches_16bit_to_full_range():
    ramp = np.linspace(1000, 3000, 256 * 256).reshape(256, 256)
    out = normalize_to_uint8(ramp.astype(np.uint16))
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_normalize_of_flat_frame_is_black():
    flat = np.full((16, 16), 500, dtype=np.uint16)
    assert normalize_to_uint8(flat).max() == 0
