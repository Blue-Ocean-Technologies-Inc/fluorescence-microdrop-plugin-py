# ROI Analysis Persistence and Plot Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist computed ROI stats per experiment so plots auto-load on
return, make the plot pane a self-deriving observer, and add ROI
renaming, per-ROI plot styling, a live stats table, and publication
export.

**Architecture:** A new `AnalysisSession` HasTraits object carries all
per-experiment state (ROIs + styles, stats store, plot stat, figure
settings) and is swapped wholesale on experiment change; two JSON files
under `<experiment>/analysis/` persist it. The plot pane observes the
session and derives its own series; the viewer controller keeps thin
`filtered_paths` / `current_image_path` mirrors on the shared model so
panes never touch the viewer model.

**Tech Stack:** Traits/TraitsUI, PySide6, matplotlib QtAgg, pytest.
Spec: `docs/superpowers/specs/2026-07-31-roi-analysis-persistence-and-plot-styling-design.md`.

## Global Constraints

- Repo: `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py\src\fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis` (continue on it; base commit `08a3518`).
- Run tests from `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py`: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/<file> -q`
- Known pre-existing full-suite failures (do NOT touch): `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults` (suite-ordering interference) and `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions` (references a method that never existed).
- Conventions: f-strings only; module-level imports (EXCEPTION: `capture_service` must only ever be imported lazily inside functions — documented constraint); constants UPPER_SNAKE_CASE in the package `consts.py` unless single-consumer; logger via `from logger.logger_service import get_logger`; dialogs via `microdrop_application.dialogs.pyface_wrapper` compared to `pyface.api` YES/NO; comments state constraints, never narrate edits.
- Model traits are mutated ONLY on the GUI thread. Worker threads talk through the runner's queue.
- Traits observe mini-language: dot form (`rois.items`) fires on wholesale replacement AND item mutation; colon form does not. Nested Instance traits must be enumerated explicitly (no `:+` patterns).
- Commit after every task, conventional-commit style, never `--no-verify`.
- Suggested implementer tiers: haiku for verbatim transcription tasks (1, 2), sonnet for integration tasks (3–9), reviews on sonnet.

---

### Task 1: Session, style, and figure traits

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
- Test: `fluorescence_controls_ui/tests/test_analysis_session.py` (new)

**Interfaces:**
- Consumes: existing `Roi`, `capture_timestamp`.
- Produces: `RoiStyle(HasTraits)` (`color: Str hex`, `line_style: Enum("solid","dashed","dotted","dashdot")`, `marker: Enum("none",".","o","s","^","x")`, `marker_size: Float(4.0)`); `FigureSettings(HasTraits)` (`x_auto/y_auto: Bool(True)`, `x_min/x_max/y_min/y_max: Float`, `export_format: Enum("png","svg","pdf","tiff")`, `export_dpi: Enum(300,150,600)`); `PLOT_STATS` tuple; `AnalysisSession(HasTraits)` with `directory: Str`, `rois: List(Instance(Roi))`, `stats: Dict`, `stats_revision: Int`, `plot_stat: Enum(*PLOT_STATS)`, `figure: Instance(FigureSettings, ())` and methods `roi_by_id`, `next_roi_name`, `stat_info`, `cache_key`, `effective_for` (same signatures/bodies as today's model methods); `Roi.style: Instance(RoiStyle, ())`; `RoiAnalysisModel.session: Instance(AnalysisSession, ())`, `filtered_paths: List(Str)`, `current_image_path: Str`; `DEFAULT_ROI_COLORS` in consts. Old model traits are NOT removed yet (Task 3 does that).

- [ ] **Step 1: Add constants**

Append to `analysis/consts.py`:

```python
#: Default per-ROI plot colors, cycled at creation (matplotlib tab10).
DEFAULT_ROI_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)

#: Persisted computed-stats store inside ANALYSIS_DIR_NAME.
ROI_STATS_FILENAME = "roi_stats.json"

#: Minimum seconds between debounced writes of the stats store.
STATS_SAVE_DEBOUNCE_S = 2.0
```

- [ ] **Step 2: Add the traits classes**

In `roi_model.py`, after the `Roi` class (keep everything existing —
`RoiAnalysisModel` methods stay in place until Task 3), add:

```python
#: Stats the plot can show. "bg_corrected" is interior mean minus the
#: outline-ring mean — the standard fluorescence background correction
#: the ring exists for.
PLOT_STATS = ("mean", "bg_corrected", "median", "min", "max", "outline_mean")


class RoiStyle(HasTraits):
    """Plot styling for one ROI's line (persisted per experiment)."""

    color = Str("#1f77b4")
    line_style = Enum("solid", "dashed", "dotted", "dashdot")
    marker = Enum("none", ".", "o", "s", "^", "x")
    marker_size = Float(4.0)


class FigureSettings(HasTraits):
    """Figure-level plot settings (axis limits and export defaults)."""

    x_auto = Bool(True)
    x_min = Float(0.0)
    x_max = Float(1.0)
    y_auto = Bool(True)
    y_min = Float(0.0)
    y_max = Float(1.0)
    export_format = Enum("png", "svg", "pdf", "tiff")
    export_dpi = Enum(300, 150, 600)


class AnalysisSession(HasTraits):
    """Everything belonging to one experiment's analysis, swapped
    wholesale when the browsed experiment changes: the ROI set, the
    computed-stats store, and the plot configuration."""

    #: Experiment directory this session was loaded from ('' = none).
    directory = Str()

    rois = List(Instance(Roi))

    #: (path str, mtime, roi_id, kind, geometry tuple) -> stats dict.
    #: The geometry in the key makes invalidation implicit: an edit only
    #: misses on the images its override actually covers.
    stats = Dict()

    #: Bumped after every drain absorption and after a store load — Dict
    #: item writes don't notify, so observers watch this instead.
    stats_revision = Int(0)

    #: Which stat the plot shows.
    plot_stat = Enum(*PLOT_STATS)

    figure = Instance(FigureSettings, ())

    def roi_by_id(self, roi_id):
        for roi in self.rois:
            if roi.roi_id == roi_id:
                return roi
        return None

    def next_roi_name(self):
        """'ROI N' with N one past the highest numbered existing ROI
        name, so a deleted ROI's number isn't reissued to collide with
        a surviving one (duplicate names would double up CSV columns
        and plot legend labels)."""
        highest = 0
        for roi in self.rois:
            match = ROI_NAME_PATTERN.match(roi.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"ROI {highest + 1}"

    def stat_info(self, path, stat_cache=None):
        """(mtime, capture_time) for ``path``. Pass a dict as
        ``stat_cache`` (path str -> (mtime, capture_time)) to memoize
        the filesystem stat and timestamp parse across many calls in
        the same pass (a rebuild calls this once per image, cache_key()
        once per image per ROI)."""
        key = str(path)
        if stat_cache is not None and key in stat_cache:
            return stat_cache[key]
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        info = (mtime, capture_timestamp(path))
        if stat_cache is not None:
            stat_cache[key] = info
        return info

    def cache_key(self, path, roi, stat_cache=None):
        """Cache key for one (image, ROI) pair: the file identity/mtime
        plus the geometry in force at the image's capture time. Pass
        ``stat_cache`` through from stat_info() to avoid re-stating the
        same path for every ROI."""
        mtime, capture_time = self.stat_info(path, stat_cache)
        return (
            str(path),
            mtime,
            roi.roi_id,
            roi.kind,
            tuple(roi.effective_geometry(capture_time)),
        )

    def effective_for(self, path):
        """[(roi_id, name, kind, geometry), ...] in force for ``path`` —
        what the canvas draws and the batch computes for that image."""
        capture_time = capture_timestamp(path)
        return [
            (roi.roi_id, roi.name, roi.kind, roi.effective_geometry(capture_time))
            for roi in self.rois
        ]
```

Add to `Roi` (after `overrides`):

```python
    #: Plot styling (line color/style/marker); persisted with the ROI.
    style = Instance(RoiStyle, ())
```

`RoiStyle` is defined after `Roi` in the file, so instead define
`RoiStyle`, `FigureSettings`, and `PLOT_STATS` ABOVE the `Roi` class
(right after `ROI_NAME_PATTERN`), and `AnalysisSession` after `Roi`.

Add to `RoiAnalysisModel` (after `canvas_roi_edited`):

```python
    #: The per-experiment analysis state (swapped on experiment change).
    session = Instance(AnalysisSession, ())

    #: Mirrors of the viewer's filtered image list and displayed image
    #: (str paths), maintained by RoiAnalysisController so the plot
    #: pane and stats table never need the viewer model.
    filtered_paths = List(Str)
    current_image_path = Str()
```

- [ ] **Step 3: Write the tests**

Create `fluorescence_controls_ui/tests/test_analysis_session.py`:

```python
"""Session-object unit tests: defaults, name sequencing, and the
geometry-hashed cache keys on the session."""

from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession,
    PLOT_STATS,
    Roi,
    RoiAnalysisModel,
)


def test_session_defaults_are_empty_and_mean():
    session = AnalysisSession()
    assert session.directory == ""
    assert session.rois == []
    assert session.stats == {}
    assert session.plot_stat == "mean"
    assert session.figure.x_auto and session.figure.y_auto
    assert session.figure.export_dpi == 300
    assert session.figure.export_format == "png"
    assert "bg_corrected" in PLOT_STATS


def test_roi_default_style_and_session_name_sequence():
    session = AnalysisSession()
    roi = Roi(name=session.next_roi_name(), kind="circle", geometry=[10.0, 10.0, 5.0])
    assert roi.style.line_style == "solid"
    assert roi.style.marker == "none"
    session.rois.append(roi)
    assert session.next_roi_name() == "ROI 2"
    assert session.roi_by_id(roi.roi_id) is roi
    assert session.roi_by_id("nope") is None


def test_session_cache_key_uses_effective_geometry(tmp_path):
    image = tmp_path / "a_2026_07_20-10_00_00_raw.png"
    image.write_bytes(b"")
    roi = Roi(name="ROI 1", kind="circle", geometry=[5.0, 5.0, 2.0])
    session = AnalysisSession(rois=[roi])
    key = session.cache_key(str(image), roi)
    assert key[2] == roi.roi_id and key[3] == "circle"
    assert key[4] == (5.0, 5.0, 2.0)


def test_model_gains_session_and_mirrors():
    model = RoiAnalysisModel()
    assert isinstance(model.session, AnalysisSession)
    assert model.filtered_paths == []
    assert model.current_image_path == ""
```

- [ ] **Step 4: Run the new tests and the existing model tests**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py -q`
Expected: all pass (old model traits untouched).

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/consts.py fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/tests/test_analysis_session.py
git commit -m "feat(analysis): add AnalysisSession, RoiStyle, FigureSettings traits"
```

---

### Task 2: Session and stats persistence in roi_store

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py`
- Test: `fluorescence_controls_ui/tests/test_roi_store.py` (extend)

**Interfaces:**
- Consumes: `AnalysisSession`, `RoiStyle`, `FigureSettings`, `Roi`, `ROI_STATS_FILENAME` (Task 1).
- Produces: `save_session(experiment_directory, session)` and `load_session(experiment_directory) -> AnalysisSession` (v2 config format, v1 bare-list fallback); `save_roi_stats(experiment_directory, stats)` and `load_roi_stats(experiment_directory) -> dict` (lossless store round-trip). `save_roi_config`/`load_roi_config` are DELETED in this task; the controller call sites switch in Task 3, so this task also updates the controller's imports/two call sites minimally (see Step 3) to keep the suite green.

- [ ] **Step 1: Write the failing tests**

Replace the config tests in `test_roi_store.py` (keep the CSV test) so the file tests the new API:

```python
"""Persistence tests: session config round-trip (v2 + v1 fallback),
stats-store round-trip, and the CSV export layout."""

import json
import math

from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession,
    Roi,
    RoiStyle,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_stats,
    load_session,
    save_roi_stats,
    save_session,
)


def test_session_round_trip_preserves_rois_styles_and_figure(tmp_path):
    roi = Roi(
        name="Cell body",
        kind="box",
        geometry=[1.0, 2.0, 30.0, 40.0],
        base_anchor=100.0,
        overrides={200.0: [5.0, 6.0, 30.0, 40.0]},
        style=RoiStyle(
            color="#d62728", line_style="dashed", marker="o", marker_size=7.0
        ),
    )
    session = AnalysisSession(
        directory=str(tmp_path), rois=[roi], plot_stat="bg_corrected"
    )
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


def test_load_session_accepts_v1_bare_list(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text(
        json.dumps(
            [
                {
                    "roi_id": "abcd1234",
                    "name": "ROI 1",
                    "kind": "circle",
                    "geometry": [10.0, 10.0, 5.0],
                    "base_anchor": 0.0,
                    "overrides": {},
                }
            ]
        )
    )
    loaded = load_session(tmp_path)
    (roi,) = loaded.rois
    assert roi.roi_id == "abcd1234" and roi.kind == "circle"
    assert loaded.plot_stat == "mean"  # defaults fill in
    assert roi.style.line_style == "solid"


def test_load_session_missing_or_corrupt_is_empty(tmp_path):
    assert load_session(tmp_path).rois == []
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text("{nope")
    assert load_session(tmp_path).rois == []


def test_stats_store_round_trip_including_nan(tmp_path):
    key = (str(tmp_path / "a_raw.png"), 123.5, "abcd1234", "circle", (10.0, 10.0, 5.0))
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
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py -q`
Expected: FAIL with ImportError (`load_session` not defined).

- [ ] **Step 3: Implement the store**

In `roi_store.py`: change the imports/docstring and replace
`save_roi_config`/`load_roi_config` with:

```python
"""Persistence for the ROI analysis: the per-experiment session config
(roi_config.json v2 — ROIs with styles, plot stat, figure settings),
the computed-stats store (roi_stats.json), and the intensity CSV
export. Qt-free, pure file IO."""

import csv
import json
from pathlib import Path

from logger.logger_service import get_logger

from .consts import (
    ANALYSIS_DIR_NAME,
    OUTLINE_STATS_PREFIX,
    ROI_CONFIG_FILENAME,
    ROI_STATS_FILENAME,
)
from .roi_compute import STAT_NAMES
from .roi_model import AnalysisSession, FigureSettings, Roi, RoiStyle

logger = get_logger(__name__)

#: Persisted FigureSettings fields (also the tolerated-missing set on
#: load, so older configs upgrade with defaults).
_FIGURE_FIELDS = (
    "x_auto",
    "x_min",
    "x_max",
    "y_auto",
    "y_min",
    "y_max",
    "export_format",
    "export_dpi",
)
_STYLE_FIELDS = ("color", "line_style", "marker", "marker_size")


def analysis_directory(experiment_directory) -> Path:
    """The experiment's analysis output folder, created on demand."""
    directory = Path(experiment_directory) / ANALYSIS_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_session(experiment_directory, session):
    payload = {
        "version": 2,
        "plot_stat": session.plot_stat,
        "figure": {name: getattr(session.figure, name) for name in _FIGURE_FIELDS},
        "rois": [
            {
                "roi_id": roi.roi_id,
                "name": roi.name,
                "kind": roi.kind,
                "geometry": list(roi.geometry),
                "base_anchor": roi.base_anchor,
                "overrides": {
                    repr(anchor): list(geometry)
                    for anchor, geometry in roi.overrides.items()
                },
                "style": {name: getattr(roi.style, name) for name in _STYLE_FIELDS},
            }
            for roi in session.rois
        ],
    }
    path = analysis_directory(experiment_directory) / ROI_CONFIG_FILENAME
    path.write_text(json.dumps(payload, indent=2))


def _roi_from(entry):
    style = RoiStyle()
    style.trait_set(
        **{
            name: entry.get("style", {})[name]
            for name in _STYLE_FIELDS
            if name in entry.get("style", {})
        }
    )
    return Roi(
        roi_id=entry["roi_id"],
        name=entry["name"],
        kind=entry["kind"],
        geometry=[float(value) for value in entry["geometry"]],
        base_anchor=float(entry["base_anchor"]),
        overrides={
            float(anchor): [float(value) for value in geometry]
            for anchor, geometry in entry["overrides"].items()
        },
        style=style,
    )


def load_session(experiment_directory) -> AnalysisSession:
    """The experiment's saved analysis session; empty (with defaults)
    when absent or unreadable. Accepts the v1 format (a bare ROI list,
    no styles/figure) with defaults filling the rest."""
    session = AnalysisSession(directory=str(experiment_directory))
    path = Path(experiment_directory) / ANALYSIS_DIR_NAME / ROI_CONFIG_FILENAME
    if not path.is_file():
        return session
    try:
        payload = json.loads(path.read_text())
        entries = payload if isinstance(payload, list) else payload["rois"]
        session.rois = [_roi_from(entry) for entry in entries]
        if isinstance(payload, dict):
            session.plot_stat = payload.get("plot_stat", "mean")
            figure = FigureSettings()
            figure.trait_set(
                **{
                    name: payload.get("figure", {})[name]
                    for name in _FIGURE_FIELDS
                    if name in payload.get("figure", {})
                }
            )
            session.figure = figure
    except Exception as error:
        logger.warning(f"Could not load ROI config {path}: {error}")
        return AnalysisSession(directory=str(experiment_directory))
    return session


def save_roi_stats(experiment_directory, stats):
    """Lossless dump of the computed-stats store (json allows the NaN
    literal, which Python's parser reads back)."""
    payload = {
        "version": 1,
        "entries": [
            {
                "path": key[0],
                "mtime": key[1],
                "roi_id": key[2],
                "kind": key[3],
                "geometry": list(key[4]),
                "stats": value,
            }
            for key, value in stats.items()
        ],
    }
    path = analysis_directory(experiment_directory) / ROI_STATS_FILENAME
    path.write_text(json.dumps(payload))


def load_roi_stats(experiment_directory) -> dict:
    """The persisted stats store, {} when absent/unreadable/unknown
    version. Entries that no longer match anything (moved ROI, changed
    file) are simply never looked up — invalidation stays automatic."""
    path = Path(experiment_directory) / ANALYSIS_DIR_NAME / ROI_STATS_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
        if payload["version"] != 1:
            logger.warning(f"Unknown ROI stats version in {path}")
            return {}
        return {
            (
                entry["path"],
                float(entry["mtime"]),
                entry["roi_id"],
                entry["kind"],
                tuple(float(value) for value in entry["geometry"]),
            ): entry["stats"]
            for entry in payload["entries"]
        }
    except Exception as error:
        logger.warning(f"Could not load ROI stats {path}: {error}")
        return {}
```

In `roi_controller.py`, keep the suite green by switching the two old
call sites minimally (the full controller rework is Task 3):

- Import line becomes: `from .roi_store import (analysis_directory, load_session, save_session, write_intensity_csv,)`
- `_save_config` body: `save_session(directory, AnalysisSession(directory=str(directory), rois=list(self.analysis_model.rois)))` — add `AnalysisSession` to the `from .roi_model import` line.
- `_on_experiment_changed`: replace the `load_roi_config` call with `self.analysis_model.rois = (list(load_session(directory).rois) if directory is not None else [])`.

- [ ] **Step 4: Run the store tests, then the full analysis test set**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(analysis): session + stats-store persistence (v2 config)"
```

---

### Task 3: Re-point controller, model, view, and canvas at the session

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py`
- Test: `fluorescence_controls_ui/tests/test_roi_model.py` (update)

**Interfaces:**
- Consumes: Task 1's session traits, Task 2's `save_session`/`load_session`.
- Produces: `RoiAnalysisModel` WITHOUT `rois`, `cache`, and their methods (`roi_by_id`, `next_roi_name`, `stat_info`, `cache_key`, `effective_for` now live ONLY on `AnalysisSession`; callers use `model.session.<method>`); controller maintains the `filtered_paths`/`current_image_path` mirrors; ROI creation assigns a palette color. `plot_series`/`plot_revision`/`_rebuild_plot_series` STAY until Task 5.

- [ ] **Step 1: Slim the model**

In `roi_model.py` delete from `RoiAnalysisModel`: the `rois` trait, the
`cache` trait, and the four methods `roi_by_id`, `next_roi_name`,
`stat_info`, `cache_key`, `effective_for` (they are exact duplicates of
the session's). Keep: `interaction_mode`, `selected_roi_id`,
`roi_info_text`, `progress_text`, batch counters, `plot_series`,
`plot_revision`, buttons, events, `session`, `filtered_paths`,
`current_image_path`. Update the class docstring's first line to:
`"""Shared tool-state between the viewer pane (ROI editing,
toolbuttons) and the plot pane; the per-experiment data lives in
``session``."""`

- [ ] **Step 2: Rework the controller**

In `roi_controller.py`:

1. Import `DEFAULT_ROI_COLORS` from `.consts`, and `AnalysisSession`,
   `RoiStyle` from `.roi_model` (drop `Roi` only if unused — it is
   still used).
2. Add a helper property near the top of the class:

```python
    @property
    def session(self):
        return self.analysis_model.session
```

3. Replace every `self.analysis_model.rois` with `self.session.rois`,
   every `self.analysis_model.cache` with `self.session.stats`, and
   every `self.analysis_model.roi_by_id(...)` / `next_roi_name()` /
   `cache_key(...)` / `stat_info(...)` with the `self.session.`
   equivalent. In `_missing_work`, `_start_batch`, `_rebuild_plot_series`,
   `_write_export`, `_instant_stats`, `_absorb`, `_show_instant`,
   `_delete_selected_roi`, `_clear_rois`, `_reset_cache`,
   `_on_canvas_roi_created/edited`: same mechanical substitution
   (`model = self.analysis_model` locals that touch rois/cache switch
   to a `session = self.session` local).
4. `_on_canvas_roi_created` builds the ROI with a cycled default color:

```python
roi = Roi(
    name=self.session.next_roi_name(),
    kind=kind,
    geometry=[float(value) for value in geometry],
    base_anchor=anchor,
    style=RoiStyle(
        color=DEFAULT_ROI_COLORS[len(self.session.rois) % len(DEFAULT_ROI_COLORS)]
    ),
)
self.session.rois.append(roi)
```

5. `_absorb` bumps the revision so observers (Task 5's pane, Task 8's
   table) hear about store growth:

```python
    def _absorb(self, payload):
        absorbed = False
        for roi_id, stats in payload["stats"].items():
            key = self._dispatched_keys.get((payload["path"], roi_id))
            if key is not None:
                self.session.stats[key] = stats
                absorbed = True
        if absorbed:
            self.session.stats_revision += 1
```

6. `_save_config` saves the whole session:

```python
    def _save_config(self):
        directory = self._experiment_directory()
        if directory is None:
            return
        try:
            save_session(directory, self.session)
        except Exception as error:
            logger.warning(f"Could not save ROI config: {error}")
```

7. `_on_experiment_changed` swaps the session (stats loading arrives in
   Task 4 — here the new session starts with empty stats):

```python
@observe("viewer_model:browsed_directory")
def _on_experiment_changed(self, event):
    """A different folder is being browsed: swap in its saved
    session wholesale (ROIs, styles, figure settings)."""
    self.runner.cancel()
    self.analysis_model.batch_running = False
    self.analysis_model.progress_text = ""
    self.analysis_model.roi_info_text = ""
    self.analysis_model.selected_roi_id = ""
    directory = self._experiment_directory()
    self.analysis_model.session = (
        load_session(directory) if directory is not None else AnalysisSession()
    )
    self._rebuild_plot_series()
```

8. Add the mirrors (new observers, anywhere near `_on_filter_changed`):

```python
@observe("viewer_model:paths.items")
def _mirror_filtered_paths(self, event):
    self.analysis_model.filtered_paths = [str(path) for path in self.viewer_model.paths]


@observe("viewer_model:current_path")
def _mirror_current_image(self, event):
    self.analysis_model.current_image_path = self.viewer_model.current_path
```

- [ ] **Step 3: Re-point the view and canvas editor**

In `view.py`:

1. `_ImageCanvasEditor.init`: the callbacks stay on `analysis` (the
   model — events/`selected_roi_id` are tool state). The ROI-state
   observe string (in BOTH `init` and `dispose`, kept identical)
   becomes:

```python
            "current_path, roi_analysis:session, "
            "roi_analysis:session:rois.items, "
            "roi_analysis:session:rois:items:geometry, "
            "roi_analysis:session:rois:items:overrides.items, "
            "roi_analysis:selected_roi_id")
```

2. `_sync_roi_layer` uses the session:

```python
self._roi_layer.sync(
    model.roi_analysis.session.effective_for(model.current_path),
    model.roi_analysis.selected_roi_id,
)
```

The `analysis_group` bindings all target tool-state traits that stayed
on the model — no changes there.

- [ ] **Step 4: Update the model tests**

In `test_roi_model.py`, update every use of `RoiAnalysisModel().rois`,
`.cache`, `.roi_by_id`, `.next_roi_name`, `.cache_key`,
`.effective_for` to go through `model.session.` (e.g.
`model.session.rois.append(...)`; `model.session.next_roi_name()`).
Where a test constructed a bare `RoiAnalysisModel` purely for those
methods, constructing an `AnalysisSession()` directly is equally fine —
prefer whichever keeps the diff smallest. Do not change what the tests
assert.

- [ ] **Step 5: Run the affected test files**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_burst_filter_all.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/view.py fluorescence_controls_ui/tests/test_roi_model.py
git commit -m "refactor(analysis): move per-experiment state into AnalysisSession"
```

---

### Task 4: Stats persistence wiring + pool warm-up

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/dock_pane.py`
- Test: `fluorescence_controls_ui/tests/test_analysis_session.py` (extend)

**Interfaces:**
- Consumes: `save_roi_stats`/`load_roi_stats` (Task 2), `STATS_SAVE_DEBOUNCE_S` (Task 1), `_shared_executor` (existing, `roi_batch.py`).
- Produces: controller methods `flush_stats(force=False)` (called every drain tick by the dock pane) and `_mark_stats_dirty()`; sessions load their persisted stats on experiment switch; stats save on batch finish (forced), debounced after drains, and forced before a session swap; `_reset_cache` persists the emptied store. Dock pane warms the process pool at startup.

- [ ] **Step 1: Wire persistence into the controller**

In `roi_controller.py`:

1. Add `import time` usage is already present; add to the store import:
   `load_roi_stats, save_roi_stats`; add to the consts import:
   `from .consts import DEFAULT_ROI_COLORS, STATS_SAVE_DEBOUNCE_S`.
2. Add traits after `_dispatched_keys`:

```python
    #: The stats store changed since the last write; flushed by the
    #: dock pane's drain tick after STATS_SAVE_DEBOUNCE_S of quiet.
    _stats_dirty = Bool(False)
    _stats_dirty_since = Float(0.0)
```

   (`Float` joins the `traits.api` import.)
3. Add the flush machinery:

```python
def _mark_stats_dirty(self):
    if not self._stats_dirty:
        self._stats_dirty_since = time.monotonic()
    self._stats_dirty = True


def flush_stats(self, force=False):
    """Write the stats store if it changed — debounced (a draining
    batch marks it dirty every tick) unless ``force``d (batch
    finish, session swap, reset)."""
    if not self._stats_dirty:
        return
    if not force and (
        time.monotonic() - self._stats_dirty_since < STATS_SAVE_DEBOUNCE_S
    ):
        return
    directory = self.session.directory
    if not directory:
        self._stats_dirty = False
        return
    try:
        save_roi_stats(directory, self.session.stats)
        self._stats_dirty = False
    except Exception as error:
        logger.warning(f"Could not save ROI stats: {error}")
```

4. `_absorb`: after `self.session.stats_revision += 1` add
   `self._mark_stats_dirty()`.
5. In `drain_results`, the `BATCH_FINISHED` branch gains
   `self.flush_stats(force=True)` right after
   `self._update_progress_text(finished=True)`.
6. `_on_experiment_changed`: first line of the body becomes a save of
   the outgoing store, and the new session loads its persisted stats:

```python
self.runner.cancel()
self.flush_stats(force=True)
...
directory = self._experiment_directory()
session = load_session(directory) if directory is not None else AnalysisSession()
if directory is not None:
    session.stats = load_roi_stats(directory)
    session.stats_revision += 1
self.analysis_model.session = session
self._dispatched_keys = {}
self._rebuild_plot_series()
```

   (`session.directory` is the experiment dir, set by `load_session`,
   so `flush_stats` writes under the OUTGOING experiment even though
   `browsed_directory` already changed.)
7. `_reset_cache`: after `self.analysis_model.session.stats = {}` (the
   Task 3 form is `self.session.stats = {}` — Dict replacement is
   fine), add `self.session.stats_revision += 1`,
   `self._mark_stats_dirty()`, and `self.flush_stats(force=True)` so
   the emptied store persists.

- [ ] **Step 2: Dock pane — flush tick and pool warm-up**

In `dock_pane.py`:

1. Add `import threading` (module level) and
   `from .analysis.roi_batch import _shared_executor`.
2. In `traits_init`, after constructing `analysis_controller`:

```python
        # Warm the process pool off-thread so the first Calculate does
        # not pay the Windows spawn cost (~seconds for cv2 workers).
        threading.Thread(target=_shared_executor, daemon=True).start()
```

3. The drain timer also flushes:

```python
        self._drain_timer.timeout.connect(self._drain_tick)
```

   replacing the direct connect, plus the method:

```python
    def _drain_tick(self):
        self.analysis_controller.drain_results()
        self.analysis_controller.flush_stats()
```

- [ ] **Step 3: Add the round-trip integration test**

Append to `test_analysis_session.py`:

```python
def test_experiment_switch_saves_and_reloads_stats(tmp_path, monkeypatch):
    """The headline behavior: stats computed in one visit are on disk
    and come back on the next visit to that experiment."""
    from fluorescence_controls_ui.image_viewer.analysis.roi_controller import (
        RoiAnalysisController,
    )
    from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
        load_roi_stats,
    )
    from fluorescence_controls_ui.image_viewer.model import (
        FluorescenceImageViewerModel,
    )

    exp_a = tmp_path / "ExpA"
    exp_b = tmp_path / "ExpB"
    (exp_a / "captures").mkdir(parents=True)
    (exp_b / "captures").mkdir(parents=True)

    viewer = FluorescenceImageViewerModel()
    controller = RoiAnalysisController(
        viewer_model=viewer, analysis_model=viewer.roi_analysis
    )
    viewer.browsed_directory = str(exp_a / "captures")

    key = ("img.png", 1.0, "abcd1234", "circle", (5.0, 5.0, 2.0))
    controller.session.stats[key] = {"mean": 7.0, "count": 4.0}
    controller._mark_stats_dirty()

    viewer.browsed_directory = str(exp_b / "captures")  # forces flush
    assert load_roi_stats(exp_a)[key]["mean"] == 7.0
    assert controller.session.stats == {}  # B starts empty

    viewer.browsed_directory = str(exp_a / "captures")  # come back
    assert controller.session.stats[key]["count"] == 4.0
```

- [ ] **Step 4: Run the tests**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py -q`
Expected: all pass. (The shared model singleton means the switch test
must not leak state: it swaps sessions itself, which is the reset.)

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/dock_pane.py fluorescence_controls_ui/tests/test_analysis_session.py
git commit -m "feat(analysis): persist stats per experiment, warm pool at startup"
```

---

### Task 5: Self-deriving plot pane

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/plot_series.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Test: `fluorescence_controls_ui/tests/test_plot_series.py` (new)

**Interfaces:**
- Consumes: `AnalysisSession` (Task 1), mirrors (Task 3).
- Produces: `derive_series(session, filtered_paths) -> {roi_id: (name, [elapsed_sec], [value])}` honoring `session.plot_stat` (incl. `bg_corrected` = mean − outline_mean) and `stat_value(stats, stat) -> float`; the plot pane redraws from observers with a coalescing single-shot timer. DELETED: `plot_series`/`plot_revision` model traits, controller `_rebuild_plot_series` and all its call sites, `ROI_PLOT_REFRESH_INTERVAL_MS`.

- [ ] **Step 1: Write the failing derivation tests**

Create `fluorescence_controls_ui/tests/test_plot_series.py`:

```python
"""Series derivation: pure function of (session, filtered paths)."""

import math

from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    derive_series,
    stat_value,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession,
    Roi,
)


def _image(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    return str(path)


def test_derive_series_elapsed_axis_and_nan_gaps(tmp_path):
    first = _image(tmp_path, "a_2026_07_20-10_00_00_raw.png")
    second = _image(tmp_path, "b_2026_07_20-10_00_30_raw.png")
    roi = Roi(name="ROI 1", kind="circle", geometry=[5.0, 5.0, 2.0])
    session = AnalysisSession(rois=[roi])
    session.stats[session.cache_key(first, roi)] = {"mean": 10.0, "outline_mean": 4.0}

    series = derive_series(session, [first, second])
    name, elapsed, values = series[roi.roi_id]
    assert name == "ROI 1"
    assert elapsed == [0.0, 30.0]
    assert values[0] == 10.0
    assert math.isnan(values[1])  # uncomputed image gaps


def test_derive_series_honors_plot_stat(tmp_path):
    image = _image(tmp_path, "a_2026_07_20-10_00_00_raw.png")
    roi = Roi(name="ROI 1", kind="circle", geometry=[5.0, 5.0, 2.0])
    session = AnalysisSession(rois=[roi], plot_stat="bg_corrected")
    session.stats[session.cache_key(image, roi)] = {"mean": 10.0, "outline_mean": 4.0}
    ((_, _, values),) = derive_series(session, [image]).values()
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_plot_series.py -q`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `plot_series.py`**

```python
"""Series derivation for the ROI plot: a pure function of the session
and the viewer's filtered paths, so the plot pane owns its own picture
(observer pattern — nothing pushes series at it). Qt-free."""

import math


def stat_value(stats, stat):
    """The plotted value for one (image, ROI) stats dict — NaN when the
    stats are missing entirely or lack the needed keys.
    ``bg_corrected`` is interior mean minus outline-ring mean."""
    if not stats:
        return math.nan
    if stat == "bg_corrected":
        mean = stats.get("mean")
        outline = stats.get("outline_mean")
        if mean is None or outline is None:
            return math.nan
        return mean - outline
    value = stats.get(stat)
    return math.nan if value is None else value


def derive_series(session, filtered_paths):
    """{roi_id: (name, [elapsed_sec], [value])} for ``session.plot_stat``
    over the filtered images, elapsed from the first filtered capture.
    NaN where an (image, ROI) pair has no computed stats (line gaps)."""
    paths = list(filtered_paths)
    if not paths or not session.rois:
        return {}
    stat_cache = {}
    times = [session.stat_info(path, stat_cache)[1] for path in paths]
    start_time = times[0]
    series = {}
    for roi in session.rois:
        elapsed, values = [], []
        for path, capture_time in zip(paths, times):
            stats = session.stats.get(session.cache_key(path, roi, stat_cache))
            elapsed.append(capture_time - start_time)
            values.append(stat_value(stats, session.plot_stat))
        series[roi.roi_id] = (roi.name, elapsed, values)
    return series
```

- [ ] **Step 4: Rework the plot pane**

In `consts.py`: delete `ROI_PLOT_REFRESH_INTERVAL_MS`, add:

```python
#: Coalescing delay (ms) between an analysis-state notification and the
#: plot redraw — a drain burst paints once.
ROI_PLOT_COALESCE_MS = 100
```

Replace `plot_pane.py`'s canvas and pane with the observer version:

```python
"""Dock pane plotting the ROI intensity series: the chosen stat vs
elapsed time, one line per ROI. A pure observer of the shared analysis
model — it derives its own series from the session (stats store +
filters + plot stat) and coalesces notification bursts into single
redraws. Lines gap where an image failed or isn't computed."""

import os

os.environ.setdefault("QT_API", "pyside6")
import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure

from pyface.tasks.api import DockPane
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...consts import PKG
from .consts import ROI_PLOT_COALESCE_MS
from .plot_series import derive_series
from .roi_model import roi_analysis_model

#: Everything the derived series depends on; one observer, one redraw
#: path. Session swap covers experiment changes; stats_revision covers
#: store growth/loads; rois/name for legend labels; plot_stat and
#: filtered_paths for the axes content.
_PLOT_STATE = (
    "session, session:stats_revision, session:rois.items, "
    "session:rois:items:name, session:plot_stat, "
    "filtered_paths.items"
)


class RoiPlotCanvas(FigureCanvasQTAgg):
    """Intensity-vs-time chart derived from the analysis model."""

    def __init__(self, model):
        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Elapsed time (s)")
        self._axes.set_ylabel("Mean intensity")
        self._axes.grid(True, alpha=0.3)
        self._lines = {}
        self._redraw_pending = False
        model.observe(self._on_plot_state_changed, _PLOT_STATE)
        self._schedule_redraw()

    def closeEvent(self, event):
        self._model.observe(self._on_plot_state_changed, _PLOT_STATE, remove=True)
        super().closeEvent(event)

    def showEvent(self, event):
        self._schedule_redraw()  # catch up on anything missed hidden
        super().showEvent(event)

    def _on_plot_state_changed(self, event):
        self._schedule_redraw()

    def _schedule_redraw(self):
        if self._redraw_pending:
            return
        self._redraw_pending = True
        QTimer.singleShot(ROI_PLOT_COALESCE_MS, self._refresh)

    def _refresh(self):
        self._redraw_pending = False
        if not self.isVisible():
            return  # showEvent reschedules
        series = derive_series(self._model.session, self._model.filtered_paths)
        for roi_id in list(self._lines):
            if roi_id not in series:
                self._lines.pop(roi_id).remove()
        for roi_id, (name, elapsed, values) in series.items():
            if roi_id not in self._lines:
                (self._lines[roi_id],) = self._axes.plot([], [], marker=".", label=name)
            line = self._lines[roi_id]
            line.set_data(elapsed, values)
            line.set_label(name)
        if self._lines:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


class FluorescenceRoiPlotDockPane(DockPane):
    """ROI intensity vs time for the filtered image series."""

    id = PKG + ".image_viewer.roi_plot_dock_pane"
    name = "Fluorescence ROI Intensities"

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        canvas = RoiPlotCanvas(roi_analysis_model)
        layout.addWidget(NavigationToolbar2QT(canvas, widget))
        layout.addWidget(canvas)
        progress = QLabel("", widget)
        roi_analysis_model.observe(
            lambda event: progress.setText(event.new), "progress_text"
        )
        layout.addWidget(progress)
        return widget
```

- [ ] **Step 5: Delete the pushed-series machinery**

- `roi_model.py`: delete the `plot_series` and `plot_revision` traits.
- `roi_controller.py`: delete `_rebuild_plot_series` and its whole
  "Plot series" section, plus every call to it (`_on_filter_changed`
  keeps only `self._restart_batch_if_running()` and its docstring
  shrinks to `"""The filtered series changed mid-batch: restart on the
  new snapshot (the work list is a snapshot by design; the plot pane
  observes the filters itself)."""`; `_delete_selected_roi`,
  `_clear_rois`, `_reset_cache`, `_start_batch`,
  `_on_experiment_changed`, `drain_results` all drop the call — in
  `drain_results` the `drained` flag becomes unnecessary; remove it).
  `import math` becomes unused — remove it.

- [ ] **Step 6: Run the tests**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_plot_series.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_series.py fluorescence_controls_ui/image_viewer/analysis/plot_pane.py fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/analysis/consts.py fluorescence_controls_ui/tests/test_plot_series.py
git commit -m "refactor(analysis): plot pane derives its own series from the session"
```

---

### Task 6: Stat selector and styled artists

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Test: none beyond existing (UI wiring; derivation already tested)

**Interfaces:**
- Consumes: `PLOT_STATS`, `RoiStyle` (Task 1), `derive_series` (Task 5).
- Produces: a stat dropdown writing `session.plot_stat`; plot artists styled from each ROI's `RoiStyle`; `PLOT_STAT_LABELS` dict in `plot_pane.py`; controller observers persisting `plot_stat` and style edits via `_save_config`.

- [ ] **Step 1: Stat labels + dropdown**

In `plot_pane.py` add after the imports:

```python
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .roi_model import PLOT_STATS

#: Human labels for the plotted stat (dropdown + y-axis).
PLOT_STAT_LABELS = {
    "mean": "Mean intensity",
    "bg_corrected": "Background-corrected mean",
    "median": "Median intensity",
    "min": "Min intensity",
    "max": "Max intensity",
    "outline_mean": "Outline ring mean",
}

#: matplotlib linestyle codes for RoiStyle.line_style.
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
```

(merge the `QLabel...` import line with the existing one). Extend
`_PLOT_STATE` with the style traits:

```python
_PLOT_STATE = (
    "session, session:stats_revision, session:rois.items, "
    "session:rois:items:name, session:plot_stat, "
    "session:rois:items:style:color, "
    "session:rois:items:style:line_style, "
    "session:rois:items:style:marker, "
    "session:rois:items:style:marker_size, "
    "filtered_paths.items"
)
```

- [ ] **Step 2: Apply styles in `_refresh`**

In `RoiPlotCanvas._refresh`, the per-line block becomes:

```python
for roi_id, (name, elapsed, values) in series.items():
    if roi_id not in self._lines:
        (self._lines[roi_id],) = self._axes.plot([], [])
    line = self._lines[roi_id]
    line.set_data(elapsed, values)
    line.set_label(name)
    roi = self._model.session.roi_by_id(roi_id)
    if roi is not None:
        line.set_color(roi.style.color)
        line.set_linestyle(LINE_STYLES[roi.style.line_style])
        line.set_marker("" if roi.style.marker == "none" else roi.style.marker)
        line.set_markersize(roi.style.marker_size)
```

and the y-label follows the stat (start of `_refresh`, after the
visibility check):

```python
self._axes.set_ylabel(PLOT_STAT_LABELS[self._model.session.plot_stat])
```

- [ ] **Step 3: Dropdown row in the pane**

In `create_contents`, between the toolbar and the canvas:

```python
controls = QHBoxLayout()
controls.addWidget(QLabel("Plot:", widget))
stat_combo = QComboBox(widget)
for stat in PLOT_STATS:
    stat_combo.addItem(PLOT_STAT_LABELS[stat], stat)
stat_combo.setCurrentIndex(PLOT_STATS.index(roi_analysis_model.session.plot_stat))
stat_combo.currentIndexChanged.connect(
    lambda index: roi_analysis_model.session.trait_set(plot_stat=PLOT_STATS[index])
)
controls.addWidget(stat_combo)
controls.addStretch()
layout.addLayout(controls)
roi_analysis_model.observe(
    lambda event: stat_combo.setCurrentIndex(PLOT_STATS.index(event.object.plot_stat)),
    "session:plot_stat",
)
roi_analysis_model.observe(
    lambda event: stat_combo.setCurrentIndex(PLOT_STATS.index(event.new.plot_stat)),
    "session",
)
```

- [ ] **Step 4: Persist stat/style edits**

In `roi_controller.py` add:

```python
@observe(
    "analysis_model:session:plot_stat, "
    "analysis_model:session:figure:export_format, "
    "analysis_model:session:figure:export_dpi, "
    "analysis_model:session:figure:x_auto, "
    "analysis_model:session:figure:x_min, "
    "analysis_model:session:figure:x_max, "
    "analysis_model:session:figure:y_auto, "
    "analysis_model:session:figure:y_min, "
    "analysis_model:session:figure:y_max, "
    "analysis_model:session:rois:items:name, "
    "analysis_model:session:rois:items:style:color, "
    "analysis_model:session:rois:items:style:line_style, "
    "analysis_model:session:rois:items:style:marker, "
    "analysis_model:session:rois:items:style:marker_size"
)
def _on_plot_settings_changed(self, event):
    self._save_config()
```

- [ ] **Step 5: Run analysis tests (regression only) and commit**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_plot_series.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py -q`
Expected: pass.

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_pane.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py
git commit -m "feat(analysis): plot stat selector and per-ROI line styling"
```

---

### Task 7: ROI table with rename, style editors, and live stats

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_table.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py`
- Test: none (pure Qt widget; logic it displays is already tested)

**Interfaces:**
- Consumes: session/mirrors, `stat_value` (Task 5), `LINE_STYLES` keys.
- Produces: `RoiStatsTable(QTableWidget)` added below the canvas; DELETED: `roi_info_text` trait, its view readout, and `_show_instant` (instant results only absorb + bump revision; the table shows them).

- [ ] **Step 1: Implement `roi_table.py`**

```python
"""Per-ROI table under the intensity plot: editable name (drives the
plot legend and CSV columns), style editors (color, line, marker,
size), and live stats for the image currently shown in the viewer —
including the instant result right after drawing an ROI. A pure
observer of the shared analysis model, mutating it only from Qt editor
signals (GUI thread)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from .plot_series import stat_value
from .roi_model import RoiStyle

#: Value columns after the editors, shown for the current image.
_STAT_COLUMNS = ("mean", "bg_corrected", "median", "min", "max", "count")
_HEADERS = ("Name", "Color", "Line", "Marker", "Size") + _STAT_COLUMNS
_LINE_CHOICES = ("solid", "dashed", "dotted", "dashdot")
_MARKER_CHOICES = ("none", ".", "o", "s", "^", "x")

#: Everything the table depends on (rebuild on structure/style change,
#: value-refresh on stats/current-image change).
_TABLE_STATE = (
    "session, session:rois.items, session:rois:items:name, "
    "session:rois:items:style:color, "
    "session:stats_revision, current_image_path"
)


class RoiStatsTable(QTableWidget):
    """One row per ROI; editors write straight into the session."""

    def __init__(self, model, parent=None):
        super().__init__(0, len(_HEADERS), parent)
        self._model = model
        self._rebuilding = False
        self.setHorizontalHeaderLabels(_HEADERS)
        self.verticalHeader().setVisible(False)
        self.itemChanged.connect(self._on_item_changed)
        model.observe(self._on_state_changed, _TABLE_STATE)
        self._rebuild()

    def closeEvent(self, event):
        self._model.observe(self._on_state_changed, _TABLE_STATE, remove=True)
        super().closeEvent(event)

    def _on_state_changed(self, event):
        self._rebuild()

    def _rebuild(self):
        self._rebuilding = True
        session = self._model.session
        rois = list(session.rois)
        self.setRowCount(len(rois))
        current = self._model.current_image_path
        stat_cache = {}
        for row, roi in enumerate(rois):
            name_item = QTableWidgetItem(roi.name)
            name_item.setData(Qt.ItemDataRole.UserRole, roi.roi_id)
            self.setItem(row, 0, name_item)
            self.setCellWidget(row, 1, self._color_button(roi))
            self.setCellWidget(
                row,
                2,
                self._combo(
                    _LINE_CHOICES,
                    roi.style.line_style,
                    lambda value, roi=roi: roi.style.trait_set(line_style=value),
                ),
            )
            self.setCellWidget(
                row,
                3,
                self._combo(
                    _MARKER_CHOICES,
                    roi.style.marker,
                    lambda value, roi=roi: roi.style.trait_set(marker=value),
                ),
            )
            self.setCellWidget(row, 4, self._size_spin(roi))
            stats = (
                session.stats.get(session.cache_key(current, roi, stat_cache))
                if current
                else None
            )
            for column, stat in enumerate(
                _STAT_COLUMNS, start=len(_HEADERS) - len(_STAT_COLUMNS)
            ):
                value = stat_value(stats, stat)
                text = "" if value != value else f"{value:.1f}"
                value_item = QTableWidgetItem(text)
                value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(row, column, value_item)
        self._rebuilding = False

    def _on_item_changed(self, item):
        if self._rebuilding or item.column() != 0:
            return
        roi = self._model.session.roi_by_id(item.data(Qt.ItemDataRole.UserRole))
        if roi is not None and item.text().strip():
            roi.name = item.text().strip()

    def _color_button(self, roi):
        button = QPushButton(self)
        button.setStyleSheet(f"background-color: {roi.style.color};")
        button.clicked.connect(
            lambda _=False, roi=roi, button=button: self._pick_color(roi, button)
        )
        return button

    def _pick_color(self, roi, button):
        color = QColorDialog.getColor(QColor(roi.style.color), self)
        if color.isValid():
            roi.style.color = color.name()
            button.setStyleSheet(f"background-color: {color.name()};")

    def _combo(self, choices, current, setter):
        combo = QComboBox(self)
        combo.addItems(choices)
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(setter)
        return combo

    def _size_spin(self, roi):
        spin = QDoubleSpinBox(self)
        spin.setRange(1.0, 30.0)
        spin.setValue(roi.style.marker_size)
        spin.valueChanged.connect(
            lambda value, roi=roi: roi.style.trait_set(marker_size=value)
        )
        return spin
```

- [ ] **Step 2: Add the table to the pane**

In `plot_pane.py` `create_contents`, after the canvas:

```python
        table = RoiStatsTable(roi_analysis_model, widget)
        layout.addWidget(table)
```

with `from .roi_table import RoiStatsTable` in the imports.

- [ ] **Step 3: Retire `roi_info_text`**

- `roi_model.py`: delete the `roi_info_text` trait.
- `roi_controller.py`: delete `_show_instant`; in `drain_results` the
  `INSTANT_RESULT` branch becomes just `self._absorb(payload)`; in
  `_delete_selected_roi` the no-selection message goes to
  `progress_text`; `_on_experiment_changed` drops the
  `roi_info_text = ""` line.
- `view.py`: remove the `UItem("object.roi_analysis.roi_info_text", ...)`
  line from `analysis_group`. ALSO add
  `"roi_analysis:session:rois:items:name, "` to the canvas editor's
  ROI-state observe string (init + dispose, identical) so renames
  update the canvas labels live.

- [ ] **Step 4: Run the analysis test files and commit**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_plot_series.py -q`
Expected: pass.

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_table.py fluorescence_controls_ui/image_viewer/analysis/plot_pane.py fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/view.py
git commit -m "feat(analysis): ROI table with rename, styles, live stats"
```

---

### Task 8: Axis controls and publication export

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Test: none (Qt wiring over tested settings traits)

**Interfaces:**
- Consumes: `FigureSettings` (Task 1), controls row (Task 6).
- Produces: axis-limit fields with Auto checkboxes applied in `_refresh`; Save-figure button rendering `figure.savefig` at `export_dpi`/`export_format` via a pyface FileDialog defaulting into the experiment's `analysis/` folder.

- [ ] **Step 1: Apply limits in `_refresh`**

Replace the autoscale tail of `RoiPlotCanvas._refresh` with:

```python
figure_settings = self._model.session.figure
self._axes.relim()
self._axes.autoscale_view()
if not figure_settings.x_auto:
    self._axes.set_xlim(figure_settings.x_min, figure_settings.x_max)
if not figure_settings.y_auto:
    self._axes.set_ylim(figure_settings.y_min, figure_settings.y_max)
self.draw_idle()
```

and extend `_PLOT_STATE` with
`"session:figure:x_auto, session:figure:x_min, session:figure:x_max, "
"session:figure:y_auto, session:figure:y_min, session:figure:y_max, "`.

- [ ] **Step 2: Axis + export controls row**

In `create_contents`, extend the Task 6 controls row (before
`controls.addStretch()`); add the imports
(`QCheckBox`, `QDoubleSpinBox`, `QPushButton` from
`PySide6.QtWidgets`; `from pathlib import Path`;
`from pyface.api import FileDialog, OK`;
`from device_viewer.consts import CAPTURES_DIR_NAME`):

```python
def _axis_editors(label, auto_trait, low_trait, high_trait):
    figure_settings = roi_analysis_model.session.figure
    auto = QCheckBox(f"{label} auto", widget)
    auto.setChecked(getattr(figure_settings, auto_trait))
    low = QDoubleSpinBox(widget)
    high = QDoubleSpinBox(widget)
    for spin, trait in ((low, low_trait), (high, high_trait)):
        spin.setRange(-1e9, 1e9)
        spin.setDecimals(1)
        spin.setValue(getattr(figure_settings, trait))
        spin.setEnabled(not auto.isChecked())
        spin.valueChanged.connect(
            lambda value, trait=trait: roi_analysis_model.session.figure.trait_set(
                **{trait: value}
            )
        )

    def _on_auto(checked, auto_trait=auto_trait, low=low, high=high):
        roi_analysis_model.session.figure.trait_set(**{auto_trait: bool(checked)})
        low.setEnabled(not checked)
        high.setEnabled(not checked)

    auto.toggled.connect(_on_auto)
    for control in (auto, low, high):
        controls.addWidget(control)


_axis_editors("X", "x_auto", "x_min", "x_max")
_axis_editors("Y", "y_auto", "y_min", "y_max")

dpi_combo = QComboBox(widget)
for dpi in (150, 300, 600):
    dpi_combo.addItem(f"{dpi} dpi", dpi)
dpi_combo.setCurrentIndex(
    (150, 300, 600).index(roi_analysis_model.session.figure.export_dpi)
)
dpi_combo.currentIndexChanged.connect(
    lambda index: roi_analysis_model.session.figure.trait_set(
        export_dpi=(150, 300, 600)[index]
    )
)
controls.addWidget(dpi_combo)
format_combo = QComboBox(widget)
format_combo.addItems(["png", "svg", "pdf", "tiff"])
format_combo.setCurrentText(roi_analysis_model.session.figure.export_format)
format_combo.currentTextChanged.connect(
    lambda value: roi_analysis_model.session.figure.trait_set(export_format=value)
)
controls.addWidget(format_combo)
save_button = QPushButton("Save plot…", widget)
save_button.clicked.connect(lambda: _save_figure(canvas))
controls.addWidget(save_button)
```

and the module-level helper:

```python
def _save_figure(canvas):
    """Render the current figure at the session's export settings; the
    dialog defaults into the experiment's analysis folder."""
    session = roi_analysis_model.session
    default_dir = str(Path(session.directory) / "analysis") if session.directory else ""
    extension = session.figure.export_format
    dialog = FileDialog(
        action="save as",
        default_directory=default_dir,
        default_filename=f"roi_intensities.{extension}",
        wildcard=f"*.{extension}",
    )
    if dialog.open() != OK:
        return
    canvas.figure.savefig(dialog.path, dpi=session.figure.export_dpi, format=extension)
```

(Note: `session.directory` is the experiment dir; `analysis/` already
exists whenever stats or config were saved — `Path.mkdir` is NOT needed
here because `savefig` fails loudly into the dialog's chosen path
otherwise, which is the user's own choice.)

An experiment switch swaps the session, so the controls must re-read
it or they show the previous experiment's values. After building the
controls row, add ONE session-swap observer that re-syncs every
control from `event.new` (the fresh session):

```python
def _sync_controls(event):
    figure_settings = event.new.figure
    stat_combo.setCurrentIndex(PLOT_STATS.index(event.new.plot_stat))
    dpi_combo.setCurrentIndex((150, 300, 600).index(figure_settings.export_dpi))
    format_combo.setCurrentText(figure_settings.export_format)


roi_analysis_model.observe(_sync_controls, "session")
```

and the two `_axis_editors` calls register their widgets for the same
treatment: give `_axis_editors` a trailing line
`_axis_syncers.append((auto, low, high, auto_trait, low_trait,
high_trait))` over a `_axis_syncers = []` list declared before the
calls, and extend `_sync_controls` with:

```python
for auto, low, high, auto_trait, low_trait, high_trait in _axis_syncers:
    auto.setChecked(getattr(figure_settings, auto_trait))
    low.setValue(getattr(figure_settings, low_trait))
    high.setValue(getattr(figure_settings, high_trait))
```

(This replaces Task 6's two small stat-combo observers — delete those
two `roi_analysis_model.observe(...)` calls from the Task 6 block when
implementing this task, keeping `_sync_controls` as the single
session-swap syncer plus the `"session:plot_stat"` observer for
in-session changes.)

- [ ] **Step 3: Run regression tests and commit**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_plot_series.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_analysis_session.py -q`
Expected: pass.

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_pane.py
git commit -m "feat(analysis): axis limit controls and publication export"
```

---

### Task 9: Final pass

**Files:** none new.

- [ ] **Step 1: Full suite**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/ -q`
Expected: exactly the two pre-existing failures from Global Constraints;
everything else passes.

- [ ] **Step 2: Import-graph guard**

Run: `pixi run python -c "import sys; import fluorescence_controls_ui.image_viewer.analysis.plot_pane, fluorescence_controls_ui.image_viewer.dock_pane; print('capture_service imported:', 'fluorescence_controls_ui.capture_service' in sys.modules)"`
Expected: `capture_service imported: False` (the lazy-import constraint
held through the refactor).

- [ ] **Step 3: Manual GUI checklist (report to the user; do NOT launch the app)**

1. Compute stats in an experiment, switch away, come back → the plot is
   there immediately, current filters applied; Calculate reports "ROI
   stats up to date".
2. Change wavelength / image-group filters → the plot follows without
   recalculating (cache hits).
3. Rename an ROI in the table → legend, canvas label, and the next CSV
   export follow.
4. Style an ROI (color/line/marker/size) → plot updates live; reopen
   the experiment → styling restored.
5. Stat dropdown incl. background-corrected mean → y-label and values
   change.
6. Draw a new ROI → its row appears in the table with instant stats for
   the shown image.
7. Axis auto off + limits → plot clamps; Save plot… writes the chosen
   format/DPI into `analysis/`.
8. Reset dialog (both flavors) still works and survives restart
   (emptied store stays empty).

- [ ] **Step 4: Commit any final fixes with conventional messages.**
