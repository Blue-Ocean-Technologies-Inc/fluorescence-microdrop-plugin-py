"""ROI config JSON round-trip and intensity-CSV layout."""
import csv

from fluorescence_controls_ui.image_viewer.analysis.roi_model import Roi
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_config, save_roi_config, write_intensity_csv,
)


def test_roi_config_round_trip(tmp_path):
    roi = Roi(name="ROI 1", kind="circle", geometry=[50.0, 50.0, 10.0],
              base_anchor=100.0)
    roi.apply_edit(200.0, [60.0, 60.0, 12.0])
    save_roi_config(tmp_path, [roi])
    loaded = load_roi_config(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].roi_id == roi.roi_id
    assert loaded[0].kind == "circle"
    assert loaded[0].effective_geometry(250.0) == [60.0, 60.0, 12.0]
    assert loaded[0].base_anchor == 100.0


def test_load_missing_or_corrupt_config_is_empty(tmp_path):
    assert load_roi_config(tmp_path) == []
    config_dir = tmp_path / "analysis"
    config_dir.mkdir()
    (config_dir / "roi_config.json").write_text("{not json")
    assert load_roi_config(tmp_path) == []


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
