# Plot Transforms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log X, log Y and 0–100% normalization on the ROI plot, each independently switchable, with the normalized series exported alongside the raw one.

**Architecture:** Log is a display scale applied in `_refresh`'s shared tail; normalization is a data transform applied once after `visible_series` so every view sees the same numbers. Both are persisted `FigureSettings` booleans driving in-place toggles.

**Tech Stack:** matplotlib axis scales, Traits/TraitsUI, pure-Python series maths.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-plot-transforms-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- Normalization is `(value − min) / (max − min) × 100` per ROI over finite values; NaN stays NaN; `min == max` yields 0.0.
- Axis scales must be set **after** the `AutoLocator`/`ScalarFormatter` reset at the top of `_refresh` (they would fight the log locators) and **before** `relim`.
- Source files are UTF-8 (`²`, `−` appear in labels); pass `encoding="utf-8"` to any `pathlib.write_text` you add, and run scripts with `PYTHONIOENCODING=utf-8`.
- f-strings everywhere; module-level imports; no aliasing of constants; conventional commits.
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/<file> -q"` (always from `microdrop-py`).
- Known pre-existing failures, not yours: `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults`, `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions`, and two in `fluorescence_controller/tests/test_command_setter.py`.
- Never launch the GUI. Never push.

---

### Task 1: The normalizer

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_series.py`
- Test: `fluorescence_controls_ui/tests/test_plot_series.py`

**Interfaces:**
- Produces: `normalized_series(series) -> dict` in the same `{roi_id: (name, elapsed, values)}` shape. Tasks 2 and 4 both call it.

- [ ] **Step 1: Write the failing tests** — append to `test_plot_series.py`, extending its import with `normalized_series`:

```python
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
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_plot_series.py -q"`
Expected: ImportError on `normalized_series`.

- [ ] **Step 3: Write it** — append to `plot_series.py`:

```python
def normalized_series(series):
    """``series`` with each ROI stretched to 0-100% of its own finite
    range, so curves of wildly different brightness can be compared for
    shape and timing. NaN stays NaN, so a gap stays a gap; a curve with
    no range (min == max) sits flat at 0%, there being nothing to
    stretch and no span to divide by."""
    scaled = {}
    for roi_id, (name, elapsed, values) in series.items():
        finite = [value for value in values if value == value]
        low = min(finite) if finite else 0.0
        span = (max(finite) - low) if finite else 0.0
        scaled[roi_id] = (name, elapsed, [
            value if value != value
            else (0.0 if span == 0 else (value - low) / span * 100.0)
            for value in values])
    return scaled
```

- [ ] **Step 4: Run them and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_plot_series.py -q"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_series.py fluorescence_controls_ui/tests/test_plot_series.py
git commit -m "feat(analysis): normalise each ROI series to its own range"
```

---

### Task 2: The three toggles and what they do

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py` (`FigureSettings`)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py` (`_FIGURE_FIELDS`)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (persistence observer)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Consumes: `normalized_series` from Task 1.
- Produces: `FigureSettings.log_x`, `.log_y`, `.normalize`; `y_axis_label(plot_stat, scale, normalize)`.

- [ ] **Step 1: Write the failing test** — extend `test_figure_fit_settings_round_trip` in `test_roi_store.py`:

```python
    session.figure.trim_poor_fit = True
    session.figure.log_x = True
    session.figure.normalize = True
```

and its assertions:

```python
    assert loaded.figure.trim_poor_fit is True
    assert loaded.figure.log_x is True and loaded.figure.log_y is False
    assert loaded.figure.normalize is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: `AttributeError` / `TraitError` on `log_x`.

- [ ] **Step 3: Add the traits** — in `roi_model.py`'s `FigureSettings`, beside `trim_poor_fit`:

```python
    #: Display scales (the data and the fits are untouched) and the
    #: 0-100% per-ROI normalisation (which rewrites the values).
    log_x = Bool(False)
    log_y = Bool(False)
    normalize = Bool(False)
```

Add `"log_x", "log_y", "normalize"` to `_FIGURE_FIELDS` in `roi_store.py`, and the three clauses to the plot-settings observer in `roi_controller.py`:

```python
             "analysis_model:session:figure:log_x, "
             "analysis_model:session:figure:log_y, "
             "analysis_model:session:figure:normalize, "
```

- [ ] **Step 4: Apply the normalization and the label** — in `plot_pane.py`, extend the label composer:

```python
def y_axis_label(plot_stat, scale, normalize=False):
    """The y-axis text for a stat, with the area unit spliced in where
    the stat depends on it and the normalisation noted where it
    applies."""
    template = _Y_LABEL_TEMPLATES.get(plot_stat)
    label = (PLOT_STAT_LABELS[plot_stat] if template is None
             else template.format(
                 unit=area_unit(scale.metres_per_pixel, scale.unit)))
    return f"{label} (% of range)" if normalize else label
```

its caller in `_refresh_intensity`:

```python
        self._axes.set_ylabel(y_axis_label(session.plot_stat,
                                           session.scale,
                                           figure_settings.normalize))
```

and the transform itself in `_refresh`, right after the visibility filter:

```python
        series = visible_series(self._model.session, derived)
        figure_settings = self._model.session.figure
        if figure_settings.normalize:
            # Once, before any view draws, so the lines, the fits, the
            # d² curves and the bars cannot disagree.
            series = normalized_series(series)
```

importing `normalized_series` beside `visible_series`.

- [ ] **Step 5: Add the toggles** — in `_plot_controls_view`, a fourth `HGroup` after the d² row:

```python
        HGroup(
            UItem("figure.log_x",
                  editor=InPlaceToggleEditor(on_label="Log X",
                                             off_label="Log X"),
                  tooltip="Logarithmic time axis. Points at t = 0 "
                          "cannot be drawn on it and are counted in a "
                          "note on the figure."),
            UItem("figure.log_y",
                  editor=InPlaceToggleEditor(on_label="Log Y",
                                             off_label="Log Y"),
                  tooltip="Logarithmic value axis. Zero and negative "
                          "values cannot be drawn on it and are "
                          "counted in a note on the figure."),
            UItem("figure.normalize",
                  editor=InPlaceToggleEditor(on_label="Normalize",
                                             off_label="Normalize"),
                  tooltip="Stretch each ROI to 0-100% of its own "
                          "range, to compare shape and timing. Fitted "
                          "midpoints and R² are unchanged; amplitudes "
                          "become percentages."),
        ),
```

and add `session:figure:log_x`, `log_y` and `normalize` to `_PLOT_STATE`.

- [ ] **Step 6: Run the store tests**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/analysis/plot_pane.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(analysis): add log and normalise plot toggles"
```

---

### Task 3: The axis scales and the hidden-point note

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py` (`_refresh` tail)

**Interfaces:**
- Consumes: Task 2's traits.
- Produces: log scales applied to the time-axis views, manual limits skipped where a log axis would reject them, and a hint counting points a log axis hides.

- [ ] **Step 1: Apply the scales and guard the limits** — replace `_refresh`'s tail (from `self._axes.relim()` to `self.draw_idle()`):

```python
        # After the locator reset above (which would fight the log
        # locators) and before relim, so autoscale sees the final
        # scale. The bar view keeps linear: its x is ROI names.
        time_axis = figure_settings.view_mode != "fastest_change"
        log_x = time_axis and figure_settings.log_x
        log_y = time_axis and figure_settings.log_y
        self._axes.set_xscale("log" if log_x else "linear")
        self._axes.set_yscale("log" if log_y else "linear")
        self._axes.relim()
        self._axes.autoscale_view()
        # A log axis rejects a limit at or below zero, so a manual one
        # is skipped there and the autoscaled range stands.
        if (not figure_settings.x_auto and time_axis
                and not (log_x and figure_settings.x_min <= 0)):
            self._axes.set_xlim(figure_settings.x_min,
                                figure_settings.x_max)
        if (not figure_settings.y_auto
                and not (log_y and figure_settings.y_min <= 0)):
            self._axes.set_ylim(figure_settings.y_min,
                                figure_settings.y_max)
        self._shade_trimmed_tails(trim_edges)
        self._note_hidden_points(series, log_x, log_y)
        self.draw_idle()
```

- [ ] **Step 2: Add the note** — beside `_draw_hint`:

```python
    def _note_hidden_points(self, series, log_x, log_y):
        """Matplotlib drops non-positive values on a log axis without a
        word, and two cases are certain rather than hypothetical:
        elapsed time starts at 0, and a normalised curve's minimum is
        exactly 0. Count them instead of letting data vanish."""
        if not (log_x or log_y):
            return
        hidden = 0
        for _name, elapsed, values in series.values():
            for time, value in zip(elapsed, values):
                if value != value:
                    continue        # already a gap, not a casualty
                if (log_x and time <= 0) or (log_y and value <= 0):
                    hidden += 1
        if not hidden:
            return
        self._fit_artists.append(self._axes.text(
            0.5, 0.02,
            f"Log axis hides {hidden} non-positive "
            f"{'point' if hidden == 1 else 'points'}",
            transform=self._axes.transAxes, ha="center",
            va="bottom", color="gray", fontsize="x-small"))
```

- [ ] **Step 3: Check it offscreen** — a throwaway in the scratchpad that builds a canvas over the demo experiment, sets each toggle, and prints `canvas._axes.get_xscale()`, `get_yscale()` and the hint texts. Confirm: log X alone gives `('log', 'linear')` and a hint counting one point per ROI (t = 0); the fastest-change view stays `('linear', 'linear')` with both toggles on.

- [ ] **Step 4: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_pane.py
git commit -m "feat(analysis): apply log scales and count hidden points"
```

---

### Task 4: The normalized CSV column

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (the export call)
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Consumes: `normalized_series` from Task 1.
- Produces: `write_intensity_csv(..., normalize_stat=None)` adding one `<roi>_<stat>_norm_pct` column per ROI when set.

- [ ] **Step 1: Write the failing test** — append to `test_roi_store.py`:

```python
def test_write_intensity_csv_adds_the_normalised_column(tmp_path):
    roi = Roi(name="ROI 1", kind="box", geometry=[1.0, 1.0, 5.0, 5.0])
    rows = [{
        "filename": f"img{index}_raw.png",
        "time_utc": "2026_07_20-17_46_24", "elapsed_sec": float(index),
        "group": "burst_a", "wavelength": "Green 540 nm",
        "stats": {roi.roi_id: {"mean": mean, "count": 4.0}},
    } for index, mean in enumerate((10.0, 20.0, 30.0))]
    csv_path = tmp_path / "out.csv"
    write_intensity_csv(csv_path, rows, [roi], normalize_stat="mean")
    with open(csv_path, newline="", encoding="utf-8") as handle:
        records = list(csv.reader(handle))

    column = records[0].index("ROI 1_mean_norm_pct")
    assert [records[row][column] for row in (1, 2, 3)] == \
        ["0.0", "50.0", "100.0"]


def test_write_intensity_csv_omits_the_column_when_not_normalising(
        tmp_path):
    roi = Roi(name="ROI 1", kind="box", geometry=[1.0, 1.0, 5.0, 5.0])
    rows = [{
        "filename": "img_raw.png", "time_utc": "2026_07_20-17_46_24",
        "elapsed_sec": 0.0, "group": "burst_a",
        "wavelength": "Green 540 nm",
        "stats": {roi.roi_id: {"mean": 10.0, "count": 4.0}},
    }]
    csv_path = tmp_path / "out.csv"
    write_intensity_csv(csv_path, rows, [roi])
    with open(csv_path, newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert not [name for name in header if name.endswith("_norm_pct")]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: `TypeError` on `normalize_stat`.

- [ ] **Step 3: Add the column** — in `roi_store.py`, importing `normalized_series` beside `stat_value`:

```python
def _normalised_columns(rows, rois, normalize_stat, pixel_area):
    """{roi_id: [cell, ...]} for the normalised column, run through the
    plot's own normaliser so a CSV column and its curve can never
    disagree."""
    series = {
        roi.roi_id: (roi.name, list(range(len(rows))),
                     [stat_value(row["stats"].get(roi.roi_id, {}),
                                 normalize_stat, pixel_area)
                      for row in rows])
        for roi in rois}
    return {roi_id: ["" if value != value else value
                     for value in values]
            for roi_id, (_name, _elapsed, values)
            in normalized_series(series).items()}
```

and thread it through `write_intensity_csv`:

```python
def write_intensity_csv(csv_path, rows, rois, pixel_area=1.0,
                        area_unit_label="px²", normalize_stat=None):
```

with the header addition inside the per-ROI loop:

```python
        if normalize_stat is not None:
            header += [f"{roi.name}_{normalize_stat}_norm_pct"]
```

before opening the file:

```python
    normalised = ({} if normalize_stat is None
                  else _normalised_columns(rows, rois, normalize_stat,
                                           pixel_area))
```

and in the row loop, after the derived cells:

```python
                if normalize_stat is not None:
                    record += [normalised[roi.roi_id][index]]
```

- [ ] **Step 4: Pass it from the export** — in `roi_controller.py`:

```python
            write_intensity_csv(
                csv_path, rows, session.rois,
                pixel_area(scale.metres_per_pixel, scale.unit),
                area_unit(scale.metres_per_pixel, scale.unit),
                session.plot_stat if session.figure.normalize else None)
```

- [ ] **Step 5: Run the store tests and the full controls_ui suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests -q"`
Expected: only the two known pre-existing failures.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(analysis): export the normalised series beside the raw"
```

---

### Task 5: Offscreen verification

**Files:**
- Create (scratchpad, never committed): `C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_transforms.py`

- [ ] **Step 1: Write the smoke script** covering, against the demo experiment:

  - each toggle alone and all three together, asserting `get_xscale()`/`get_yscale()` match and that `_refresh` never raises;
  - normalization putting every visible curve's finite values inside 0–100 with at least one 0 and one 100;
  - the hidden-point hint appearing with log X on (elapsed starts at 0) and its count equalling the number of visible ROIs;
  - the fastest-change view staying linear with both log toggles on;
  - **the invariance this design leans on**: with `fit_method="sigmoid"`, `fit_series` on the raw and on the normalized values of the same ROI agreeing on `params["midpoint"]` to within 1e-6 and on `r_squared` to within 1e-9, while `params["amplitude"]` differs.

- [ ] **Step 2: Run it**

Run it with `PYTHONIOENCODING=utf-8` against `<scratchpad>/fit_demo_experiment`; expected "smoke passed" with the scales and the midpoint comparison printed.

- [ ] **Step 3: Run every suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui fluorescence_controller fluorescence_protocol_controls -q"`
Expected: only the four known pre-existing failures.

- [ ] **Step 4: Report to the user**

Summarize: the three toggles and that they combine; that log is display-only so fits keep their meaning while normalization rewrites the values; the measured invariance of midpoint and R²; the hidden-point note and why it exists; the new CSV column; and that nothing is pushed.
