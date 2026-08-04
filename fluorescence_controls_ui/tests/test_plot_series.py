"""Series derivation: pure function of (session, filtered paths)."""
import math

from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    derive_series, stat_value,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, Roi,
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
