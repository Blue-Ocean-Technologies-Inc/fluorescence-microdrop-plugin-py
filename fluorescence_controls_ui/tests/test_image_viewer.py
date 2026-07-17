"""Hardware-free tests for the 16-bit image viewer display helpers and
capture discovery."""
import os

import numpy as np
from PySide6.QtGui import QImage

from fluorescence_controls_ui.cameras.asi_thread import raw_to_qimage
from fluorescence_controls_ui.image_viewer import discovery
from fluorescence_controls_ui.image_viewer.display import (
    qimage_to_array, stretch_to_8bit,
)


def test_16bit_png_round_trip_is_lossless(tmp_path):
    raw = (np.arange(40 * 30, dtype=np.uint16).reshape(30, 40) * 50)
    path = str(tmp_path / "raw.png")
    assert raw_to_qimage(raw).save(path)
    back = qimage_to_array(QImage(path))
    assert back.dtype == np.uint16
    assert np.array_equal(back, raw)


def test_auto_contrast_windows_dim_frames():
    # dark field + small bright blob: naive full-range display is ~black.
    raw = np.full((60, 80), 400, dtype=np.uint16)
    raw[20:30, 30:40] = 3200
    naive = stretch_to_8bit(raw, auto_contrast=False)
    auto = stretch_to_8bit(raw, auto_contrast=True)
    assert naive.max() <= 12
    assert auto.min() == 0 and auto.max() == 255


def test_flat_frame_does_not_divide_by_zero():
    flat = np.full((8, 8), 1234, dtype=np.uint16)
    out = stretch_to_8bit(flat, auto_contrast=True)
    assert out.dtype == np.uint8


def test_8bit_grayscale_passthrough_shape():
    img = np.random.default_rng(0).integers(0, 255, (16, 16), dtype=np.uint8)
    out = stretch_to_8bit(img, auto_contrast=False)
    assert out.shape == img.shape and out.dtype == np.uint8


def test_manual_window_maps_low_to_black_high_to_white():
    raw = np.array([[100, 200], [300, 400]], dtype=np.uint16)
    out = stretch_to_8bit(raw, auto_contrast=False, window=(200, 400))
    assert out[0, 0] == 0        # below the window clips to black
    assert out[0, 1] == 0        # window low edge
    assert out[1, 1] == 255      # window high edge
    assert 0 < out[1, 0] < 255   # mid-window stays mid-gray


def test_manual_window_inverted_renders_black_not_crash():
    raw = np.full((4, 4), 300, dtype=np.uint16)
    out = stretch_to_8bit(raw, auto_contrast=False, window=(400, 200))
    assert out.dtype == np.uint8 and out.max() == 0


def test_manual_window_ignored_while_auto_contrast_on():
    raw = np.full((60, 80), 400, dtype=np.uint16)
    raw[20:30, 30:40] = 3200
    auto = stretch_to_8bit(raw, auto_contrast=True, window=(0, 65535))
    assert auto.max() == 255     # percentile window, not the manual one


def test_viewer_model_navigation_wraps_and_positions():
    from pathlib import Path
    from fluorescence_controls_ui.image_viewer.model import (
        FluorescenceImageViewerModel,
    )
    model = FluorescenceImageViewerModel()
    assert model.relative_path(1) is None          # nothing discovered
    assert model.position_text == ""

    model.paths = [Path("a.png"), Path("b.png"), Path("c.png")]
    assert model.relative_path(1) == Path("a.png")  # no current: enter at start
    assert model.relative_path(-1) == Path("c.png")
    assert model.position_text == "–/3"             # showing an outside image
    assert model.image_names == ["a.png", "b.png", "c.png"]
    assert model.max_image_index == 2

    model.current_path = str(Path("c.png"))
    assert model.position_text == "3/3"
    assert model.path_index() == 2
    assert model.relative_path(1) == Path("a.png")  # wraps forward
    assert model.relative_path(-1) == Path("b.png")


def test_discover_captures_oldest_first_by_save_time(tmp_path):
    assert discovery.discover_captures(None) == []
    assert discovery.discover_captures(tmp_path / "absent") == []
    # Discovery is raws-only now: files live under a 16bit_raw parent.
    raw_dir = tmp_path / "16bit_raw"
    raw_dir.mkdir()
    older, newer = raw_dir / "b_older.png", raw_dir / "a_newer.png"
    older.write_bytes(b"")
    newer.write_bytes(b"")
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    assert discovery.discover_captures(tmp_path) == [older, newer]


def test_current_captures_directory_returns_captures_folder(tmp_path,
                                                               monkeypatch):
    # The renamed function returns <exp>/captures (not <exp>/captures/16bit_raw).
    monkeypatch.setattr(discovery, "get_current_experiment_directory",
                        lambda: tmp_path)
    assert discovery.current_captures_directory() == tmp_path / "captures"


def test_current_captures_directory_tolerates_no_experiment(monkeypatch):
    def unavailable():
        raise RuntimeError("no redis")
    monkeypatch.setattr(discovery, "get_current_experiment_directory",
                        unavailable)
    assert discovery.current_captures_directory() is None


def test_discover_captures_finds_nested_burst_raw_captures(tmp_path,
                                                           monkeypatch):
    # Nested burst raw captures: captures/Mix_1.2_x/16bit_raw/GFP_raw.png
    monkeypatch.setattr(discovery, "get_current_experiment_directory",
                        lambda: tmp_path)

    captures_dir = tmp_path / "captures"
    burst_dir = captures_dir / "Mix_1.2_x" / "16bit_raw"
    burst_dir.mkdir(parents=True, exist_ok=True)

    burst_raw = burst_dir / "GFP_raw.png"
    burst_raw.write_bytes(b"")

    discovered = discovery.discover_captures(captures_dir)
    assert burst_raw in discovered


def test_discover_captures_finds_old_flat_layout(tmp_path, monkeypatch):
    # Old flat layout: captures/16bit_raw/old_raw.png
    monkeypatch.setattr(discovery, "get_current_experiment_directory",
                        lambda: tmp_path)

    captures_dir = tmp_path / "captures"
    flat_dir = captures_dir / "16bit_raw"
    flat_dir.mkdir(parents=True, exist_ok=True)

    flat_raw = flat_dir / "old_raw.png"
    flat_raw.write_bytes(b"")

    discovered = discovery.discover_captures(captures_dir)
    assert flat_raw in discovered


def test_discover_captures_excludes_display_pngs_at_burst_root(tmp_path,
                                                               monkeypatch):
    # Display PNGs at burst root should NOT be returned.
    # captures/Mix_1.2_x/GFP.png should be excluded,
    # but captures/Mix_1.2_x/16bit_raw/GFP_raw.png should be included.
    monkeypatch.setattr(discovery, "get_current_experiment_directory",
                        lambda: tmp_path)

    captures_dir = tmp_path / "captures"
    burst_dir = captures_dir / "Mix_1.2_x"
    burst_dir.mkdir(parents=True, exist_ok=True)

    raw_subdir = burst_dir / "16bit_raw"
    raw_subdir.mkdir(parents=True, exist_ok=True)

    # Display PNG at burst root - should be excluded
    display_png = burst_dir / "GFP.png"
    display_png.write_bytes(b"")

    # Raw PNG in 16bit_raw - should be included
    raw_png = raw_subdir / "GFP_raw.png"
    raw_png.write_bytes(b"")

    discovered = discovery.discover_captures(captures_dir)
    assert raw_png in discovered
    assert display_png not in discovered
