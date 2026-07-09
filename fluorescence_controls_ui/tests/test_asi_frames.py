"""Hardware-free tests for the ASI display helpers and enumeration guard."""
import numpy as np

from fluorescence_controls_ui.cameras.asi_thread import (
    debayered_to_rgb, frame_to_qimage, raw_to_qimage, to_display_8bit,
)
from fluorescence_controls_ui.cameras.zwoasi import list_asi_cameras


def test_16bit_full_range_scales_by_256():
    img = np.full((4, 4), 40000, dtype=np.uint16)
    out = to_display_8bit(img)
    assert out.dtype == np.uint8 and out[0, 0] == 40000 // 256


def test_16bit_12bit_data_scales_by_16():
    img = np.full((4, 4), 4000, dtype=np.uint16)   # within 12-bit range
    out = to_display_8bit(img)
    assert out.dtype == np.uint8 and out[0, 0] == 4000 // 16


def test_8bit_passthrough():
    img = np.full((4, 4), 99, dtype=np.uint8)
    assert to_display_8bit(img) is img


def test_frame_to_qimage_shapes():
    gray = frame_to_qimage(np.zeros((10, 20), dtype=np.uint8))
    assert (gray.width(), gray.height()) == (20, 10)
    rgb = frame_to_qimage(np.zeros((10, 20, 3), dtype=np.uint8))
    assert (rgb.width(), rgb.height()) == (20, 10)


def test_debayered_to_rgb_swaps_color_channels():
    bgr = np.zeros((2, 2, 3), dtype=np.uint8)
    bgr[:, :, 0] = 200                       # blue plane, as the debayer emits
    assert debayered_to_rgb(bgr)[0, 0, 2] == 200


def test_debayered_to_rgb_mono_passthrough():
    mono = np.zeros((2, 2), dtype=np.uint16)
    assert debayered_to_rgb(mono) is mono


def test_raw_to_qimage_color_order():
    raw = np.zeros((2, 2, 3), dtype=np.uint16)
    raw[:, :, 0] = 65535                     # blue plane, as the debayer emits
    color = raw_to_qimage(raw).pixelColor(0, 0)
    assert (color.red(), color.green(), color.blue()) == (0, 0, 255)


def test_enumeration_disabled_without_sdk_dir(tmp_path):
    assert list_asi_cameras("") == []
    # A directory without the SDK library: logged + skipped, never raises.
    assert list_asi_cameras(str(tmp_path)) == []
