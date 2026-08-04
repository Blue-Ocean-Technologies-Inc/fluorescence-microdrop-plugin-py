# Area Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report each ROI's area, and plot its total signal and its signal per unit area — each in a raw and a background-corrected form.

**Architecture:** Everything is derived from numbers already stored: `count` (interior mask pixels) and the scale calibration. `scale_bar` gains `pixel_area`/`area_unit`, `stat_value` gains five branches and a `pixel_area` argument, and the plot, table and CSV pass that argument through and label their units.

**Tech Stack:** numpy-free pure Python, Traits/TraitsUI, matplotlib, PySide6 QTableWidget.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-area-statistics-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- `pixel_area` is one pixel's area in the display unit and is **1.0 when uncalibrated**, so every derivation still computes and reads in px².
- Nothing recomputes image statistics: `count`, `mean` and `outline_mean` are already in the stored stats dict.
- Source files are UTF-8 (`µ`, `²` appear in labels and CSV headers); pass `encoding="utf-8"` to any `pathlib.write_text` or `open` you add.
- f-strings everywhere; module-level imports; no aliasing of constants; conventional commits.
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/<file> -q"` (always from `microdrop-py`, or pixi resolves the wrong manifest).
- Known pre-existing failures, not yours: `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults`, `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions`, and two in `fluorescence_controller/tests/test_command_setter.py`.
- Never launch the GUI (the user tests manually). Never push.

---

### Task 1: Pixel area and its unit

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/scale_bar.py`
- Test: `fluorescence_controls_ui/tests/test_scale_bar.py`

**Interfaces:**
- Produces: `pixel_area(metres_per_pixel_value, unit) -> float`, `area_unit(metres_per_pixel_value, unit) -> str`. Tasks 2–4 import both.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_scale_bar.py`, extending its import with `area_unit, pixel_area`:

```python
def test_pixel_area_squares_the_calibration():
    # 10 µm per pixel, reported in mm: (0.01 mm)^2 = 1e-4 mm^2.
    assert abs(pixel_area(1e-5, "mm") - 1e-4) < 1e-12
    # The same calibration in µm: 10 µm x 10 µm = 100 µm^2.
    assert abs(pixel_area(1e-5, "µm") - 100.0) < 1e-9


def test_pixel_area_without_a_calibration_is_one_square_pixel():
    assert pixel_area(0.0, "mm") == 1.0
    assert pixel_area(-1.0, "mm") == 1.0


def test_area_unit_says_pixels_until_calibrated():
    assert area_unit(1e-5, "mm") == "mm²"
    assert area_unit(1e-5, "µm") == "µm²"
    assert area_unit(0.0, "mm") == "px²"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_scale_bar.py -q"`
Expected: ImportError on `area_unit`.

- [ ] **Step 3: Add the helpers** at the end of `scale_bar.py`:

```python
def pixel_area(metres_per_pixel_value, unit):
    """One pixel's area in ``unit`` squared; 1.0 (that is, px²) when
    there is no calibration, so every size-aware stat still
    computes."""
    if metres_per_pixel_value <= 0:
        return 1.0
    return (metres_per_pixel_value / UNIT_METRES[unit]) ** 2


def area_unit(metres_per_pixel_value, unit):
    """'mm²' when calibrated, 'px²' when not."""
    return f"{unit}²" if metres_per_pixel_value > 0 else "px²"
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_scale_bar.py -q"`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/scale_bar.py fluorescence_controls_ui/tests/test_scale_bar.py
git commit -m "feat(analysis): add pixel area and its unit label"
```

---

### Task 2: The five derived statistics

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_series.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py` (`PLOT_STATS`)
- Test: `fluorescence_controls_ui/tests/test_plot_series.py`

**Interfaces:**
- Consumes: `pixel_area` from Task 1.
- Produces: `stat_value(stats, stat, pixel_area=1.0)` handling `integrated`, `bg_integrated`, `per_area`, `bg_per_area` and `area`; `PLOT_STATS` including the four new plot stats. Tasks 3–4 rely on both.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_plot_series.py`:

```python
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
    session = AnalysisSession(rois=[roi], plot_stat="area")
    session.scale.trait_set(metres_per_pixel=1e-5, unit="mm")
    session.stats[session.cache_key(image, roi)] = {
        "mean": 10.0, "outline_mean": 4.0, "count": 25.0}

    _name, _elapsed, values = derive_series(session, [image])[roi.roi_id]
    assert abs(values[0] - 25.0 * 1e-4) < 1e-12
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_plot_series.py -q"`
Expected: the `area` stat returns NaN (unknown key) and `AnalysisSession(plot_stat="area")` raises a TraitError.

- [ ] **Step 3: Rewrite `stat_value`** in `plot_series.py`, replacing the whole function and adding the two helpers above it:

```python
def _signal(stats, background):
    """The mean, or the mean less the outline ring when
    ``background``. NaN when either piece is missing."""
    mean = stats.get("mean")
    if mean is None:
        return math.nan
    if not background:
        return mean
    outline = stats.get("outline_mean")
    return math.nan if outline is None else mean - outline


def _count(stats):
    """The interior pixel count, or NaN — which then propagates
    through whatever it is multiplied into."""
    count = stats.get("count")
    return math.nan if count is None else count


def stat_value(stats, stat, pixel_area=1.0):
    """The plotted value for one (image, ROI) stats dict — NaN when the
    stats are missing entirely or lack the pieces a stat needs.
    ``pixel_area`` is one pixel's area in the display unit (1.0 = px²),
    which the size-aware stats scale by."""
    if not stats:
        return math.nan
    if stat == "bg_corrected":
        return _signal(stats, True)
    if stat == "integrated":
        return _signal(stats, False) * _count(stats)
    if stat == "bg_integrated":
        return _signal(stats, True) * _count(stats)
    if stat == "per_area":
        return _signal(stats, False) / pixel_area
    if stat == "bg_per_area":
        return _signal(stats, True) / pixel_area
    if stat == "area":
        return _count(stats) * pixel_area
    value = stats.get(stat)
    return math.nan if value is None else value
```

Then have `derive_series` resolve the calibration once and pass it, importing `from ..scale_bar import pixel_area`:

```python
    stat_cache = {}
    area_per_pixel = pixel_area(session.scale.metres_per_pixel,
                                session.scale.unit)
```

and at the value site:

```python
            values.append(stat_value(stats, session.plot_stat,
                                     area_per_pixel))
```

The local is named `area_per_pixel` so it does not shadow the imported
`pixel_area` function.

- [ ] **Step 4: Widen `PLOT_STATS`** in `roi_model.py`:

```python
#: Stats the plot can show. "bg_corrected" is interior mean minus the
#: outline-ring mean — the standard fluorescence background correction
#: the ring exists for. The last four are size-aware: "integrated" is
#: the ROI's total signal, "per_area" its density (see the design note
#: — that one is the mean times a constant).
PLOT_STATS = ("mean", "bg_corrected", "median", "min", "max",
              "outline_mean", "integrated", "bg_integrated",
              "per_area", "bg_per_area")
```

- [ ] **Step 5: Run the series tests and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_plot_series.py -q"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_series.py fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/tests/test_plot_series.py
git commit -m "feat(analysis): derive integrated and per-area statistics"
```

---

### Task 3: Plot labels that carry the unit

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`

**Interfaces:**
- Consumes: `area_unit` from Task 1, `PLOT_STATS` from Task 2.
- Produces: `PLOT_STAT_LABELS` entries for the four new stats and `y_axis_label(plot_stat, scale)`.

- [ ] **Step 1: Add the labels and the composer** — extend `PLOT_STAT_LABELS` in `plot_pane.py`:

```python
    "outline_mean": "Outline ring mean",
    "integrated": "Integrated",
    "bg_integrated": "Integrated (bg-corrected)",
    "per_area": "Per area",
    "bg_per_area": "Per area (bg-corrected)",
}

#: Y-axis wording for the stats whose numbers mean nothing without
#: their unit; every other stat uses its plain label.
_Y_LABEL_TEMPLATES = {
    "per_area": "Intensity per {unit}",
    "bg_per_area": "Bg-corrected intensity per {unit}",
}


def y_axis_label(plot_stat, scale):
    """The y-axis text for a stat, with the area unit spliced in where
    the stat depends on it."""
    template = _Y_LABEL_TEMPLATES.get(plot_stat)
    if template is None:
        return PLOT_STAT_LABELS[plot_stat]
    return template.format(
        unit=area_unit(scale.metres_per_pixel, scale.unit))
```

importing `from ..scale_bar import area_unit`.

- [ ] **Step 2: Use it for the y-axis** — in `_refresh_intensity`, replace the ylabel line:

```python
    def _refresh_intensity(self, series, figure_settings):
        session = self._model.session
        self._axes.set_ylabel(y_axis_label(session.plot_stat,
                                           session.scale))
```

leaving the rest of the method as it is.

- [ ] **Step 3: Redraw when the calibration changes** — add to `_PLOT_STATE`, so a recalibration re-labels the axis:

```python
               "session:scale:metres_per_pixel, session:scale:unit, "
```

- [ ] **Step 4: Check it offscreen** — a throwaway in the scratchpad:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from fluorescence_controls_ui.image_viewer.analysis.plot_pane import (
    y_axis_label,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    ScaleCalibration,
)

uncalibrated = ScaleCalibration()
calibrated = ScaleCalibration(metres_per_pixel=1e-5, unit="mm")
print(y_axis_label("mean", uncalibrated))
print(y_axis_label("per_area", uncalibrated))
print(y_axis_label("per_area", calibrated))
print(y_axis_label("bg_per_area", calibrated))
assert y_axis_label("per_area", uncalibrated).endswith("px²")
assert y_axis_label("per_area", calibrated).endswith("mm²")
assert y_axis_label("integrated", calibrated) == "Integrated"
print("ok")
```

Run it; expected `ok` with the four labels printed.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_pane.py
git commit -m "feat(analysis): label the per-area axis with its unit"
```

---

### Task 4: The area column in the table and the CSV

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_table.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (the export call)
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: an `area` column in the stats table; `write_intensity_csv(csv_path, rows, rois, pixel_area=1.0, area_unit_label="px²")` writing five derived columns per ROI.

- [ ] **Step 1: Write the failing test** — replace the tail of `test_write_intensity_csv_layout` in `test_roi_store.py` (keep the rows fixture, extend the assertions) and add a second test:

```python
def test_write_intensity_csv_includes_the_derived_columns(tmp_path):
    roi = Roi(name="ROI 1", kind="box", geometry=[1.0, 1.0, 5.0, 5.0])
    rows = [{
        "filename": "img_raw.png", "time_utc": "2026_07_20-17_46_24",
        "elapsed_sec": 0.0, "group": "burst_a",
        "wavelength": "Green 540 nm",
        "stats": {roi.roi_id: {"mean": 10.0, "outline_mean": 4.0,
                               "count": 25.0}},
    }]
    csv_path = tmp_path / "out.csv"
    write_intensity_csv(csv_path, rows, [roi], pixel_area=1e-4,
                        area_unit_label="mm²")
    with open(csv_path, newline="", encoding="utf-8") as handle:
        records = list(csv.reader(handle))

    assert "ROI 1_area_mm²" in records[0]
    assert "ROI 1_integrated" in records[0]
    assert "ROI 1_bg_integrated" in records[0]
    assert "ROI 1_per_area" in records[0]
    assert "ROI 1_bg_per_area" in records[0]
    area = records[1][records[0].index("ROI 1_area_mm²")]
    assert abs(float(area) - 25.0 * 1e-4) < 1e-12
    integrated = records[1][records[0].index("ROI 1_integrated")]
    assert float(integrated) == 250.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: `TypeError: write_intensity_csv() got an unexpected keyword argument 'pixel_area'`.

- [ ] **Step 3: Extend the CSV writer** in `roi_store.py`:

```python
#: Per-ROI CSV columns, in order: interior stats, outline stats, then
#: the values derived from the pixel count and the scale.
CSV_STAT_COLUMNS = tuple(STAT_NAMES) + tuple(
    OUTLINE_STATS_PREFIX + name for name in STAT_NAMES)
CSV_DERIVED_COLUMNS = ("area", "integrated", "bg_integrated",
                       "per_area", "bg_per_area")


def write_intensity_csv(csv_path, rows, rois, pixel_area=1.0,
                        area_unit_label="px²"):
    """One row per image, blank cells where an (image, ROI) pair has no
    computed stats. ``rows``: [{"filename", "time_utc", "elapsed_sec",
    "group", "wavelength", "stats": {roi_id: stats_dict}}, ...].
    ``pixel_area`` scales the derived size-aware columns; it is 1.0
    (px²) for an uncalibrated experiment."""
    header = ["index", "time_utc", "elapsed_sec", "filename", "group",
              "wavelength"]
    for roi in rois:
        header += [f"{roi.name}_{stat}" for stat in CSV_STAT_COLUMNS]
        header += [f"{roi.name}_area_{area_unit_label}"]
        header += [f"{roi.name}_{stat}"
                   for stat in CSV_DERIVED_COLUMNS[1:]]
    # utf-8, not the platform default: the area header carries µ and ².
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index, row in enumerate(rows):
            record = [index, row["time_utc"], row["elapsed_sec"],
                      row["filename"], row["group"], row["wavelength"]]
            for roi in rois:
                stats = row["stats"].get(roi.roi_id, {})
                record += [stats.get(stat, "")
                           for stat in CSV_STAT_COLUMNS]
                record += [_csv_cell(stats, stat, pixel_area)
                           for stat in CSV_DERIVED_COLUMNS]
            writer.writerow(record)


def _csv_cell(stats, stat, pixel_area):
    """A derived value, blank where the stats cannot supply it — the
    same empty cell an uncomputed image already writes."""
    value = stat_value(stats, stat, pixel_area)
    return "" if value != value else value
```

with `from .plot_series import stat_value` at the top.

- [ ] **Step 4: Pass the calibration at the export site** — in `roi_controller.py`, where `write_intensity_csv` is called (~line 490), importing `area_unit, pixel_area` from `..scale_bar`:

```python
            scale = session.scale
            write_intensity_csv(
                csv_path, rows, session.rois,
                pixel_area(scale.metres_per_pixel, scale.unit),
                area_unit(scale.metres_per_pixel, scale.unit))
```

- [ ] **Step 5: Add the table column** — in `roi_table.py`:

```python
_STAT_COLUMNS = ("mean", "bg_corrected", "median", "min", "max",
                 "count", "area")
```

Move the header assignment out of `__init__` and into `_rebuild`, so the unit tracks the calibration:

```python
        scale = session.scale
        area_per_pixel = pixel_area(scale.metres_per_pixel, scale.unit)
        self.setHorizontalHeaderLabels(
            [f"Area ({area_unit(scale.metres_per_pixel, scale.unit)})"
             if header == "area" else header for header in _HEADERS])
```

and pass `area_per_pixel` into both `stat_value` calls (in `_rebuild`
and in `_refresh_values`, which resolves its own copy the same way).
Extend `_TABLE_STRUCTURE` with `"session:scale:metres_per_pixel, session:scale:unit, "` so recalibrating rebuilds rather than leaving a stale header, and import `area_unit, pixel_area` from `...scale_bar`.

- [ ] **Step 6: Run the whole controls_ui suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests -q"`
Expected: only the two known pre-existing failures. `test_write_intensity_csv_layout` still passes — its assertions index columns by name — but give its `open(csv_path, newline="")` an `encoding="utf-8"` too, so it reads the file the way the writer now writes it rather than relying on cp1252 happening to decode those bytes.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_table.py fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(analysis): report ROI area in the table and the CSV"
```

---

### Task 5: Offscreen verification

**Files:**
- Create (scratchpad, never committed): `C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_area_stats.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the smoke script**

```python
"""Offscreen smoke for the area statistics: every new stat draws on the
demo experiment, the y-label carries the unit, and the table grows its
area column with the calibration's unit in the header."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from fluorescence_controls_ui.image_viewer.analysis.plot_pane import (
    RoiPlotCanvas,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    roi_analysis_model,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_stats, load_session,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_table import (
    RoiStatsTable,
)
from fluorescence_controls_ui.image_viewer.discovery import (
    discover_captures,
)

experiment_dir = Path(sys.argv[1]).resolve()
session = load_session(experiment_dir)
session.stats = load_roi_stats(experiment_dir)
session.figure.view_mode = "intensity"
session.scale.trait_set(metres_per_pixel=1e-5, unit="mm")
roi_analysis_model.session = session
roi_analysis_model.filtered_paths = [
    str(path) for path in discover_captures(experiment_dir / "captures")]

canvas = RoiPlotCanvas(roi_analysis_model)
canvas.show()

for stat in ("mean", "integrated", "bg_integrated", "per_area",
             "bg_per_area"):
    session.plot_stat = stat
    canvas._refresh()
    canvas.figure.canvas.draw()
    lines = [line for line in canvas._lines.values()
             if len(line.get_ydata())]
    assert lines, f"{stat} drew no data"
    first = list(lines[0].get_ydata())[:2]
    print(f"{stat:14s} ylabel={canvas._axes.get_ylabel()!r} "
          f"first={[round(value, 3) for value in first]}")

session.plot_stat = "per_area"
canvas._refresh()
assert canvas._axes.get_ylabel().endswith("mm²")
session.scale.metres_per_pixel = 0.0
canvas._refresh()
assert canvas._axes.get_ylabel().endswith("px²"), \
    canvas._axes.get_ylabel()
print("uncalibrated axis falls back to px²")

session.scale.trait_set(metres_per_pixel=1e-5, unit="mm")
table = RoiStatsTable(roi_analysis_model)
table._rebuild()
headers = [table.horizontalHeaderItem(column).text()
           for column in range(table.columnCount())]
print(f"table headers: {headers}")
assert "Area (mm²)" in headers
area_column = headers.index("Area (mm²)")
print(f"first ROI area cell: {table.item(0, area_column).text()!r}")
assert table.item(0, area_column).text()
print("smoke passed")
```

- [ ] **Step 2: Run it against the regenerated demo**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && PYTHONIOENCODING=utf-8 python 'C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_area_stats.py' 'C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/fit_demo_experiment'"`
Expected: "smoke passed", with `integrated` values around the disk area times its mean, and `per_area` an exact 10⁴× the mean curve (1e-4 mm² per pixel).

- [ ] **Step 3: Run every suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui fluorescence_controller fluorescence_protocol_controls -q"`
Expected: only the four known pre-existing failures.

- [ ] **Step 4: Report to the user**

Summarize: the four new plot stats and what each answers, that area now reads in the table and the CSV in the calibration's unit, that `per_area` is the mean rescaled (so its curve shape matches the mean plot — by arithmetic, not by bug), that each ROI's CSV block grew from 13 to 18 columns, and that nothing is pushed.
