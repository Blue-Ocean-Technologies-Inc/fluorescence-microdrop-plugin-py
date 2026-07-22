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


# --- burst discovery + wavelength detection (issue #6 viewer rework) -------

def _make_raw(directory, name, mtime):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"")
    os.utime(path, (mtime, mtime))
    return path


def test_discover_bursts_groups_by_folder_oldest_first(tmp_path):
    captures = tmp_path / "captures"
    b1 = _make_raw(captures / "Mix_1.2_x" / "16bit_raw",
                   "Blue_460_nm_1_ts_raw.png", 1_000)
    b2a = _make_raw(captures / "Rinse_2_y" / "16bit_raw",
                    "Green_540_nm_1_ts_raw.png", 2_000)
    b2b = _make_raw(captures / "Rinse_2_y" / "16bit_raw",
                    "Blue_460_nm_2_ts_raw.png", 3_000)
    legacy = _make_raw(captures / "16bit_raw", "old_raw.png", 500)

    bursts = discovery.discover_bursts(captures)
    assert [name for name, _ in bursts] == [
        discovery.UNGROUPED_BURST, "Mix_1.2_x", "Rinse_2_y"]
    as_dict = dict(bursts)
    assert as_dict["Mix_1.2_x"] == [b1]
    assert as_dict["Rinse_2_y"] == [b2a, b2b]
    assert as_dict[discovery.UNGROUPED_BURST] == [legacy]


def test_discover_bursts_empty_and_missing(tmp_path):
    assert discovery.discover_bursts(None) == []
    assert discovery.discover_bursts(tmp_path / "absent") == []


def test_detect_wavelength_from_derived_labels():
    assert discovery.detect_wavelength(
        "gfp_Green_540_nm_2_2026_07_20-17_46_24_raw.png") == "Green (540 nm)"
    assert discovery.detect_wavelength(
        "Deep_Red_660_nm_1_ts.png") == "Deep Red (660 nm)"
    assert discovery.detect_wavelength(
        "free_mode_2026_07_20-17_50_08_raw.png") == ""


# --- burst/wavelength navigation (controller level, no Qt) -----------------

import types as _types

from fluorescence_controls_ui.image_viewer import controller as viewer_controller_mod
from fluorescence_controls_ui.image_viewer.controller import (
    FluorescenceImageViewerController,
)
from fluorescence_controls_ui.image_viewer.model import (
    FluorescenceImageViewerModel, WAVELENGTH_FILTER_ALL,
)


def _viewer(monkeypatch, tmp_path):
    """Model + controller over a synthetic two-burst captures tree, with
    image loading stubbed out (navigation is under test, not decoding)."""
    captures = tmp_path / "captures"
    paths = {
        "old_blue": _make_raw(captures / "Mix_1.2_a" / "16bit_raw",
                              "Blue_460_nm_1_t1_raw.png", 1_000),
        "old_green": _make_raw(captures / "Mix_1.2_a" / "16bit_raw",
                               "Green_540_nm_2_t2_raw.png", 1_500),
        "new_blue": _make_raw(captures / "Rinse_3_b" / "16bit_raw",
                              "Blue_460_nm_1_t3_raw.png", 2_000),
    }
    monkeypatch.setattr(viewer_controller_mod, "load_image_array",
                        lambda path: np.zeros((2, 2), dtype=np.uint16))
    model = FluorescenceImageViewerModel()
    model.directory = ""   # follow-the-experiment mode
    ctrl = FluorescenceImageViewerController(model=model)
    monkeypatch.setattr(ctrl, "_scan_directory", lambda: captures)
    return ctrl, model, paths


def test_rescan_follows_newest_burst_and_populates_wavelengths(
        monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    assert model.burst_names == ["Mix_1.2_a", "Rinse_3_b"]
    assert model.selected_burst == "Rinse_3_b"
    assert model.burst_index == 1
    assert model.current_path == str(paths["new_blue"])
    assert model.wavelength_names == [
        WAVELENGTH_FILTER_ALL, "Blue (460 nm)", "Green (540 nm)"]


def test_selecting_older_burst_shows_its_first_image(monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    model.selected_burst = "Mix_1.2_a"
    assert model.burst_index == 0
    assert [p.name for p in model.paths] == [
        "Blue_460_nm_1_t1_raw.png", "Green_540_nm_2_t2_raw.png"]
    assert model.current_path == str(paths["old_blue"])


def test_burst_slider_drives_selection(monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    model.burst_index = 0
    assert model.selected_burst == "Mix_1.2_a"


def test_wavelength_filter_narrows_and_keeps_surviving_image(
        monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    model.selected_burst = "Mix_1.2_a"   # shows old_blue
    model.selected_wavelength = "Blue (460 nm)"
    assert [p.name for p in model.paths] == ["Blue_460_nm_1_t1_raw.png"]
    assert model.current_path == str(paths["old_blue"])   # survived

    model.selected_wavelength = "Green (540 nm)"
    assert [p.name for p in model.paths] == ["Green_540_nm_2_t2_raw.png"]
    assert model.current_path == str(paths["old_green"])  # fell to first


def test_parked_user_stays_parked_when_new_burst_lands(
        monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    model.selected_burst = "Mix_1.2_a"
    captures = paths["old_blue"].parent.parent.parent
    _make_raw(captures / "Zap_4_c" / "16bit_raw",
              "Red_630_nm_1_t4_raw.png", 3_000)
    ctrl.rescan()
    assert model.selected_burst == "Mix_1.2_a"            # still parked
    assert "Zap_4_c" in model.burst_names                 # but discovered
    assert "Red (630 nm)" in model.wavelength_names


def test_seek_sliders_are_one_based_twins(monkeypatch, tmp_path):
    """The sliders bind to 1-based `*_number` twins; setting a number
    drives the 0-based index and vice versa."""
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    assert model.burst_number == model.burst_index + 1 == 2
    assert model.max_burst_number == 2
    model.burst_number = 1
    assert model.burst_index == 0 and model.selected_burst == "Mix_1.2_a"
    assert model.max_image_number == len(model.paths) == 2
    model.image_number = 2
    assert model.image_index == 1
    assert model.current_path == str(paths["old_green"])


def test_rescan_records_the_browsed_directory(monkeypatch, tmp_path):
    ctrl, model, paths = _viewer(monkeypatch, tmp_path)
    ctrl.rescan()
    assert model.browsed_directory == str(tmp_path / "captures")


def test_dock_pane_title_names_the_browsed_folder():
    from pathlib import Path

    from fluorescence_controls_ui.image_viewer.dock_pane import _title_for
    assert _title_for("") == "Fluorescence Images"
    # Default (experiment) captures dir: the experiment folder names it.
    assert _title_for(str(Path("Experiments/2026_07_20-17_41_31/captures"))) \
        == "Fluorescence Images\t\t-\t\t2026_07_20-17_41_31"
    # A user-picked folder shows its own name.
    assert _title_for(str(Path("D:/some/album"))) \
        == "Fluorescence Images\t\t-\t\talbum"
