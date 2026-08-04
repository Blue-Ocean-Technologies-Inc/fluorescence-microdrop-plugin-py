"""Persistence tests: session config round-trip (v2 + v1 fallback),
stats-store round-trip, and the CSV export layout."""
import csv
import json
import math

from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, Roi, RoiStyle,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_stats, load_session, save_roi_stats, save_session,
    write_intensity_csv,
)


def test_session_round_trip_preserves_rois_styles_and_figure(tmp_path):
    roi = Roi(name="Cell body", kind="box",
              geometry=[1.0, 2.0, 30.0, 40.0], base_anchor=100.0,
              overrides={200.0: [5.0, 6.0, 30.0, 40.0]},
              style=RoiStyle(color="#d62728", line_style="dashed",
                             marker="o", marker_size=7.0))
    session = AnalysisSession(directory=str(tmp_path), rois=[roi],
                              plot_stat="bg_corrected")
    session.figure.y_auto = False
    session.figure.y_max = 4096.0
    save_session(tmp_path, session)

    loaded = load_session(tmp_path)
    assert loaded.directory == str(tmp_path)
    assert loaded.plot_stat == "bg_corrected"
    assert loaded.figure.y_auto is False and loaded.figure.y_max == 4096.0
    (back,) = loaded.rois
    assert back.roi_id == roi.roi_id and back.name == "Cell body"
    assert back.overrides == {200.0: [5.0, 6.0, 30.0, 40.0]}
    assert back.style.color == "#d62728"
    assert back.style.line_style == "dashed"
    assert back.style.marker == "o" and back.style.marker_size == 7.0


def test_figure_fit_settings_round_trip(tmp_path):
    session = AnalysisSession()
    session.figure.fit_method = "exponential"
    session.figure.show_legend = False
    session.figure.show_second_derivative_max = True
    session.figure.view_mode = "fastest_change"
    session.figure.trim_poor_fit = True
    save_session(tmp_path, session)

    loaded = load_session(tmp_path)
    assert loaded.figure.fit_method == "exponential"
    assert loaded.figure.show_legend is False
    assert loaded.figure.show_second_derivative_max is True
    assert loaded.figure.view_mode == "fastest_change"
    assert loaded.figure.trim_poor_fit is True


def test_load_session_accepts_v1_bare_list(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text(json.dumps([{
        "roi_id": "abcd1234", "name": "ROI 1", "kind": "circle",
        "geometry": [10.0, 10.0, 5.0], "base_anchor": 0.0,
        "overrides": {},
    }]))
    loaded = load_session(tmp_path)
    (roi,) = loaded.rois
    assert roi.roi_id == "abcd1234" and roi.kind == "circle"
    assert loaded.plot_stat == "mean"          # defaults fill in
    assert roi.style.line_style == "solid"


def test_load_session_bad_plot_stat_keeps_parsed_roi(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text(json.dumps({
        "version": 2, "plot_stat": "sparkle",
        "rois": [{
            "roi_id": "abcd1234", "name": "ROI 1", "kind": "circle",
            "geometry": [10.0, 10.0, 5.0], "base_anchor": 0.0,
            "overrides": {},
        }],
    }))
    loaded = load_session(tmp_path)
    (roi,) = loaded.rois
    assert roi.roi_id == "abcd1234"
    assert loaded.plot_stat == "mean"


def test_load_session_missing_or_corrupt_is_empty(tmp_path):
    assert load_session(tmp_path).rois == []
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text("{nope")
    assert load_session(tmp_path).rois == []


def test_stats_store_round_trip_including_nan(tmp_path):
    key = (str(tmp_path / "a_raw.png"), 123.5, "abcd1234", "circle",
           (10.0, 10.0, 5.0))
    stats = {"mean": 42.5, "std": float("nan"), "count": 9.0}
    save_roi_stats(tmp_path, {key: stats})

    loaded = load_roi_stats(tmp_path)
    assert set(loaded) == {key}
    assert loaded[key]["mean"] == 42.5
    assert math.isnan(loaded[key]["std"])


def test_load_roi_stats_missing_or_corrupt_is_empty(tmp_path):
    assert load_roi_stats(tmp_path) == {}
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_stats.json").write_text("[not the schema]")
    assert load_roi_stats(tmp_path) == {}


def test_write_intensity_csv_layout(tmp_path):
    roi = Roi(name="ROI 1", kind="box", geometry=[1.0, 1.0, 5.0, 5.0])
    rows = [{
        "filename": "img_raw.png", "time_utc": "2026_07_20-17_46_24",
        "elapsed_sec": 0.0, "group": "burst_a", "wavelength": "Green 540 nm",
        "stats": {roi.roi_id: {"mean": 10.0, "std": 1.0, "median": 10.0,
                               "min": 8.0, "max": 12.0, "count": 25.0,
                               "outline_mean": 9.0, "outline_std": 1.0,
                               "outline_median": 9.0, "outline_min": 8.0,
                               "outline_max": 10.0, "outline_count": 16.0}},
    }, {
        "filename": "img2_raw.png", "time_utc": "2026_07_20-17_46_25",
        "elapsed_sec": 1.0, "group": "burst_a", "wavelength": "Green 540 nm",
        "stats": {},   # not computed: blank cells
    }]
    csv_path = tmp_path / "out.csv"
    write_intensity_csv(csv_path, rows, [roi])
    with open(csv_path, newline="") as handle:
        records = list(csv.reader(handle))
    assert records[0][:6] == ["index", "time_utc", "elapsed_sec",
                              "filename", "group", "wavelength"]
    assert "ROI 1_mean" in records[0]
    assert "ROI 1_outline_count" in records[0]
    mean_column = records[0].index("ROI 1_mean")
    assert records[1][mean_column] == "10.0"
    assert records[2][mean_column] == ""
