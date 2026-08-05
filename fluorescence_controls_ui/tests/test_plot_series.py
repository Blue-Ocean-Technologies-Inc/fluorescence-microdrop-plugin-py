"""Series derivation: pure function of (session, filtered paths)."""
import math

from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    derive_series, normalized_series, stat_value, visible_series,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, Roi, RoiStyle,
)


def _image(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    return str(path)


def test_derive_series_elapsed_axis_and_nan_gaps(tmp_path):
    first = _image(tmp_path, "a_2026_07_20-10_00_00_raw.png")
    second = _image(tmp_path, "b_2026_07_20-10_00_30_raw.png")
    roi = Roi(name="ROI 1", kind="ellipse",
              geometry=[5.0, 5.0, 2.0, 2.0, 0.0])
    session = AnalysisSession(rois=[roi])
    session.stats[session.cache_key(first, roi)] = {
        "mean": 10.0, "outline_mean": 4.0}

    series = derive_series(session, [first, second])
    name, elapsed, values = series[roi.roi_id]
    assert name == "ROI 1"
    assert elapsed == [0.0, 30.0]
    assert values[0] == 10.0
    assert math.isnan(values[1])          # uncomputed image gaps


def test_derive_series_honors_plot_stat(tmp_path):
    image = _image(tmp_path, "a_2026_07_20-10_00_00_raw.png")
    roi = Roi(name="ROI 1", kind="ellipse",
              geometry=[5.0, 5.0, 2.0, 2.0, 0.0])
    session = AnalysisSession(rois=[roi], plot_stat="bg_corrected")
    session.stats[session.cache_key(image, roi)] = {
        "mean": 10.0, "outline_mean": 4.0}
    (_, _, values), = derive_series(session, [image]).values()
    assert values == [6.0]


def test_derive_series_empty_inputs():
    assert derive_series(AnalysisSession(), []) == {}


def test_stat_value_variants():
    stats = {"mean": 10.0, "median": 9.0, "outline_mean": 4.0}
    assert stat_value(stats, "median") == 9.0
    assert stat_value(stats, "bg_corrected") == 6.0
    assert math.isnan(stat_value(None, "mean"))
    assert math.isnan(stat_value({}, "mean"))
    assert math.isnan(stat_value({"mean": 10.0}, "bg_corrected"))


def test_visible_series_drops_the_hidden_rois():
    shown = Roi(roi_id="a", name="ROI 1", kind="ellipse")
    hidden = Roi(roi_id="b", name="ROI 2", kind="ellipse",
                 style=RoiStyle(visible=False))
    session = AnalysisSession(rois=[shown, hidden])
    series = {"a": ("ROI 1", [0.0], [1.0]),
              "b": ("ROI 2", [0.0], [2.0])}

    assert visible_series(session, series) == {"a": ("ROI 1", [0.0], [1.0])}


def test_visible_series_keeps_everything_by_default():
    session = AnalysisSession(rois=[Roi(roi_id="a", name="ROI 1")])
    series = {"a": ("ROI 1", [0.0], [1.0])}
    assert visible_series(session, series) == series


def test_visible_series_drops_series_without_an_roi():
    # A stale entry cannot be styled, so it cannot be drawn either.
    session = AnalysisSession(rois=[])
    assert visible_series(session, {"gone": ("ROI 9", [], [])}) == {}


def test_plot_alpha_is_the_percentage_as_a_fraction():
    assert RoiStyle().plot_alpha == 1.0
    assert RoiStyle(alpha=40).plot_alpha == 0.4


def test_size_aware_stats_without_a_calibration():
    stats = {"mean": 10.0, "outline_mean": 4.0, "count": 25.0}
    # px² units: area is the pixel count and density is the mean.
    assert stat_value(stats, "area") == 25.0
    assert stat_value(stats, "integrated") == 250.0
    assert stat_value(stats, "bg_integrated") == 150.0
    assert stat_value(stats, "per_area") == 10.0
    assert stat_value(stats, "bg_per_area") == 6.0


def test_size_aware_stats_with_a_calibration():
    stats = {"mean": 10.0, "outline_mean": 4.0, "count": 25.0}
    # 1e-4 mm² per pixel: 25 px is 2.5e-3 mm².
    assert abs(stat_value(stats, "area", 1e-4) - 2.5e-3) < 1e-12
    assert abs(stat_value(stats, "per_area", 1e-4) - 1e5) < 1e-6
    assert abs(stat_value(stats, "bg_per_area", 1e-4) - 6e4) < 1e-6
    # Integrated is a pixel sum, so a calibration cannot change it.
    assert stat_value(stats, "integrated", 1e-4) == 250.0


def test_size_aware_stats_are_nan_when_a_piece_is_missing():
    assert math.isnan(stat_value({"mean": 10.0}, "integrated"))
    assert math.isnan(stat_value({"count": 25.0}, "per_area"))
    assert math.isnan(stat_value({"mean": 10.0, "count": 25.0},
                                 "bg_integrated"))


def test_derive_series_uses_the_sessions_calibration(tmp_path):
    image = _image(tmp_path, "a_2026_07_20-10_00_00_raw.png")
    roi = Roi(name="ROI 1", kind="ellipse",
              geometry=[5.0, 5.0, 2.0, 2.0, 0.0])
    # "area" is table/CSV only, so per_area is what carries the
    # calibration into a plotted series: 10 / 1e-4 mm^2 = 1e5.
    session = AnalysisSession(rois=[roi], plot_stat="per_area")
    session.scale.trait_set(metres_per_pixel=1e-5, unit="mm")
    session.stats[session.cache_key(image, roi)] = {
        "mean": 10.0, "outline_mean": 4.0, "count": 25.0}

    _name, _elapsed, values = derive_series(session, [image])[roi.roi_id]
    assert abs(values[0] - 1e5) < 1e-6


def test_normalized_series_stretches_each_roi_to_its_own_range():
    series = {"a": ("ROI 1", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0]),
              "b": ("ROI 2", [0.0, 1.0, 2.0], [100.0, 300.0, 500.0])}
    result = normalized_series(series)
    assert result["a"][2] == [0.0, 50.0, 100.0]
    assert result["b"][2] == [0.0, 50.0, 100.0]
    # Names and time axes ride through untouched.
    assert result["a"][0] == "ROI 1" and result["a"][1] == [0.0, 1.0, 2.0]


def test_normalized_series_keeps_gaps_as_gaps():
    series = {"a": ("ROI 1", [0.0, 1.0, 2.0],
                    [10.0, math.nan, 30.0])}
    values = normalized_series(series)["a"][2]
    assert values[0] == 0.0 and values[2] == 100.0
    assert math.isnan(values[1])


def test_normalized_series_leaves_a_flat_curve_at_zero():
    series = {"a": ("ROI 1", [0.0, 1.0], [7.0, 7.0])}
    assert normalized_series(series)["a"][2] == [0.0, 0.0]


def test_normalized_series_passes_an_all_nan_curve_through():
    series = {"a": ("ROI 1", [0.0, 1.0], [math.nan, math.nan])}
    assert all(math.isnan(value)
               for value in normalized_series(series)["a"][2])
