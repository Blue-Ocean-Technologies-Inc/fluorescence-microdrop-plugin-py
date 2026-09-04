# ROI Intensity Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed ROI-based intensity analysis in the fluorescence image viewer: draw circle/box ROIs on the canvas, compute cached per-ROI stats across the filtered image series in a process pool, stream them into a live plot dock pane, and export CSV to the experiment folder.

**Architecture:** Follows the viewer's existing MVC split — a new Qt-free `analysis/` subpackage (`roi_model`, `roi_compute`, `roi_batch`, `roi_store`) plus Qt pieces (`roi_items` graphics layer, plot canvas/pane) and a `RoiAnalysisController` glued in by the existing dock pane. Results flow worker process → queue → GUI-thread drain timer → HasTraits model → poll-timer plot canvas (the plugin's established pattern).

**Tech Stack:** Traits/TraitsUI, PySide6 QGraphicsView, cv2 + numpy, `concurrent.futures.ProcessPoolExecutor`, matplotlib QtAgg (temperature-canvas pattern).

**Spec:** `docs/superpowers/specs/2026-07-30-roi-intensity-analysis-design.md`

## Global Constraints

- Repo: `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py\src\fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`. All `git` commands run from that repo root.
- Tests run from `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py`: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/<test path> -v`. Run ONLY the test file the task names — never the whole suite.
- Conventional Commits, imperative ~50-char subject (`feat(image-viewer): ...`), why/what body. Pre-commit hooks enforce format; never `--no-verify`.
- microdrop conventions (enforced): f-strings everywhere (no `%s`/`.format()`); `from logger.logger_service import get_logger; logger = get_logger(__name__)` (never `logging.getLogger`); no imports inside functions — hoist to module top; stateful classes are `HasTraits` (trait declarations, `traits_init`, `_x_default`), stateless utility functions stay plain; constants in the package's `consts.py` in UPPER_SNAKE_CASE, never mid-file, never aliased; descriptive names over short ones; no Qt imports in model/compute/store/batch modules (views only); no bare `except: pass` — catch `Exception` and log; dialogs via `microdrop_application.dialogs.pyface_wrapper`, comparing against pyface `YES`/`NO`/`CANCEL`.
- Geometry conventions used EVERYWHERE: circle = `[center_x, center_y, radius]`, box = `[x, y, width, height]` (top-left corner), all image-pixel floats. Time convention: "capture time" = epoch seconds from the filename's UTC stamp (mtime fallback) — used for override anchors and plot x-axis; file mtime is used only inside cache keys for staleness.

---

### Task 1: Shared capture-timestamp helper

**Files:**
- Modify: `fluorescence_controls_ui/consts.py` (add one constant at the end)
- Modify: `fluorescence_controls_ui/capture_service.py:65-67` (use the constant)
- Modify: `fluorescence_controls_ui/image_viewer/discovery.py` (add `capture_timestamp`)
- Test: `fluorescence_controls_ui/tests/test_capture_timestamp.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `CAPTURE_TIMESTAMP_FORMAT: str` in `fluorescence_controls_ui/consts.py`; `capture_timestamp(path) -> float` in `image_viewer/discovery.py` (epoch seconds; filename UTC stamp, mtime fallback, `0.0` for missing file). Tasks 3, 8 rely on these exact names.

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_capture_timestamp.py
"""capture_timestamp: filename UTC stamp preferred, mtime fallback."""

import calendar
import time

from fluorescence_controls_ui.image_viewer.discovery import capture_timestamp


def test_timestamp_parsed_from_filename(tmp_path):
    path = tmp_path / "gfp_Green_540_nm_2_2026_07_20-17_46_24_raw.png"
    path.write_bytes(b"")
    expected = calendar.timegm(
        time.strptime("2026_07_20-17_46_24", "%Y_%m_%d-%H_%M_%S")
    )
    assert capture_timestamp(path) == expected


def test_falls_back_to_mtime_without_stamp(tmp_path):
    path = tmp_path / "legacy_capture_raw.png"
    path.write_bytes(b"")
    assert capture_timestamp(path) == path.stat().st_mtime


def test_missing_file_without_stamp_is_zero(tmp_path):
    assert capture_timestamp(tmp_path / "nope.png") == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_capture_timestamp.py -v`
Expected: FAIL — `ImportError: cannot import name 'capture_timestamp'`

- [ ] **Step 3: Implement**

Append to `fluorescence_controls_ui/consts.py`:

```python
#: strftime format of the UTC stamp embedded in capture filenames
#: (capture_service.utc_stamp writes it; discovery.capture_timestamp
#: parses it back).
CAPTURE_TIMESTAMP_FORMAT = "%Y_%m_%d-%H_%M_%S"
```

In `capture_service.py`, add `CAPTURE_TIMESTAMP_FORMAT` to the existing `from .consts import ...` line and change `utc_stamp` to:

```python
def utc_stamp() -> str:
    """UTC timestamp in the shared capture-filename format."""
    return time.strftime(CAPTURE_TIMESTAMP_FORMAT, time.gmtime())
```

In `image_viewer/discovery.py`, extend the imports (top of file) with `import calendar`, `import re`, `import time`, and add `CAPTURE_TIMESTAMP_FORMAT` to the existing `from ..consts import IMAGE_PATTERNS` line. Append at the end of the file:

```python
#: The utc_stamp() pattern as it appears inside capture filenames.
CAPTURE_TIMESTAMP_PATTERN = re.compile(r"\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}")


def capture_timestamp(path) -> float:
    """Capture time (epoch seconds) embedded in the filename by
    capture_service.utc_stamp(), falling back to the file's mtime for
    names without a stamp (legacy captures); 0.0 when neither exists."""
    match = CAPTURE_TIMESTAMP_PATTERN.search(Path(path).name)
    if match:
        return float(
            calendar.timegm(time.strptime(match.group(0), CAPTURE_TIMESTAMP_FORMAT))
        )
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/consts.py fluorescence_controls_ui/capture_service.py fluorescence_controls_ui/image_viewer/discovery.py fluorescence_controls_ui/tests/test_capture_timestamp.py
git commit -m "feat(image-viewer): parse capture time from filenames" -m "Shared CAPTURE_TIMESTAMP_FORMAT + discovery.capture_timestamp so ROI analysis can anchor overrides and plot elapsed time on capture time rather than file mtime."
```

---

### Task 2: Image-group "All" filter option

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/model.py`
- Modify: `fluorescence_controls_ui/image_viewer/controller.py`
- Test: `fluorescence_controls_ui/tests/test_burst_filter_all.py` (create)

**Interfaces:**
- Produces: `BURST_FILTER_ALL = "All"` module constant in `image_viewer/model.py` (next to `WAVELENGTH_FILTER_ALL`). `burst_names` now returns `["All", <groups...>]` (still `[]` with no groups); `burst_paths("All")` returns every group's paths flattened in group order. Task 8 relies on `model.paths` being the full filtered series when "All" + wavelength filter are active.

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_burst_filter_all.py
"""The image-group filter's "All" choice mirrors the wavelength filter's."""

from pathlib import Path

from fluorescence_controls_ui.image_viewer.model import (
    BURST_FILTER_ALL,
    FluorescenceImageViewerModel,
)


def _model_with_two_bursts():
    model = FluorescenceImageViewerModel()
    model.bursts = [
        (
            "burst_a",
            [Path("a/16bit_raw/img1_raw.png"), Path("a/16bit_raw/img2_raw.png")],
        ),
        ("burst_b", [Path("b/16bit_raw/img3_raw.png")]),
    ]
    return model


def test_burst_names_prepend_all():
    model = _model_with_two_bursts()
    assert model.burst_names == [BURST_FILTER_ALL, "burst_a", "burst_b"]


def test_burst_names_empty_without_bursts():
    assert FluorescenceImageViewerModel().burst_names == []


def test_burst_paths_all_flattens_groups_in_order():
    model = _model_with_two_bursts()
    assert [path.name for path in model.burst_paths(BURST_FILTER_ALL)] == [
        "img1_raw.png",
        "img2_raw.png",
        "img3_raw.png",
    ]


def test_position_text_spans_all_when_all_selected():
    model = _model_with_two_bursts()
    model.selected_burst = BURST_FILTER_ALL
    model.burst_index = 0
    model.paths = model.burst_paths(BURST_FILTER_ALL)
    model.current_path = str(model.paths[2])
    assert model.position_text == "3/3"


def test_position_text_counts_prior_groups_for_specific_burst():
    model = _model_with_two_bursts()
    model.selected_burst = "burst_b"
    model.burst_index = 2  # [All, burst_a, burst_b]
    model.paths = model.burst_paths("burst_b")
    model.current_path = str(model.paths[0])
    assert model.position_text == "3/3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_burst_filter_all.py -v`
Expected: FAIL — `ImportError: cannot import name 'BURST_FILTER_ALL'`

- [ ] **Step 3: Implement the model side**

In `model.py`, under `WAVELENGTH_FILTER_ALL` (line 18), add:

```python
#: The image-group filter's no-filter choice (spans every group).
BURST_FILTER_ALL = "All"
```

Replace `_get_burst_names` (line 186-187):

```python
    def _get_burst_names(self):
        names = [name for name, _paths in self.bursts]
        return [BURST_FILTER_ALL] + names if names else []
```

Replace `_get_max_burst_index` (uses names, which now include "All"):

```python
    def _get_max_burst_index(self):
        return max(len(self.burst_names) - 1, 0)
```

Replace `_get_max_burst_number`:

```python
    def _get_max_burst_number(self):
        return max(len(self.burst_names), 1)
```

Replace `burst_paths` (line 229-234):

```python
    def burst_paths(self, burst_name):
        """The named burst's images — every group's, flattened in group
        order, for the "All" choice; [] for an unknown name."""
        if burst_name == BURST_FILTER_ALL:
            return [path for _name, paths in self.bursts for path in paths]
        for name, paths in self.bursts:
            if name == burst_name:
                return list(paths)
        return []
```

Replace `_get_position_text`'s `before` computation — the whole method becomes (note `selected_burst` joins the observe list on the `position_text` Property declaration, line 152-154):

```python
position_text = Property(
    Str,
    observe=(
        "bursts.items, burst_index, selected_burst, "
        "selected_wavelength, paths.items, current_path"
    ),
)
```

```python
    def _get_position_text(self):
        """Position across every image group in the experiment (the arrows
        traverse them all), through the active wavelength filter — the
        images actually reachable. ``self.paths`` is already the filtered
        list; a specific group adds its predecessors' filtered counts,
        the "All" choice starts at zero."""
        total = sum(len(self.visible_of(paths)) for _name, paths in self.bursts)
        if total == 0:
            return ""
        before = 0
        if self.selected_burst != BURST_FILTER_ALL:
            for name, paths in self.bursts:
                if name == self.selected_burst:
                    break
                before += len(self.visible_of(paths))
        index = self.path_index()
        if index is not None:
            return f"{before + index + 1}/{total}"
        return f"–/{total}"
```

- [ ] **Step 4: Implement the controller side**

In `controller.py`, add `BURST_FILTER_ALL` to the existing `.model` import (line 21). Replace `_step_to_adjacent_group` (line 159-169) — with "All" selected the visible list already spans everything, so wrap within it; index arithmetic maps the 1-offset (All at 0) onto the real group list:

```python
def _step_to_adjacent_group(self, direction, show):
    """Move to the next/previous image group (wrapping) and show its
    first/last image. With the "All" choice (or a single group) the
    visible list already spans everything: wrap within it."""
    if self.model.selected_burst == BURST_FILTER_ALL or len(self.model.bursts) <= 1:
        paths = self.model.paths
        self.model.current_path = str(paths[0] if direction > 0 else paths[-1])
        return
    group_index = (self.model.burst_index - 1 + direction) % len(self.model.bursts)
    self._jump_to_burst(group_index + 1, show)
```

In `rescan()` (line 276-322), extend `following_newest` so a user parked on "All" at the newest image also rides along, and keep them on "All" — replace the `following_newest` assignment and the tail `if following_newest:` branch:

```python
on_all = self.model.selected_burst == BURST_FILTER_ALL
following_newest = (
    not self.model.current_path
    or not self.model.paths
    or (on_all and self.model.current_path == str(self.model.paths[-1]))
    or (
        not on_all
        and self.model.burst_names
        and self.model.selected_burst == self.model.burst_names[-1]
        and self.model.current_path == str(self.model.paths[-1])
    )
)
```

```python
        if following_newest:
            if on_all:
                self._refresh_visible("last")
            else:
                self._jump_to_burst(-1, "last")
        elif self.model.selected_burst not in names:
            # The parked burst vanished (folder pruned): fall to newest.
            self._jump_to_burst(-1, "first")
        else:
            self._refresh_visible("keep")
```

(`_jump_to_burst(-1, ...)` still lands on the newest real group — "All" sits at index 0, so index -1 is unchanged. `_browse_directory`'s `_jump_to_burst(0, "first")` now lands on "All" showing the first image, which is the same image as before.)

- [ ] **Step 5: Run test to verify it passes**

Same command as Step 2. Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/model.py fluorescence_controls_ui/image_viewer/controller.py fluorescence_controls_ui/tests/test_burst_filter_all.py
git commit -m "feat(image-viewer): add All choice to image-group filter" -m "Mirrors the wavelength filter's All option so the scrubber and prev/next traversal can span every image group - and so ROI analysis can run over the whole filtered experiment."
```

---

### Task 3: Analysis package — consts + ROI model

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/__init__.py` (empty)
- Create: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
- Modify: `fluorescence_controls_ui/image_viewer/model.py` (add `roi_analysis` trait)
- Test: `fluorescence_controls_ui/tests/test_roi_model.py` (create)

**Interfaces:**
- Consumes: `capture_timestamp` (Task 1).
- Produces (exact names later tasks use):
  - consts: `OUTLINE_PERIMETER_PX = 2`, `OUTLINE_STATS_PREFIX = "outline_"`, `ANALYSIS_DIR_NAME = "analysis"`, `ROI_CONFIG_FILENAME = "roi_config.json"`, `ANALYSIS_RESULT_DRAIN_INTERVAL_MS = 200`, `ROI_PLOT_REFRESH_INTERVAL_MS = 500`, `MIN_ROI_SIZE_PX = 3.0`
  - `Roi(HasTraits)`: traits `roi_id: Str` (8-hex default), `name: Str`, `kind: Enum("circle", "box")`, `geometry: List(Float)`, `base_anchor: Float`, `overrides: Dict(Float, List)`; methods `effective_geometry(capture_time) -> list`, `apply_edit(capture_time, geometry)`, `clear_overrides()`
  - `RoiAnalysisModel(HasTraits)`: traits `rois: List(Instance(Roi))`, `interaction_mode: Enum("pan", "draw_circle", "draw_box", "edit")`, `selected_roi_id: Str`, `cache: Dict`, `roi_info_text: Str`, `progress_text: Str`, `batch_total/batch_done/batch_failed: Int`, `batch_running: Bool`, `plot_series: Dict` (roi_id -> `(name, xs, ys)`), `plot_revision: Int`, buttons `draw_circle_button/draw_box_button/delete_roi_button/clear_rois_button/calculate_button/export_csv_button/reset_cache_button: Button`, `edit_mode: Bool`, events `canvas_roi_created: Event` (payload `(kind, geometry)`), `canvas_roi_edited: Event` (payload `(roi_id, geometry)`); methods `roi_by_id(roi_id) -> Roi | None`, `next_roi_name() -> str`, `cache_key(path, roi) -> tuple`, `effective_for(path) -> [(roi_id, name, kind, geometry)]`
  - module-level singleton `roi_analysis_model = RoiAnalysisModel()` shared by the viewer pane and plot pane
  - `FluorescenceImageViewerModel.roi_analysis: Instance(RoiAnalysisModel)` defaulting to the singleton

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_roi_model.py
"""Roi override resolution and RoiAnalysisModel cache keys."""

from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    Roi,
    RoiAnalysisModel,
)


def _roi():
    return Roi(
        name="ROI 1", kind="circle", geometry=[50.0, 50.0, 10.0], base_anchor=100.0
    )


def test_effective_geometry_is_base_without_overrides():
    assert _roi().effective_geometry(500.0) == [50.0, 50.0, 10.0]


def test_override_applies_from_its_anchor_forward():
    roi = _roi()
    roi.apply_edit(200.0, [60.0, 60.0, 12.0])
    assert roi.effective_geometry(150.0) == [50.0, 50.0, 10.0]
    assert roi.effective_geometry(200.0) == [60.0, 60.0, 12.0]
    assert roi.effective_geometry(999.0) == [60.0, 60.0, 12.0]


def test_latest_applicable_override_wins():
    roi = _roi()
    roi.apply_edit(200.0, [60.0, 60.0, 12.0])
    roi.apply_edit(300.0, [70.0, 70.0, 14.0])
    assert roi.effective_geometry(250.0) == [60.0, 60.0, 12.0]
    assert roi.effective_geometry(350.0) == [70.0, 70.0, 14.0]


def test_edit_at_or_before_base_anchor_updates_base():
    roi = _roi()
    roi.apply_edit(100.0, [55.0, 55.0, 11.0])
    assert roi.geometry == [55.0, 55.0, 11.0]
    assert roi.overrides == {}


def test_clear_overrides_restores_base_everywhere():
    roi = _roi()
    roi.apply_edit(200.0, [60.0, 60.0, 12.0])
    roi.clear_overrides()
    assert roi.effective_geometry(999.0) == [50.0, 50.0, 10.0]


def test_cache_key_changes_only_with_effective_geometry(tmp_path):
    path = tmp_path / "img_2026_07_20-17_46_24_raw.png"
    path.write_bytes(b"")
    model = RoiAnalysisModel()
    roi = _roi()
    model.rois = [roi]
    key_before = model.cache_key(path, roi)
    # An override anchored AFTER this image's capture time: key unchanged.
    roi.apply_edit(9e12, [60.0, 60.0, 12.0])
    assert model.cache_key(path, roi) == key_before
    # An override covering it: key changes.
    roi.apply_edit(0.0, [61.0, 61.0, 12.0])
    assert model.cache_key(path, roi) != key_before


def test_roi_ids_are_unique_and_names_sequence():
    model = RoiAnalysisModel()
    first, second = Roi(), Roi()
    assert first.roi_id != second.roi_id
    model.rois = [first]
    assert model.next_roi_name() == "ROI 2"
```

(In `test_cache_key_...`, `apply_edit(0.0, ...)` with `base_anchor=100.0` updates the base — which also changes the effective geometry. Both branches change the key; the test's point is the *after*-anchor override does not.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py -v`
Expected: FAIL — `ModuleNotFoundError: ...analysis.roi_model`

- [ ] **Step 3: Implement**

`analysis/__init__.py`: empty file.

`analysis/consts.py`:

```python
"""Constants for the ROI intensity-analysis subpackage."""

#: Outline-ring thickness (px) for the perimeter stats — the standalone
#: app's ROIManager default.
OUTLINE_PERIMETER_PX = 2

#: Prefix on the outline-ring stat columns (outline_mean, outline_std, ...).
OUTLINE_STATS_PREFIX = "outline_"

#: Per-experiment folder holding analysis outputs (CSV exports and the
#: persisted ROI definitions).
ANALYSIS_DIR_NAME = "analysis"

#: Persisted ROI definitions (bases + overrides) inside ANALYSIS_DIR_NAME.
ROI_CONFIG_FILENAME = "roi_config.json"

#: Cadence (ms) of the GUI-thread timer draining finished batch results
#: into the model.
ANALYSIS_RESULT_DRAIN_INTERVAL_MS = 200

#: Cadence (ms) of the plot pane's redraw poll.
ROI_PLOT_REFRESH_INTERVAL_MS = 500

#: Smallest ROI dimension (radius / box side, px) a canvas drag may create.
MIN_ROI_SIZE_PX = 3.0
```

`analysis/roi_model.py`:

```python
"""Qt-free ROI analysis state: the ROI definitions (shared base geometry
plus forward drift-overrides), the intensity-stats cache, batch progress,
and the plot-ready series. Mutated only on the GUI thread (button events
and the dock pane's drain timer), so no Qt bridging is needed."""

import uuid
from pathlib import Path

from traits.api import (
    Bool,
    Button,
    Dict,
    Enum,
    Event,
    Float,
    HasTraits,
    Instance,
    Int,
    List,
    Str,
)

from ..discovery import capture_timestamp


class Roi(HasTraits):
    """One region of interest: a shared base geometry applying everywhere,
    plus optional overrides anchored at capture times that apply from
    their anchor forward (drift compensation)."""

    #: Stable identity used in cache keys and result columns.
    roi_id = Str()

    #: Display name (also the CSV column prefix and plot legend label).
    name = Str()

    #: Shape. Circle geometry is [center_x, center_y, radius]; box
    #: geometry is [x, y, width, height] with (x, y) the top-left corner.
    #: All values are image-pixel floats.
    kind = Enum("circle", "box")

    #: Base geometry, applying to every image without a later override.
    geometry = List(Float)

    #: Capture time of the image the ROI was created on — edits at or
    #: before it update the base instead of adding an override.
    base_anchor = Float(0.0)

    #: anchor capture time -> geometry; an override applies from its
    #: anchor forward until the next override.
    overrides = Dict(Float, List)

    def _roi_id_default(self):
        return uuid.uuid4().hex[:8]

    def effective_geometry(self, capture_time):
        """The geometry in force for an image captured at
        ``capture_time``: the override with the greatest anchor at or
        before it, else the base geometry."""
        anchors = [anchor for anchor in self.overrides if anchor <= capture_time]
        if anchors:
            return list(self.overrides[max(anchors)])
        return list(self.geometry)

    def apply_edit(self, capture_time, geometry):
        """Record an edit made while viewing the image captured at
        ``capture_time``: at or before the base anchor it updates the
        base, later it upserts a forward override."""
        if capture_time <= self.base_anchor:
            self.geometry = list(geometry)
        else:
            self.overrides[capture_time] = list(geometry)

    def clear_overrides(self):
        self.overrides = {}


class RoiAnalysisModel(HasTraits):
    """Shared state between the viewer pane (ROI editing, toolbuttons)
    and the plot pane (series display)."""

    rois = List(Instance(Roi))

    #: Canvas interaction: pan (normal navigation), one-shot draw modes,
    #: or edit (move/resize/select existing ROIs).
    interaction_mode = Enum("pan", "draw_circle", "draw_box", "edit")

    #: roi_id of the canvas-selected ROI (edit mode), '' when none.
    selected_roi_id = Str()

    #: (path str, mtime, roi_id, kind, geometry tuple) -> stats dict.
    #: The geometry in the key makes invalidation implicit: an edit only
    #: misses on the images its override actually covers.
    cache = Dict()

    #: Instant-stats readout for the ROI just drawn/edited.
    roi_info_text = Str()

    #: Batch progress readout ("12/40, 1 failed"; '' when idle).
    progress_text = Str()
    batch_total = Int(0)
    batch_done = Int(0)
    batch_failed = Int(0)
    batch_running = Bool(False)

    #: Plot-ready series: roi_id -> (name, [elapsed_sec...], [mean...]).
    plot_series = Dict()

    #: Bumped whenever plot_series is rebuilt (the plot canvas polls it).
    plot_revision = Int(0)

    # Toolbar buttons (view events; RoiAnalysisController reacts).
    draw_circle_button = Button()
    draw_box_button = Button()
    edit_mode = Bool(False)
    delete_roi_button = Button()
    clear_rois_button = Button()
    calculate_button = Button()
    export_csv_button = Button()
    reset_cache_button = Button()

    #: View -> controller channels fired by the canvas ROI layer.
    canvas_roi_created = Event()  # (kind, geometry)
    canvas_roi_edited = Event()  # (roi_id, geometry)

    def roi_by_id(self, roi_id):
        for roi in self.rois:
            if roi.roi_id == roi_id:
                return roi
        return None

    def next_roi_name(self):
        return f"ROI {len(self.rois) + 1}"

    def cache_key(self, path, roi):
        """Cache key for one (image, ROI) pair: the file identity/mtime
        plus the geometry in force at the image's capture time."""
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        return (
            str(path),
            mtime,
            roi.roi_id,
            roi.kind,
            tuple(roi.effective_geometry(capture_timestamp(path))),
        )

    def effective_for(self, path):
        """[(roi_id, name, kind, geometry), ...] in force for ``path`` —
        what the canvas draws and the batch computes for that image."""
        capture_time = capture_timestamp(path)
        return [
            (roi.roi_id, roi.name, roi.kind, roi.effective_geometry(capture_time))
            for roi in self.rois
        ]


#: The single analysis state shared by the viewer pane and the plot pane
#: (both owned by this plugin) — the media_capture_event_model pattern.
roi_analysis_model = RoiAnalysisModel()
```

In `image_viewer/model.py`, add the import (with the other relative imports):

```python
from .analysis.roi_model import RoiAnalysisModel, roi_analysis_model
```

and add to `FluorescenceImageViewerModel` (near the `preferences` trait):

```python
#: ROI intensity-analysis state (shared with the plot pane).
roi_analysis = Instance(RoiAnalysisModel)


def _roi_analysis_default(self):
    return roi_analysis_model
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis fluorescence_controls_ui/image_viewer/model.py fluorescence_controls_ui/tests/test_roi_model.py
git commit -m "feat(image-viewer): add ROI analysis model layer" -m "Roi (base geometry + forward drift overrides anchored at capture times) and RoiAnalysisModel (geometry-hashed stats cache, batch progress, plot series, toolbutton traits), shared as a module singleton between viewer and plot panes."
```

---

### Task 4: Pure compute layer

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_compute.py`
- Test: `fluorescence_controls_ui/tests/test_roi_compute.py` (create)

**Interfaces:**
- Consumes: `OUTLINE_PERIMETER_PX`, `OUTLINE_STATS_PREFIX` (Task 3 consts).
- Produces: `STAT_NAMES = ("mean", "std", "median", "min", "max", "count")`; `roi_masks(shape, kind, geometry) -> (interior, outline)` uint8 masks; `masked_stats(array, mask) -> dict`; `compute_image_stats(image_path, effective_rois) -> dict` where `effective_rois` is `{roi_id: (kind, geometry_tuple)}` and the return is `{"path": str, "mtime": float, "stats": {roi_id: {mean..., outline_mean...}}, "error": str | None}`. Module-level function — picklable for `ProcessPoolExecutor` (Windows spawn). Tasks 5 and 8 rely on these exact names and shapes.

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_roi_compute.py
"""ROI mask/stats math against synthetic arrays."""

import math

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats,
    masked_stats,
    roi_masks,
)


def test_box_interior_stats_on_uniform_patch():
    array = np.zeros((40, 40), dtype=np.uint16)
    array[10:20, 10:20] = 1000
    interior, _outline = roi_masks((40, 40), "box", [10.0, 10.0, 9.0, 9.0])
    stats = masked_stats(array, interior)
    assert stats["mean"] == 1000.0
    assert stats["std"] == 0.0
    assert stats["min"] == stats["max"] == 1000.0
    assert stats["count"] == 100.0  # cv2.rectangle corners are inclusive


def test_circle_mask_is_filled_disk():
    interior, outline = roi_masks((100, 100), "circle", [50.0, 50.0, 10.0])
    area = np.count_nonzero(interior)
    assert abs(area - math.pi * 10**2) / area < 0.15
    assert 0 < np.count_nonzero(outline) < area


def test_roi_outside_image_yields_nan_stats():
    array = np.zeros((20, 20), dtype=np.uint16)
    interior, _outline = roi_masks((20, 20), "circle", [500.0, 500.0, 5.0])
    stats = masked_stats(array, interior)
    assert stats["count"] == 0.0
    assert math.isnan(stats["mean"])


def test_compute_image_stats_reads_16bit_png(tmp_path):
    array = np.full((30, 30), 500, dtype=np.uint16)
    array[5:15, 5:15] = 2000
    path = tmp_path / "img_2026_07_20-17_46_24_raw.png"
    cv2.imwrite(str(path), array)
    result = compute_image_stats(str(path), {"roi1": ("box", (5.0, 5.0, 9.0, 9.0))})
    assert result["error"] is None
    assert result["stats"]["roi1"]["mean"] == 2000.0
    assert "outline_mean" in result["stats"]["roi1"]
    assert result["mtime"] > 0


def test_compute_image_stats_reports_unreadable_file(tmp_path):
    path = tmp_path / "broken_raw.png"
    path.write_bytes(b"not a png")
    result = compute_image_stats(str(path), {"roi1": ("circle", (5.0, 5.0, 2.0))})
    assert result["error"] is not None
    assert result["stats"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_compute.py -v`
Expected: FAIL — `ModuleNotFoundError: ...roi_compute`

- [ ] **Step 3: Implement**

```python
# fluorescence_controls_ui/image_viewer/analysis/roi_compute.py
"""Pure per-image ROI statistics (Qt-free and importable by spawned
worker processes): interior + outline-ring masks for circle/box ROIs and
the summary stats of the masked pixels. Ported from the standalone
fluorescence app's ROIManager (image_tools.py)."""

import os

import cv2
import numpy as np

from .consts import OUTLINE_PERIMETER_PX, OUTLINE_STATS_PREFIX

#: Stats computed for every mask, in column order.
STAT_NAMES = ("mean", "std", "median", "min", "max", "count")


def roi_masks(shape, kind, geometry, perimeter_px=OUTLINE_PERIMETER_PX):
    """(interior, outline) uint8 masks (255 inside) for one ROI on an
    image of ``shape`` (height, width); cv2 clips to the image bounds."""
    interior = np.zeros(shape, dtype=np.uint8)
    outline = np.zeros(shape, dtype=np.uint8)
    if kind == "circle":
        center_x, center_y, radius = geometry
        center = (int(round(center_x)), int(round(center_y)))
        cv2.circle(interior, center, int(round(radius)), 255, -1)
        cv2.circle(outline, center, int(round(radius)), 255, perimeter_px)
    else:
        x, y, width, height = geometry
        top_left = (int(round(x)), int(round(y)))
        bottom_right = (int(round(x + width)), int(round(y + height)))
        cv2.rectangle(interior, top_left, bottom_right, 255, -1)
        cv2.rectangle(outline, top_left, bottom_right, 255, perimeter_px)
    return interior, outline


def masked_stats(array, mask):
    """mean/std/median/min/max/count of ``array`` under ``mask`` — NaN
    stats with count 0 for an empty mask (ROI fully outside the image)."""
    pixels = array[mask == 255]
    if pixels.size == 0:
        stats = {name: float("nan") for name in STAT_NAMES}
        stats["count"] = 0.0
        return stats
    return {
        "mean": float(np.mean(pixels)),
        "std": float(np.std(pixels)),
        "median": float(np.median(pixels)),
        "min": float(np.min(pixels)),
        "max": float(np.max(pixels)),
        "count": float(np.count_nonzero(mask)),
    }


def compute_image_stats(image_path, effective_rois):
    """Stats for every ROI on one image — the process-pool work unit.

    ``effective_rois``: roi_id -> (kind, geometry tuple), the geometries
    in force for THIS image. Returns {"path", "mtime", "stats":
    {roi_id: {mean..., outline_mean...}}, "error"}; a load failure fills
    "error" and leaves "stats" empty (the caller counts it as failed)."""
    result = {"path": str(image_path), "mtime": 0.0, "stats": {}, "error": None}
    try:
        result["mtime"] = os.path.getmtime(image_path)
        array = cv2.imread(str(image_path), cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)
        if array is None:
            raise ValueError("unreadable image")
        for roi_id, (kind, geometry) in effective_rois.items():
            interior, outline = roi_masks(array.shape[:2], kind, geometry)
            stats = masked_stats(array, interior)
            for name, value in masked_stats(array, outline).items():
                stats[OUTLINE_STATS_PREFIX + name] = value
            result["stats"][roi_id] = stats
    except Exception as error:
        result["error"] = str(error)
        result["stats"] = {}
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: 5 PASS. If `test_box_interior_stats_on_uniform_patch` fails on `count` (cv2 corner inclusivity), adjust the box geometry in the TEST to `[10.0, 10.0, 9.0, 9.0]` ↔ expected count 100 so the mask covers exactly the 10×10 patch — do not change the implementation.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_compute.py fluorescence_controls_ui/tests/test_roi_compute.py
git commit -m "feat(image-viewer): add pure ROI stats compute layer" -m "Interior + outline-ring masks and mean/std/median/min/max/count per ROI on 16-bit raws, as a picklable module-level work unit for the process pool. Ported from the standalone app's ROIManager."
```

---

### Task 5: Batch runner (thread + process pool)

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_batch.py`
- Test: `fluorescence_controls_ui/tests/test_roi_batch.py` (create)

**Interfaces:**
- Consumes: `compute_image_stats` (Task 4).
- Produces: queue-message constants `BATCH_RESULT = "result"`, `BATCH_FINISHED = "finished"`, `INSTANT_RESULT = "instant"`; `RoiBatchRunner(HasTraits)` with trait `results` (a `queue.SimpleQueue` of `(kind, payload)`, REPLACED on every `start()` so stale results die with the old queue) and methods `start(work_items)` (`work_items = [(path_str, effective_rois_dict), ...]`), `cancel()`, `compute_single(path, effective_rois)`. Task 8 drains `runner.results`.

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_roi_batch.py
"""Batch runner end-to-end on tiny synthetic images (real process pool)."""

import queue
import time

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_batch import (
    BATCH_FINISHED,
    BATCH_RESULT,
    INSTANT_RESULT,
    RoiBatchRunner,
)


def _drain_until(results, wanted_kind, timeout_s=60.0):
    messages = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            message = results.get(timeout=0.5)
        except queue.Empty:
            continue
        messages.append(message)
        if message[0] == wanted_kind:
            return messages
    raise AssertionError(f"no {wanted_kind} within {timeout_s}s: {messages}")


def _write_image(path, value):
    cv2.imwrite(str(path), np.full((20, 20), value, dtype=np.uint16))


def test_batch_computes_all_images_and_finishes(tmp_path):
    paths = []
    for index, value in enumerate((100, 200)):
        path = tmp_path / f"img{index}_raw.png"
        _write_image(path, value)
        paths.append(str(path))
    rois = {"r1": ("box", (2.0, 2.0, 10.0, 10.0))}
    runner = RoiBatchRunner()
    runner.start([(path, rois) for path in paths])
    messages = _drain_until(runner.results, BATCH_FINISHED)
    payloads = [payload for kind, payload in messages if kind == BATCH_RESULT]
    assert sorted(payload["stats"]["r1"]["mean"] for payload in payloads) == [
        100.0,
        200.0,
    ]


def test_compute_single_reports_on_queue(tmp_path):
    path = tmp_path / "one_raw.png"
    _write_image(path, 300)
    runner = RoiBatchRunner()
    runner.compute_single(str(path), {"r1": ("circle", (10.0, 10.0, 4.0))})
    messages = _drain_until(runner.results, INSTANT_RESULT, timeout_s=15.0)
    kind, payload = messages[-1]
    assert payload["stats"]["r1"]["mean"] == 300.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: ...roi_batch`

- [ ] **Step 3: Implement**

```python
# fluorescence_controls_ui/image_viewer/analysis/roi_batch.py
"""Off-GUI batch computation: a daemon orchestrator thread (the plugin's
established off-GUI pattern) fans the images out to a process pool and
streams results back through a thread-safe queue that the dock pane's
drain timer empties on the GUI thread. One batch at a time — start()
cancels any running one and swaps in a fresh queue, so a superseded
batch's stragglers die with the old queue."""

import os
import queue
import threading
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)

from traits.api import Any, HasTraits

from logger.logger_service import get_logger

from .roi_compute import compute_image_stats

logger = get_logger(__name__)

#: Queue message kinds: per-image batch result, end-of-batch marker, and
#: the single-image instant-feedback result.
BATCH_RESULT = "result"
BATCH_FINISHED = "finished"
INSTANT_RESULT = "instant"


def _pool_workers():
    return max((os.cpu_count() or 2) - 1, 1)


class RoiBatchRunner(HasTraits):
    """Runs compute_image_stats over a work list off the GUI thread."""

    #: GUI-drained result queue of (kind, payload) tuples; replaced on
    #: every start() so a cancelled batch's late results are discarded.
    results = Any()

    _thread = Any()
    _cancel = Any()

    def _results_default(self):
        return queue.SimpleQueue()

    def _cancel_default(self):
        return threading.Event()

    def start(self, work_items):
        """``work_items``: [(path, effective_rois), ...] with
        ``effective_rois`` = roi_id -> (kind, geometry tuple)."""
        self.cancel()
        self.results = queue.SimpleQueue()
        self._cancel = threading.Event()
        cancel, results = self._cancel, self.results
        self._thread = threading.Thread(
            target=self._run, args=(list(work_items), cancel, results), daemon=True
        )
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def compute_single(self, path, effective_rois):
        """Instant feedback for a freshly drawn/edited ROI on the shown
        image: one off-thread compute, reported on the same queue."""
        results = self.results
        thread = threading.Thread(
            target=lambda: results.put(
                (INSTANT_RESULT, compute_image_stats(path, effective_rois))
            ),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _run(work_items, cancel, results):
        try:
            executor = ProcessPoolExecutor(max_workers=_pool_workers())
        except Exception as error:
            logger.warning(
                f"Process pool unavailable, falling back to threads: {error}"
            )
            executor = ThreadPoolExecutor(max_workers=_pool_workers())
        with executor:
            futures = [
                executor.submit(compute_image_stats, path, rois)
                for path, rois in work_items
            ]
            for future in as_completed(futures):
                if cancel.is_set():
                    for pending in futures:
                        pending.cancel()
                    return
                try:
                    results.put((BATCH_RESULT, future.result()))
                except Exception as error:
                    # Pool infrastructure failure (the work unit itself
                    # reports its errors inside the payload).
                    logger.warning(f"ROI batch worker failed: {error}")
        if not cancel.is_set():
            results.put((BATCH_FINISHED, None))
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: 2 PASS (allow ~30 s — Windows process-pool spawn is slow the first time).

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_batch.py fluorescence_controls_ui/tests/test_roi_batch.py
git commit -m "feat(image-viewer): add ROI batch compute runner" -m "Daemon orchestrator thread + ProcessPoolExecutor (thread-pool fallback) streaming per-image results into a queue the GUI drains; start() swaps the queue so superseded batches die silently."
```

---

### Task 6: Persistence (ROI config JSON + intensity CSV)

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py`
- Test: `fluorescence_controls_ui/tests/test_roi_store.py` (create)

**Interfaces:**
- Consumes: `Roi` (Task 3), `STAT_NAMES`/`OUTLINE_STATS_PREFIX` (Task 4/3), `ANALYSIS_DIR_NAME`, `ROI_CONFIG_FILENAME`.
- Produces: `analysis_directory(experiment_directory) -> Path` (created on demand); `save_roi_config(experiment_directory, rois)`; `load_roi_config(experiment_directory) -> list[Roi]` (`[]` on missing/corrupt); `write_intensity_csv(csv_path, rows, rois)` where each row is `{"filename", "time_utc", "elapsed_sec", "group", "wavelength", "stats": {roi_id: stats_dict}}` and columns are `index,time_utc,elapsed_sec,filename,group,wavelength` then `<roi name>_<stat>` for every ROI × (`STAT_NAMES` + outline-prefixed), blank for missing. Task 8 relies on these names.

- [ ] **Step 1: Write the failing test**

```python
# fluorescence_controls_ui/tests/test_roi_store.py
"""ROI config JSON round-trip and intensity-CSV layout."""

import csv

from fluorescence_controls_ui.image_viewer.analysis.roi_model import Roi
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_config,
    save_roi_config,
    write_intensity_csv,
)


def test_roi_config_round_trip(tmp_path):
    roi = Roi(
        name="ROI 1", kind="circle", geometry=[50.0, 50.0, 10.0], base_anchor=100.0
    )
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
    rows = [
        {
            "filename": "img_raw.png",
            "time_utc": "2026_07_20-17_46_24",
            "elapsed_sec": 0.0,
            "group": "burst_a",
            "wavelength": "Green 540 nm",
            "stats": {
                roi.roi_id: {
                    "mean": 10.0,
                    "std": 1.0,
                    "median": 10.0,
                    "min": 8.0,
                    "max": 12.0,
                    "count": 25.0,
                    "outline_mean": 9.0,
                    "outline_std": 1.0,
                    "outline_median": 9.0,
                    "outline_min": 8.0,
                    "outline_max": 10.0,
                    "outline_count": 16.0,
                }
            },
        },
        {
            "filename": "img2_raw.png",
            "time_utc": "2026_07_20-17_46_25",
            "elapsed_sec": 1.0,
            "group": "burst_a",
            "wavelength": "Green 540 nm",
            "stats": {},  # not computed: blank cells
        },
    ]
    csv_path = tmp_path / "out.csv"
    write_intensity_csv(csv_path, rows, [roi])
    with open(csv_path, newline="") as handle:
        records = list(csv.reader(handle))
    assert records[0][:6] == [
        "index",
        "time_utc",
        "elapsed_sec",
        "filename",
        "group",
        "wavelength",
    ]
    assert "ROI 1_mean" in records[0]
    assert "ROI 1_outline_count" in records[0]
    mean_column = records[0].index("ROI 1_mean")
    assert records[1][mean_column] == "10.0"
    assert records[2][mean_column] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py -v`
Expected: FAIL — `ModuleNotFoundError: ...roi_store`

- [ ] **Step 3: Implement**

```python
# fluorescence_controls_ui/image_viewer/analysis/roi_store.py
"""Persistence for the ROI analysis: the per-experiment roi_config.json
(bases + overrides, auto-saved on change and auto-loaded per experiment)
and the intensity CSV export. Qt-free, pure file IO."""

import csv
import json
from pathlib import Path

from logger.logger_service import get_logger

from .consts import ANALYSIS_DIR_NAME, OUTLINE_STATS_PREFIX, ROI_CONFIG_FILENAME
from .roi_compute import STAT_NAMES
from .roi_model import Roi

logger = get_logger(__name__)


def analysis_directory(experiment_directory) -> Path:
    """The experiment's analysis output folder, created on demand."""
    directory = Path(experiment_directory) / ANALYSIS_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_roi_config(experiment_directory, rois):
    payload = [
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
        }
        for roi in rois
    ]
    path = analysis_directory(experiment_directory) / ROI_CONFIG_FILENAME
    path.write_text(json.dumps(payload, indent=2))


def load_roi_config(experiment_directory) -> list:
    """The experiment's saved ROIs, [] when absent or unreadable."""
    path = Path(experiment_directory) / ANALYSIS_DIR_NAME / ROI_CONFIG_FILENAME
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
        return [
            Roi(
                roi_id=entry["roi_id"],
                name=entry["name"],
                kind=entry["kind"],
                geometry=[float(value) for value in entry["geometry"]],
                base_anchor=float(entry["base_anchor"]),
                overrides={
                    float(anchor): [float(value) for value in geometry]
                    for anchor, geometry in entry["overrides"].items()
                },
            )
            for entry in payload
        ]
    except Exception as error:
        logger.warning(f"Could not load ROI config {path}: {error}")
        return []


#: Per-ROI CSV columns, in order: interior stats then outline stats.
CSV_STAT_COLUMNS = tuple(STAT_NAMES) + tuple(
    OUTLINE_STATS_PREFIX + name for name in STAT_NAMES
)


def write_intensity_csv(csv_path, rows, rois):
    """One row per image, blank cells where an (image, ROI) pair has no
    computed stats. ``rows``: [{"filename", "time_utc", "elapsed_sec",
    "group", "wavelength", "stats": {roi_id: stats_dict}}, ...]."""
    header = ["index", "time_utc", "elapsed_sec", "filename", "group", "wavelength"]
    for roi in rois:
        header += [f"{roi.name}_{stat}" for stat in CSV_STAT_COLUMNS]
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index, row in enumerate(rows):
            record = [
                index,
                row["time_utc"],
                row["elapsed_sec"],
                row["filename"],
                row["group"],
                row["wavelength"],
            ]
            for roi in rois:
                stats = row["stats"].get(roi.roi_id, {})
                record += [stats.get(stat, "") for stat in CSV_STAT_COLUMNS]
            writer.writerow(record)
```

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2. Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(image-viewer): persist ROI config and intensity CSV" -m "roi_config.json round-trips bases + overrides per experiment; write_intensity_csv lays out one row per image with per-ROI interior + outline stat columns."
```

---

### Task 7: Canvas ROI layer (Qt graphics items + viewer integration)

**Files:**
- Modify: `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py\src\microdrop_style\icons\icons.py` (4 new ligature constants — NOTE: this file is in the Microdrop source submodule `microdrop-py/src`, a DIFFERENT git repo; commit it there separately)
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_items.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (`_ImageView`, `_ImageCanvasEditor`)

**Interfaces:**
- Consumes: `RoiAnalysisModel.effective_for/interaction_mode/selected_roi_id/canvas_roi_created/canvas_roi_edited` (Task 3), `MIN_ROI_SIZE_PX`.
- Produces: `CircleRoiItem`/`BoxRoiItem` (`roi_id` attr, `set_geometry(list)`, `geometry() -> list`, `set_editable(bool)`); `RoiCanvasLayer(scene)` with attributes `mode`, callbacks `on_roi_created(kind, geometry)`, `on_roi_edited(roi_id, geometry)`, `on_roi_selected(roi_id)`, and methods `set_mode(mode)`, `sync(effective, selected_roi_id)`, `mouse_press/mouse_move/mouse_release(scene_point) -> bool`. Icons: `ICON_CIRCLE = "circle"`, `ICON_RECTANGLE = "rectangle"`, `ICON_SHOW_CHART = "show_chart"`, `ICON_DELETE_SWEEP = "delete_sweep"` (Task 9 uses them).

- [ ] **Step 1: Add the icon constants**

In `microdrop_style/icons/icons.py`, after the `ICON_ARCHIVE` line (line 51):

```python
ICON_CIRCLE = "circle"  # draw circular ROI
ICON_RECTANGLE = "rectangle"  # draw rectangular ROI
ICON_SHOW_CHART = "show_chart"  # calculate & plot intensities
ICON_DELETE_SWEEP = "delete_sweep"  # clear all ROIs
```

- [ ] **Step 2: Implement roi_items.py**

```python
# fluorescence_controls_ui/image_viewer/analysis/roi_items.py
"""Qt graphics layer for ROI drawing/editing on the image canvas: the
circle/box item classes with a drag-resize corner grip, and the
RoiCanvasLayer that owns them on the image scene and turns the canvas's
forwarded mouse events into creation/edit callbacks. The layer never
touches the model — the canvas editor wires its callbacks to the
analysis model's canvas_* event traits and the controller reacts."""

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from .consts import MIN_ROI_SIZE_PX

#: Cosmetic (zoom-independent 1px) pens; cyan reads on dark raws.
ROI_PEN = QPen(QColor(0, 229, 255), 0)
ROI_SELECTED_PEN = QPen(QColor(255, 214, 0), 0)
HANDLE_BRUSH = QBrush(QColor(255, 214, 0))
HANDLE_SIZE_PX = 9.0


class _ResizeHandle(QGraphicsRectItem):
    """Drag grip riding the parent ROI's edge; dragging resizes it."""

    def __init__(self, parent):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX, parent)
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem().resize_to(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem().commit_geometry()
        event.accept()


class _RoiItemBase:
    """Shared behavior mixed into the two shape items: identity, label,
    grip, edit-mode flags, and commit-on-release."""

    def _setup(self, roi_id, name, on_edited):
        self.roi_id = roi_id
        self._on_edited = on_edited
        self.setPen(ROI_PEN)
        self._label = QGraphicsSimpleTextItem(name, self)
        self._label.setBrush(QBrush(ROI_PEN.color()))
        self._label.setFlag(self._label.GraphicsItemFlag.ItemIgnoresTransformations)
        self._handle = _ResizeHandle(self)

    def set_editable(self, editable):
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, editable)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, editable)
        self._handle.setVisible(editable)

    def set_name(self, name):
        self._label.setText(name)

    def set_selected_style(self, selected):
        self.setPen(ROI_SELECTED_PEN if selected else ROI_PEN)
        self._label.setBrush(QBrush(self.pen().color()))

    def commit_geometry(self):
        self._on_edited(self.roi_id, self.geometry())

    def mouseReleaseEvent(self, event):
        # Ends a move drag: report the moved geometry.
        super().mouseReleaseEvent(event)
        if self.flags() & self.GraphicsItemFlag.ItemIsMovable:
            self.commit_geometry()


class CircleRoiItem(_RoiItemBase, QGraphicsEllipseItem):
    """Circle ROI: geometry [center_x, center_y, radius]."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsEllipseItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        center_x, center_y, radius = geometry
        self.setPos(0, 0)
        self.setRect(center_x - radius, center_y - radius, 2 * radius, 2 * radius)
        self._place_attachments()

    def geometry(self):
        center = self.rect().center() + self.pos()
        return [center.x(), center.y(), self.rect().width() / 2]

    def resize_to(self, scene_point):
        point = self.mapFromScene(scene_point)
        center = self.rect().center()
        radius = max(
            math.hypot(point.x() - center.x(), point.y() - center.y()), MIN_ROI_SIZE_PX
        )
        self.setRect(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        self._place_attachments()

    def _place_attachments(self):
        rect = self.rect()
        offset = rect.width() / 2 * math.sqrt(0.5)
        self._handle.setPos(rect.center().x() + offset, rect.center().y() + offset)
        self._label.setPos(rect.left(), rect.top() - 2)


class BoxRoiItem(_RoiItemBase, QGraphicsRectItem):
    """Box ROI: geometry [x, y, width, height] (top-left corner)."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsRectItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        x, y, width, height = geometry
        self.setPos(0, 0)
        self.setRect(x, y, width, height)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        return [
            rect.x() + self.pos().x(),
            rect.y() + self.pos().y(),
            rect.width(),
            rect.height(),
        ]

    def resize_to(self, scene_point):
        point = self.mapFromScene(scene_point)
        rect = self.rect()
        rect.setRight(max(point.x(), rect.left() + MIN_ROI_SIZE_PX))
        rect.setBottom(max(point.y(), rect.top() + MIN_ROI_SIZE_PX))
        self.setRect(rect)
        self._place_attachments()

    def _place_attachments(self):
        rect = self.rect()
        self._handle.setPos(rect.right(), rect.bottom())
        self._label.setPos(rect.left(), rect.top() - 2)


class RoiCanvasLayer:
    """Owns the ROI items on the image scene (stateless wiring around Qt
    items, so it stays a plain class). The canvas view forwards mouse
    events here when the interaction mode isn't pan; creation/edit/
    selection are reported through the three callbacks."""

    def __init__(self, scene):
        self._scene = scene
        self._items = {}  # roi_id -> item
        self._draft = None  # item being rubber-band drawn
        self._draft_kind = ""
        self._press_point = None
        self.mode = "pan"
        self.on_roi_created = lambda kind, geometry: None
        self.on_roi_edited = lambda roi_id, geometry: None
        self.on_roi_selected = lambda roi_id: None
        self._scene.selectionChanged.connect(self._selection_changed)

    def set_mode(self, mode):
        self.mode = mode
        for item in self._items.values():
            item.set_editable(mode == "edit")

    def sync(self, effective, selected_roi_id):
        """Match the items to ``effective`` ([(roi_id, name, kind,
        geometry), ...] for the SHOWN image) — create, update, drop."""
        wanted = {
            roi_id: (name, kind, geometry) for roi_id, name, kind, geometry in effective
        }
        for roi_id in list(self._items):
            if roi_id not in wanted:
                self._scene.removeItem(self._items.pop(roi_id))
        for roi_id, (name, kind, geometry) in wanted.items():
            item = self._items.get(roi_id)
            item_class = CircleRoiItem if kind == "circle" else BoxRoiItem
            if item is not None and not isinstance(item, item_class):
                self._scene.removeItem(self._items.pop(roi_id))
                item = None
            if item is None:
                item = item_class(roi_id, name, geometry, self.on_roi_edited)
                item.set_editable(self.mode == "edit")
                self._scene.addItem(item)
                self._items[roi_id] = item
            elif not item.isSelected():
                # The selected item may be mid-drag: don't yank it.
                item.set_geometry(geometry)
                item.set_name(name)
            item.set_selected_style(roi_id == selected_roi_id)

    def clear_items(self):
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items = {}

    # ------------------------------------------------------------------ #
    # Mouse events forwarded by the canvas view (scene coordinates).      #
    # Return True when handled (the view then skips its own handling).    #
    # ------------------------------------------------------------------ #
    def mouse_press(self, scene_point):
        if self.mode not in ("draw_circle", "draw_box"):
            return False
        self._press_point = scene_point
        self._draft_kind = "circle" if self.mode == "draw_circle" else "box"
        if self._draft_kind == "circle":
            self._draft = QGraphicsEllipseItem()
        else:
            self._draft = QGraphicsRectItem()
        self._draft.setPen(ROI_SELECTED_PEN)
        self._scene.addItem(self._draft)
        return True

    def mouse_move(self, scene_point):
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        if self._draft_kind == "circle":
            center_x, center_y, radius = geometry
            self._draft.setRect(
                center_x - radius, center_y - radius, 2 * radius, 2 * radius
            )
        else:
            self._draft.setRect(*geometry)
        return True

    def mouse_release(self, scene_point):
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        self._scene.removeItem(self._draft)
        self._draft = None
        size = (
            geometry[2]
            if self._draft_kind == "circle"
            else min(geometry[2], geometry[3])
        )
        if size >= MIN_ROI_SIZE_PX:
            self.on_roi_created(self._draft_kind, geometry)
        return True

    def _drag_geometry(self, scene_point):
        """Geometry of the press->current drag: press point = circle
        center / box corner."""
        press = self._press_point
        if self._draft_kind == "circle":
            radius = math.hypot(
                scene_point.x() - press.x(), scene_point.y() - press.y()
            )
            return [press.x(), press.y(), radius]
        x = min(press.x(), scene_point.x())
        y = min(press.y(), scene_point.y())
        return [
            x,
            y,
            abs(scene_point.x() - press.x()),
            abs(scene_point.y() - press.y()),
        ]

    def _selection_changed(self):
        for roi_id, item in self._items.items():
            if item.isSelected():
                self.on_roi_selected(roi_id)
                return
        self.on_roi_selected("")
```

- [ ] **Step 3: Integrate with the canvas view**

In `view.py`:

Add imports: `from .analysis.roi_items import RoiCanvasLayer`.

`_ImageView.__init__` gains a `roi_layer` parameter (stored as `self._roi_layer`), and the three mouse handlers forward first:

```python
def __init__(self, scene, on_hover, roi_layer):
    super().__init__(scene)
    self._on_hover = on_hover
    self._roi_layer = roi_layer
    ...  # rest unchanged


def mousePressEvent(self, event):
    point = self.mapToScene(event.position().toPoint())
    if self._roi_layer.mouse_press(point):
        event.accept()
        return
    super().mousePressEvent(event)


def mouseMoveEvent(self, event):
    point = self.mapToScene(event.position().toPoint())
    self._on_hover(int(point.x()), int(point.y()))
    if self._roi_layer.mouse_move(point):
        event.accept()
        return
    super().mouseMoveEvent(event)


def mouseReleaseEvent(self, event):
    point = self.mapToScene(event.position().toPoint())
    if self._roi_layer.mouse_release(point):
        event.accept()
        return
    super().mouseReleaseEvent(event)
```

`_ImageCanvasEditor.init` creates the layer, wires callbacks to the analysis model, and observes analysis state (`self.object` is the viewer model):

```python
def init(self, parent):
    self._scene = QGraphicsScene()
    self._pixmap_item = QGraphicsPixmapItem()
    self._scene.addItem(self._pixmap_item)
    self._roi_layer = RoiCanvasLayer(self._scene)
    analysis = self.object.roi_analysis
    self._roi_layer.on_roi_created = lambda kind, geometry: analysis.trait_set(
        canvas_roi_created=(kind, geometry)
    )
    self._roi_layer.on_roi_edited = lambda roi_id, geometry: analysis.trait_set(
        canvas_roi_edited=(roi_id, geometry)
    )
    self._roi_layer.on_roi_selected = lambda roi_id: analysis.trait_set(
        selected_roi_id=roi_id
    )
    self.control = _ImageView(self._scene, self._on_hover, self._roi_layer)
    self.object.observe(
        self._on_window_changed, "auto_contrast, window_min, window_max"
    )
    self.object.observe(self._on_fit_request, "fit_request")
    self.object.observe(
        self._on_roi_state_changed,
        "current_path, roi_analysis:rois.items, "
        "roi_analysis:rois:items:geometry, "
        "roi_analysis:rois:items:overrides:items, "
        "roi_analysis:selected_roi_id",
    )
    self.object.observe(
        self._on_interaction_mode_changed, "roi_analysis:interaction_mode"
    )
```

with matching removals in `dispose()` (same patterns, `remove=True`), and the two new handlers + a sync call at the end of `update_editor`:

```python
def update_editor(self):
    # A new image arrived in `array`: redraw and refit.
    self._redraw()
    self.control.fit()
    self._sync_roi_layer()


def _on_roi_state_changed(self, event):
    self._sync_roi_layer()


def _sync_roi_layer(self):
    model = self.object
    if not model.current_path or model.array is None:
        self._roi_layer.clear_items()
        return
    self._roi_layer.sync(
        model.roi_analysis.effective_for(model.current_path),
        model.roi_analysis.selected_roi_id,
    )


def _on_interaction_mode_changed(self, event):
    mode = event.new
    self._roi_layer.set_mode(mode)
    self.control.setDragMode(
        self.control.DragMode.ScrollHandDrag
        if mode == "pan"
        else self.control.DragMode.NoDrag
    )
```

- [ ] **Step 4: Import smoke check**

Run (from `microdrop-py`): `pixi run python -c "import fluorescence_controls_ui.image_viewer.view; import fluorescence_controls_ui.image_viewer.analysis.roi_items; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit (two repos)**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_items.py fluorescence_controls_ui/image_viewer/view.py
git commit -m "feat(image-viewer): draw/edit ROI layer on the canvas" -m "Circle/box QGraphics items with a resize grip and name label; RoiCanvasLayer handles rubber-band creation and edit-mode moves, reporting through the analysis model's canvas events. Canvas editor syncs items to each shown image's effective geometry."
cd ../..   # microdrop-py/src (the Microdrop submodule repo)
git add microdrop_style/icons/icons.py
git commit -m "feat(icons): add ROI analysis glyphs" -m "circle/rectangle/show_chart/delete_sweep ligatures for the fluorescence ROI toolbuttons."
cd fluorescence-microdrop-plugin-py
```

---

### Task 8: RoiAnalysisController + dock-pane wiring

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/dock_pane.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6 (`capture_timestamp`, `BURST_FILTER_ALL` behavior via `viewer_model.paths`, `Roi`, `RoiAnalysisModel`, `RoiBatchRunner` + message kinds, `roi_store` functions, `compute_image_stats` payload shape), `pyface_wrapper.confirm`, `pyface.api.YES/NO`, `CAPTURES_DIR_NAME`, `sanitize_label`, `utc_stamp`, `detect_wavelength`, `UNGROUPED_BURST`, `CAPTURE_TIMESTAMP_FORMAT`.
- Produces: `RoiAnalysisController(HasTraits)` with traits `viewer_model`, `analysis_model`, `runner` and the public method `drain_results()` (called by the dock pane's drain QTimer, GUI thread). The dock pane owns the controller instance and the timer.

- [ ] **Step 1: Implement roi_controller.py**

```python
# fluorescence_controls_ui/image_viewer/analysis/roi_controller.py
"""Controller for the ROI analysis: reacts to the analysis toolbuttons
and canvas events, keeps the per-experiment ROI config in sync,
orchestrates the cache-aware batch computation, and rebuilds the plot
series as results drain in. All observers run on the GUI thread; the
only off-thread work is inside RoiBatchRunner."""

import math
import queue
import time
from pathlib import Path

from traits.api import Any, Bool, Dict, HasTraits, Instance, observe
from pyface.api import NO, YES

from logger.logger_service import get_logger
from microdrop_application.dialogs.pyface_wrapper import confirm

from device_viewer.consts import CAPTURES_DIR_NAME
from fluorescence_protocol_controls.capture_chain import sanitize_label

from ...capture_service import utc_stamp
from ...consts import CAPTURE_TIMESTAMP_FORMAT
from ..discovery import UNGROUPED_BURST, capture_timestamp, detect_wavelength
from ..model import FluorescenceImageViewerModel
from .roi_batch import (
    BATCH_FINISHED,
    BATCH_RESULT,
    INSTANT_RESULT,
    RoiBatchRunner,
)
from .roi_model import Roi, RoiAnalysisModel
from .roi_store import (
    analysis_directory,
    load_roi_config,
    save_roi_config,
    write_intensity_csv,
)

logger = get_logger(__name__)


class RoiAnalysisController(HasTraits):
    """Glue between the viewer model (whose ``paths`` IS the filtered
    series), the analysis model, and the batch runner."""

    viewer_model = Instance(FluorescenceImageViewerModel)
    analysis_model = Instance(RoiAnalysisModel)
    runner = Instance(RoiBatchRunner, ())

    #: Export requested while the cache was incomplete: write the CSV
    #: when the running batch finishes.
    _pending_export = Bool(False)

    #: (path str, roi_id) -> cache key, snapshotted at dispatch time so
    #: drained results land under the geometry they were computed with.
    _dispatched_keys = Dict()

    #: The Roi whose instant result should feed roi_info_text.
    _instant_roi = Any(None)

    # ------------------------------------------------------------------ #
    # Interaction modes                                                    #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:draw_circle_button")
    def _arm_draw_circle(self, event):
        self.analysis_model.interaction_mode = "draw_circle"

    @observe("analysis_model:draw_box_button")
    def _arm_draw_box(self, event):
        self.analysis_model.interaction_mode = "draw_box"

    @observe("analysis_model:edit_mode")
    def _toggle_edit_mode(self, event):
        self.analysis_model.interaction_mode = "edit" if event.new else "pan"

    def _rest_mode(self):
        return "edit" if self.analysis_model.edit_mode else "pan"

    # ------------------------------------------------------------------ #
    # Canvas events                                                        #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:canvas_roi_created")
    def _on_canvas_roi_created(self, event):
        kind, geometry = event.new
        current = self.viewer_model.current_path
        anchor = capture_timestamp(current) if current else 0.0
        roi = Roi(
            name=self.analysis_model.next_roi_name(),
            kind=kind,
            geometry=[float(value) for value in geometry],
            base_anchor=anchor,
        )
        self.analysis_model.rois.append(roi)
        self.analysis_model.interaction_mode = self._rest_mode()
        self._save_config()
        self._instant_stats(roi)
        self._restart_batch_if_running()

    @observe("analysis_model:canvas_roi_edited")
    def _on_canvas_roi_edited(self, event):
        roi_id, geometry = event.new
        roi = self.analysis_model.roi_by_id(roi_id)
        current = self.viewer_model.current_path
        if roi is None or not current:
            return
        roi.apply_edit(capture_timestamp(current), [float(value) for value in geometry])
        self._save_config()
        self._instant_stats(roi)
        self._restart_batch_if_running()

    # ------------------------------------------------------------------ #
    # Delete / clear / reset                                               #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:delete_roi_button")
    def _delete_selected_roi(self, event):
        roi = self.analysis_model.roi_by_id(self.analysis_model.selected_roi_id)
        if roi is None:
            self.analysis_model.roi_info_text = (
                "Select an ROI first (edit mode) to delete it"
            )
            return
        self.analysis_model.rois.remove(roi)
        self.analysis_model.selected_roi_id = ""
        self._save_config()
        self._rebuild_plot_series()
        self._restart_batch_if_running()

    @observe("analysis_model:clear_rois_button")
    def _clear_rois(self, event):
        if not self.analysis_model.rois:
            return
        if confirm(message="Remove ALL ROIs (and their drift overrides)?") != YES:
            return
        self.runner.cancel()
        self.analysis_model.rois = []
        self.analysis_model.selected_roi_id = ""
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self._save_config()
        self._rebuild_plot_series()

    @observe("analysis_model:reset_cache_button")
    def _reset_cache(self, event):
        result = confirm(
            message="Reset the calculated ROI intensities?",
            cancel=True,
            yes_label="Cache only",
            no_label="Cache + drift overrides",
        )
        if result not in (YES, NO):
            return
        self.runner.cancel()
        self.analysis_model.cache = {}
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        if result == NO:
            for roi in self.analysis_model.rois:
                roi.clear_overrides()
            self._save_config()
        self._rebuild_plot_series()

    # ------------------------------------------------------------------ #
    # Batch orchestration                                                  #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:calculate_button")
    def _calculate(self, event):
        self._start_batch()

    @observe("analysis_model:export_csv_button")
    def _export(self, event):
        if not self.analysis_model.rois or not self.viewer_model.paths:
            self.analysis_model.progress_text = "Nothing to export"
            return
        if self._missing_work():
            self._pending_export = True
            self.analysis_model.progress_text = "Calculating for export…"
            self._start_batch()
            return
        self._write_export()

    @observe(
        "viewer_model:paths.items, viewer_model:selected_wavelength,"
        " viewer_model:selected_burst"
    )
    def _on_filter_changed(self, event):
        """The filtered series changed mid-batch: restart on the new
        snapshot (the work list is a snapshot by design)."""
        self._restart_batch_if_running()

    def _missing_work(self):
        """[(path_str, {roi_id: (kind, geometry)}), ...] for every
        filtered image with at least one uncached (image, ROI) pair —
        only the missing ROIs are dispatched per image."""
        work = []
        for path in self.viewer_model.paths:
            missing = {}
            for roi in self.analysis_model.rois:
                key = self.analysis_model.cache_key(path, roi)
                if key not in self.analysis_model.cache:
                    missing[roi.roi_id] = (roi.kind, tuple(key[4]))
                    self._dispatched_keys[(str(path), roi.roi_id)] = key
            if missing:
                work.append((str(path), missing))
        return work

    def _start_batch(self):
        if not self.analysis_model.rois or not self.viewer_model.paths:
            return
        self._dispatched_keys = {}
        work = self._missing_work()
        self.analysis_model.batch_done = 0
        self.analysis_model.batch_failed = 0
        self.analysis_model.batch_total = len(work)
        if not work:
            self.analysis_model.batch_running = False
            self._rebuild_plot_series()
            if self._pending_export:
                self._write_export()
            return
        self.analysis_model.batch_running = True
        self._update_progress_text()
        self.runner.start(work)

    def _restart_batch_if_running(self):
        if self.analysis_model.batch_running:
            self._start_batch()

    def drain_results(self):
        """Called by the dock pane's drain QTimer (GUI thread): move
        finished results from the runner's queue into the model."""
        drained = False
        while True:
            try:
                kind, payload = self.runner.results.get_nowait()
            except queue.Empty:
                break
            drained = True
            if kind == BATCH_RESULT:
                self._absorb(payload)
                self.analysis_model.batch_done += 1
                if payload["error"]:
                    self.analysis_model.batch_failed += 1
                    logger.warning(
                        f"ROI stats failed for {payload['path']}: {payload['error']}"
                    )
                self._update_progress_text()
            elif kind == INSTANT_RESULT:
                self._absorb(payload)
                self._show_instant(payload)
            elif kind == BATCH_FINISHED:
                self.analysis_model.batch_running = False
                self._update_progress_text(finished=True)
                if self._pending_export:
                    self._write_export()
        if drained:
            self._rebuild_plot_series()

    def _absorb(self, payload):
        for roi_id, stats in payload["stats"].items():
            key = self._dispatched_keys.get((payload["path"], roi_id))
            if key is not None:
                self.analysis_model.cache[key] = stats

    def _update_progress_text(self, finished=False):
        model = self.analysis_model
        failed = f", {model.batch_failed} failed" if model.batch_failed else ""
        state = "done" if finished else "calculating"
        model.progress_text = (
            f"ROI stats {model.batch_done}/{model.batch_total} {state}{failed}"
        )

    def _instant_stats(self, roi):
        """Kick off the instant single-image compute for ``roi`` on the
        shown image."""
        current = self.viewer_model.current_path
        if not current:
            return
        key = self.analysis_model.cache_key(current, roi)
        self._dispatched_keys[(current, roi.roi_id)] = key
        self._instant_roi = roi
        cached = self.analysis_model.cache.get(key)
        if cached is not None:
            self._show_instant(
                {"path": current, "stats": {roi.roi_id: cached}, "error": None}
            )
            return
        self.runner.compute_single(current, {roi.roi_id: (roi.kind, tuple(key[4]))})

    def _show_instant(self, payload):
        roi = self._instant_roi
        if roi is None:
            return
        stats = payload["stats"].get(roi.roi_id)
        if stats is None or payload.get("error"):
            self.analysis_model.roi_info_text = (
                f"{roi.name}: no stats ({payload.get('error') or 'empty'})"
            )
            return
        self.analysis_model.roi_info_text = (
            f"{roi.name}: mean {stats['mean']:.1f}  "
            f"std {stats['std']:.1f}  min {stats['min']:.0f}  "
            f"max {stats['max']:.0f}  n {int(stats['count'])}"
        )

    # ------------------------------------------------------------------ #
    # Plot series                                                          #
    # ------------------------------------------------------------------ #
    def _rebuild_plot_series(self):
        model = self.analysis_model
        paths = list(self.viewer_model.paths)
        if not paths or not model.rois:
            model.plot_series = {}
            model.plot_revision += 1
            return
        times = [capture_timestamp(path) for path in paths]
        start_time = times[0]
        series = {}
        for roi in model.rois:
            elapsed, means = [], []
            for path, capture_time in zip(paths, times):
                stats = model.cache.get(model.cache_key(path, roi))
                elapsed.append(capture_time - start_time)
                means.append(stats["mean"] if stats else math.nan)
            series[roi.roi_id] = (roi.name, elapsed, means)
        model.plot_series = series
        model.plot_revision += 1

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #
    def _experiment_directory(self):
        """The folder analysis outputs belong to: the experiment folder
        when browsing its captures dir, else the browsed folder itself.
        None when nothing is resolved yet."""
        browsed = self.viewer_model.browsed_directory
        if not browsed:
            return None
        folder = Path(browsed)
        return folder.parent if folder.name == CAPTURES_DIR_NAME else folder

    def _save_config(self):
        directory = self._experiment_directory()
        if directory is None:
            return
        try:
            save_roi_config(directory, self.analysis_model.rois)
        except Exception as error:
            logger.warning(f"Could not save ROI config: {error}")

    @observe("viewer_model:browsed_directory")
    def _on_experiment_changed(self, event):
        """A different folder is being browsed: its saved ROIs replace
        the current set; cache and series start over."""
        self.runner.cancel()
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self.analysis_model.roi_info_text = ""
        self.analysis_model.selected_roi_id = ""
        self.analysis_model.cache = {}
        directory = self._experiment_directory()
        self.analysis_model.rois = (
            load_roi_config(directory) if directory is not None else []
        )
        self._rebuild_plot_series()

    def _write_export(self):
        self._pending_export = False
        directory = self._experiment_directory()
        if directory is None:
            self.analysis_model.progress_text = "No experiment folder"
            return
        model = self.analysis_model
        paths = list(self.viewer_model.paths)
        times = [capture_timestamp(path) for path in paths]
        start_time = times[0] if times else 0.0
        rows = []
        for path, capture_time in zip(paths, times):
            stats_by_roi = {}
            for roi in model.rois:
                stats = model.cache.get(model.cache_key(path, roi))
                if stats is not None:
                    stats_by_roi[roi.roi_id] = stats
            rows.append(
                {
                    "filename": Path(path).name,
                    "time_utc": time.strftime(
                        CAPTURE_TIMESTAMP_FORMAT, time.gmtime(capture_time)
                    ),
                    "elapsed_sec": capture_time - start_time,
                    "group": self._group_of(path),
                    "wavelength": detect_wavelength(path),
                    "stats": stats_by_roi,
                }
            )
        name = (
            f"roi_intensities_"
            f"{sanitize_label(self.viewer_model.selected_burst)}_"
            f"{sanitize_label(self.viewer_model.selected_wavelength)}_"
            f"{utc_stamp()}.csv"
        )
        csv_path = analysis_directory(directory) / name
        try:
            write_intensity_csv(csv_path, rows, model.rois)
        except Exception as error:
            logger.warning(f"CSV export failed: {error}")
            model.progress_text = f"Export failed: {error}"
            return
        model.progress_text = f"Exported {csv_path.name}"
        logger.info(f"ROI intensities exported to {csv_path}")

    def _group_of(self, path):
        """The image-group (burst folder) name a capture belongs to."""
        burst_dir = Path(path).parent.parent
        browsed = self.viewer_model.browsed_directory
        if browsed and burst_dir == Path(browsed):
            return UNGROUPED_BURST
        return burst_dir.name
```

- [ ] **Step 2: Wire into the dock pane**

In `dock_pane.py`: add imports

```python
from .analysis.consts import ANALYSIS_RESULT_DRAIN_INTERVAL_MS
from .analysis.roi_controller import RoiAnalysisController
```

add traits to `FluorescenceImageViewerDockPane`:

```python
    analysis_controller = Instance(RoiAnalysisController)
    _drain_timer = Any()
```

in `traits_init`, after the controller is built:

```python
self.analysis_controller = RoiAnalysisController(
    viewer_model=self.model, analysis_model=self.model.roi_analysis
)
```

in `create_contents`, next to the other timers:

```python
self._drain_timer = QTimer(control)
self._drain_timer.setInterval(ANALYSIS_RESULT_DRAIN_INTERVAL_MS)
self._drain_timer.timeout.connect(self.analysis_controller.drain_results)
self._drain_timer.start()
```

- [ ] **Step 3: Import smoke check**

Run: `pixi run python -c "import fluorescence_controls_ui.image_viewer.dock_pane; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/image_viewer/dock_pane.py
git commit -m "feat(image-viewer): orchestrate ROI batch analysis" -m "RoiAnalysisController: instant stats on draw/edit, cache-aware batch over the filtered series with mid-batch restart on filter/ROI changes, per-experiment config auto-load/save, CSV export (auto-calculating first when the cache is incomplete), and the two-flavor reset dialog. Dock pane drains results into the model on a 200ms GUI timer."
```

---

### Task 9: Analysis toolbuttons in the viewer

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/model.py` (one collapse trait)
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (analysis group)

**Interfaces:**
- Consumes: button/readout traits (Task 3), icons (Task 7).
- Produces: the visible toolbutton row; `show_analysis: Bool(True)` on the viewer model.

- [ ] **Step 1: Add the collapse trait**

In `model.py`, with the other `show_*` traits: `show_analysis = Bool(True)`.

- [ ] **Step 2: Add the view group**

In `view.py`, extend the `microdrop_style.icons.icons` import with `ICON_CIRCLE, ICON_DELETE, ICON_DELETE_SWEEP, ICON_EDIT, ICON_RECTANGLE, ICON_RESET_WRENCH, ICON_SAVE, ICON_SHOW_CHART`. After `contrast_group`, add:

```python
# ROI analysis: draw/edit tools, then the calculate -> plot -> export
# pipeline over the filtered images. The readouts show the freshly drawn
# ROI's instant stats and the batch progress.
analysis_group = VGroup(
    HGroup(
        UItem(
            "object.roi_analysis.draw_circle_button",
            editor=IconButtonEditor(
                glyph=ICON_CIRCLE,
                tooltip="Draw a circular ROI (click-drag on the image)",
            ),
        ),
        UItem(
            "object.roi_analysis.draw_box_button",
            editor=IconButtonEditor(
                glyph=ICON_RECTANGLE,
                tooltip="Draw a rectangular ROI (click-drag on the image)",
            ),
        ),
        UItem(
            "object.roi_analysis.edit_mode",
            editor=IconToggleEditor(
                on_glyph=ICON_EDIT,
                off_glyph=ICON_EDIT,
                tooltip="Edit ROIs: drag to move, grip to resize, "
                "click to select. Editing on a later image "
                "adds a drift override from there on",
            ),
        ),
        UItem(
            "object.roi_analysis.delete_roi_button",
            editor=IconButtonEditor(
                glyph=ICON_DELETE, tooltip="Delete the selected ROI"
            ),
        ),
        UItem(
            "object.roi_analysis.clear_rois_button",
            editor=IconButtonEditor(glyph=ICON_DELETE_SWEEP, tooltip="Remove all ROIs"),
        ),
        UItem(
            "object.roi_analysis.calculate_button",
            editor=IconButtonEditor(
                glyph=ICON_SHOW_CHART,
                tooltip="Calculate ROI intensities across the "
                "filtered images and plot them",
            ),
        ),
        UItem(
            "object.roi_analysis.export_csv_button",
            editor=IconButtonEditor(
                glyph=ICON_SAVE,
                tooltip="Export the intensities to the experiment's "
                "analysis folder (calculates first if "
                "needed)",
            ),
        ),
        UItem(
            "object.roi_analysis.reset_cache_button",
            editor=IconButtonEditor(
                glyph=ICON_RESET_WRENCH,
                tooltip="Reset calculated intensities (optionally "
                "also the drift overrides)",
            ),
        ),
    ),
    UItem("object.roi_analysis.roi_info_text", style="readonly"),
    UItem("object.roi_analysis.progress_text", style="readonly"),
    visible_when="show_analysis",
    show_border=True,
)
```

and in `ImageViewerView`, between the contrast section and the canvas:

```python
(_collapse_header("show_analysis", "Analysis"),)
(analysis_group,)
```

- [ ] **Step 3: Import smoke check**

Run: `pixi run python -c "import fluorescence_controls_ui.image_viewer.view; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/model.py fluorescence_controls_ui/image_viewer/view.py
git commit -m "feat(image-viewer): add ROI analysis toolbutton row" -m "Collapsible Analysis section: draw circle/box, edit/delete/clear, calculate+plot, export CSV, reset - plus the instant-stats and batch-progress readouts."
```

---

### Task 10: Plot dock pane

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`
- Modify: `fluorescence_controls_ui/plugin.py` (register the pane)

**Interfaces:**
- Consumes: `roi_analysis_model` singleton, `plot_series`/`plot_revision`/`progress_text` (Task 3), `ROI_PLOT_REFRESH_INTERVAL_MS`; the temperature-canvas embedding pattern (`advanced_camera/temperature_canvas.py`); `PKG` from `..consts` — note `plot_pane.py` sits in `image_viewer/analysis/`, so the import is `from ...consts import PKG`.
- Produces: `FluorescenceRoiPlotDockPane` (id `PKG + ".image_viewer.roi_plot_dock_pane"`).

- [ ] **Step 1: Implement**

```python
# fluorescence_controls_ui/image_viewer/analysis/plot_pane.py
"""Dock pane plotting the ROI intensity series: mean intensity vs
elapsed time, one line per ROI, streaming in as the batch computes
(poll-timer canvas over the shared analysis model — the temperature
canvas pattern). Lines gap where an image failed or isn't computed."""

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
from .consts import ROI_PLOT_REFRESH_INTERVAL_MS
from .roi_model import roi_analysis_model


class RoiPlotCanvas(FigureCanvasQTAgg):
    """Intensity-vs-time chart fed from the analysis model's
    ``plot_series``; redraws only when ``plot_revision`` moves."""

    def __init__(self, model):
        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Elapsed time (s)")
        self._axes.set_ylabel("Mean intensity")
        self._axes.grid(True, alpha=0.3)
        self._lines = {}
        self._plotted_revision = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)

    def showEvent(self, event):
        self._timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _refresh(self):
        if self._model.plot_revision == self._plotted_revision:
            return
        self._plotted_revision = self._model.plot_revision
        series = dict(self._model.plot_series)
        for roi_id in list(self._lines):
            if roi_id not in series:
                self._lines.pop(roi_id).remove()
        for roi_id, (name, elapsed, means) in series.items():
            if roi_id not in self._lines:
                (self._lines[roi_id],) = self._axes.plot([], [], marker=".", label=name)
            line = self._lines[roi_id]
            line.set_data(elapsed, means)
            line.set_label(name)
        if self._lines:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


class FluorescenceRoiPlotDockPane(DockPane):
    """ROI mean intensity vs time for the filtered image series."""

    id = PKG + ".image_viewer.roi_plot_dock_pane"
    name = "Fluorescence ROI Intensities"

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        canvas = RoiPlotCanvas(roi_analysis_model)
        layout.addWidget(NavigationToolbar2QT(canvas, widget))
        layout.addWidget(canvas)
        progress = QLabel("", widget)
        layout.addWidget(progress)
        timer = QTimer(widget)
        timer.timeout.connect(
            lambda: progress.setText(roi_analysis_model.progress_text)
        )
        timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)
        return widget
```

- [ ] **Step 2: Register in the plugin**

In `plugin.py`, `_get_extra_dock_pane_classes` becomes:

```python
def _get_extra_dock_pane_classes(self) -> list:
    # Extra dock panes: 16-bit-aware viewer for captured images, ROI
    # intensity plot, and advanced ASI capture settings.
    from .advanced_camera.dock_pane import AdvancedCameraDockPane
    from .image_viewer.analysis.plot_pane import (
        FluorescenceRoiPlotDockPane,
    )
    from .image_viewer.dock_pane import FluorescenceImageViewerDockPane

    return [
        FluorescenceImageViewerDockPane,
        FluorescenceRoiPlotDockPane,
        AdvancedCameraDockPane,
    ]
```

- [ ] **Step 3: Import smoke check**

Run: `pixi run python -c "import fluorescence_controls_ui.image_viewer.analysis.plot_pane; import fluorescence_controls_ui.plugin; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/plot_pane.py fluorescence_controls_ui/plugin.py
git commit -m "feat(image-viewer): add ROI intensity plot dock pane" -m "Matplotlib canvas polling the shared analysis model: one line per ROI vs elapsed capture time, live-updating as batch results drain, with nav toolbar (zoom/pan/save-PNG) and progress readout."
```

---

### Task 11: Final review pass + manual test checklist

- [ ] **Step 1: Re-run all the new test files** (the five files from Tasks 1-6 only, one command):

`pixi run python -m pytest src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_capture_timestamp.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_burst_filter_all.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_model.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_compute.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_batch.py src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_roi_store.py -v`

Expected: all PASS.

- [ ] **Step 2: Report the manual GUI checklist to the user** (they test the GUI themselves; do NOT launch the app):

1. Image Groups dropdown shows "All" first; selecting it lets the image seek slider scrub every group; wavelength filter still applies on top.
2. Draw circle/box buttons: click-drag creates an ROI, its stats appear instantly in the info readout.
3. Edit mode: drag moves an ROI, the grip resizes; doing this on a LATER image and stepping back shows the old geometry (override), stepping forward shows the new.
4. Calculate: progress counts up, plot pane lines grow live; recalculating after one small edit is near-instant (cache).
5. Export: CSV lands in `<experiment>/analysis/` with sensible name/columns; export with a cold cache calculates first, then writes.
6. Reset dialog offers "Cache only" vs "Cache + drift overrides"; Clear removes all ROIs after confirm.
7. ROIs persist across an app restart (roi_config.json) and switch with the browsed experiment.

- [ ] **Step 3: Push and open a PR** (after the user has approved): `git push -u origin feat/roi-intensity-analysis` and open a PR to `main` in the fluorescence plugin repo. The icons commit in the Microdrop submodule repo goes on its own branch/PR there if the user wants it separated — ask before pushing that repo.
