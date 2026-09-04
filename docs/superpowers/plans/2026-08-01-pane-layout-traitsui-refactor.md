# Pane Layout Rework + TraitsUI-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ROI plot pane shrinkable (scrollbars past the minimum),
replace its hand-built Qt controls with TraitsUI, and reorganize the
Fluorescence Images pane into sidebar / image / vertical-analysis-toolbar
(layout Option A of the approved spec).

**Architecture:** Plot pane keeps its Qt structural shell (scroll area,
splitter, matplotlib canvas, stats table) but all value editors become a
TraitsUI subpanel rebuilt per session swap. The Images pane is
restructured purely inside its existing TraitsUI View using
HGroup/HSplit. Spec:
`docs/superpowers/specs/2026-08-01-pane-layout-traitsui-refactor-design.md`.

**Tech Stack:** TraitsUI (View/HSplit/EnumEditor/IconToggleEditor),
PySide6 (QScrollArea/QSplitter), matplotlib QtAgg.

## Global Constraints

- Branch: `feat/roi-intensity-analysis` (plugin repo); submodule branch
  `feat/roi-analysis-icons` for the icon constants.
- Conventional commits; never `--no-verify`; f-strings; constants in
  `consts.py`; no cross-plugin reach-ins.
- Verified facts (offscreen, this env): `Group(scrollable=True)` is valid;
  `EnumEditor(values=<ordered list>, format_func=<labels>.get)` preserves
  order, shows labels, binds both ways; the `"value:label"` list form does
  NOT work — never use it; a plain dict `values=` sorts alphabetically —
  never use it either.
- TraitsUI `enabled_when` re-evaluates only on trait changes of DIRECT
  context objects — so `figure` must be its own context key (nested
  `session.figure.x_auto` would not re-evaluate). Verify in the Task 2
  smoke.
- Suite baseline: 185 passed + 2 known pre-existing failures
  (`test_chain_model` param-set ordering interference,
  `test_image_viewer` navigation `relative_path`).
- Test command: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && QT_QPA_PLATFORM=offscreen python -m pytest tests -q"`.

---

### Task 1: Chevron icon constants (Microdrop submodule)

**Files:**
- Modify: `src/microdrop_style/icons/icons.py` (append after
  `ICON_DELETE_SWEEP`)

**Interfaces:**
- Produces: `ICON_CHEVRON_LEFT = "chevron_left"`,
  `ICON_CHEVRON_RIGHT = "chevron_right"` (Material Symbols ligatures, the
  same form as `ICON_FIT_SCREEN` etc.). Task 3 imports both.

- [ ] **Step 1: Append the constants**

```python
ICON_CHEVRON_LEFT = "chevron_left"  # collapse a sidebar leftward
ICON_CHEVRON_RIGHT = "chevron_right"  # reveal a collapsed sidebar
```

- [ ] **Step 2: Commit in the submodule (already on `feat/roi-analysis-icons`)**

```bash
cd microdrop-py/src
git add microdrop_style/icons/icons.py
git commit -m "feat(style): add chevron sidebar-toggle icon constants"
```

---

### Task 2: Plot pane — TraitsUI controls + scrollable shell

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py`
  (RoiAnalysisModel buttons block)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`

**Interfaces:**
- Consumes: `PLOT_STATS`, `roi_analysis_model` (roi_model),
  `IconButtonEditor` (microdrop_utils.traitsui_qt_helpers), `ICON_SAVE`.
- Produces: `save_plot_button = Button()` on `RoiAnalysisModel`;
  `ROI_PLOT_CANVAS_MIN_WIDTH = 300`, `ROI_PLOT_CANVAS_MIN_HEIGHT = 200`
  in analysis consts. Pane behavior contract unchanged for
  roi_controller (it persists `plot_stat`/figure traits it already
  observes — no controller change needed; writes now come from TraitsUI
  editors instead of Qt lambdas).

- [ ] **Step 1: Add the button trait to `RoiAnalysisModel`** (next to
  `export_csv_button`):

```python
#: Render the current plot to an image file at the session's export
#: settings (handled by the plot dock pane, which owns the canvas).
save_plot_button = Button()
```

- [ ] **Step 2: Add the canvas minimum to `analysis/consts.py`**:

```python
#: Below this the plot canvas stops shrinking and the plot pane's
#: scroll area takes over with scrollbars instead.
ROI_PLOT_CANVAS_MIN_WIDTH = 300
ROI_PLOT_CANVAS_MIN_HEIGHT = 200
```

- [ ] **Step 3: Rewrite the controls in `plot_pane.py`.**
  Replace the imports of `QCheckBox/QComboBox/QDoubleSpinBox/QHBoxLayout/
  QPushButton` with `QScrollArea` (keep `QLabel/QVBoxLayout/QSplitter/
  QWidget`), drop `traits.api.List`, add:

```python
from traitsui.api import EnumEditor, HGroup, Item, UItem, VGroup, View

from microdrop_style.icons.icons import ICON_SAVE
from microdrop_utils.traitsui_qt_helpers import IconButtonEditor
from .consts import (
    ROI_PLOT_CANVAS_MIN_HEIGHT,
    ROI_PLOT_CANVAS_MIN_WIDTH,
    ROI_PLOT_COALESCE_MS,
)
```

  Module-level view (after `LINE_STYLES`). Two rows so the pane's
  un-scrolled minimum width stays small; `figure` is its own context key
  so `enabled_when` re-evaluates (see Global Constraints):

```python
#: Controls over the per-session plot/export traits. Rebuilt against the
#: new session on every swap (TraitsUI resolves context objects at build
#: time), which replaces all hand-written widget<->trait syncing.
_plot_controls_view = View(
    VGroup(
        HGroup(
            Item(
                "session.plot_stat",
                label="Plot",
                editor=EnumEditor(
                    values=list(PLOT_STATS), format_func=PLOT_STAT_LABELS.get
                ),
            ),
            Item("figure.x_auto", label="X auto"),
            Item("figure.x_min", label="min", enabled_when="not figure.x_auto"),
            Item("figure.x_max", label="max", enabled_when="not figure.x_auto"),
        ),
        HGroup(
            Item("figure.y_auto", label="Y auto"),
            Item("figure.y_min", label="min", enabled_when="not figure.y_auto"),
            Item("figure.y_max", label="max", enabled_when="not figure.y_auto"),
            Item("figure.export_dpi", label="DPI"),
            Item("figure.export_format", label="Format"),
            UItem(
                "model.save_plot_button",
                editor=IconButtonEditor(
                    glyph=ICON_SAVE,
                    tooltip="Save the plot to the experiment's analysis "
                    "folder at the chosen format and DPI",
                ),
            ),
        ),
    ),
)
```

- [ ] **Step 4: Rework the pane class.** Trait declarations shrink to:

```python
canvas = Instance(RoiPlotCanvas)
table = Instance(RoiStatsTable)
_controls_ui = Any()
_progress_label = Any()
```

  `create_contents` becomes (note the scroll-area return):

```python
def create_contents(self, parent):
    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    self.canvas = RoiPlotCanvas(roi_analysis_model)
    self.canvas.setMinimumSize(ROI_PLOT_CANVAS_MIN_WIDTH, ROI_PLOT_CANVAS_MIN_HEIGHT)
    layout.addWidget(NavigationToolbar2QT(self.canvas, widget))
    self._controls_ui = self._build_controls(widget)
    layout.addWidget(self._controls_ui.control)
    splitter = QSplitter(Qt.Orientation.Vertical, widget)
    splitter.addWidget(self.canvas)
    self.table = RoiStatsTable(roi_analysis_model, splitter)
    splitter.addWidget(self.table)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    layout.addWidget(splitter, 1)
    self._progress_label = QLabel("", widget)
    layout.addWidget(self._progress_label)
    roi_analysis_model.observe(self._on_session_swapped, "session")
    roi_analysis_model.observe(self._on_save_plot, "save_plot_button")
    roi_analysis_model.observe(self._on_progress_text_changed, "progress_text")
    # The pane may be resized below the content's minimum; past that
    # point scrollbars take over instead of the dock pane locking.
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll


def _build_controls(self, parent):
    session = roi_analysis_model.session
    return _plot_controls_view.ui(
        context={
            "session": session,
            "figure": session.figure,
            "model": roi_analysis_model,
        },
        kind="subpanel",
        parent=parent,
    )


def _on_session_swapped(self, event):
    old_ui = self._controls_ui
    holder = old_ui.control.parentWidget()
    self._controls_ui = self._build_controls(holder)
    holder.layout().replaceWidget(old_ui.control, self._controls_ui.control)
    old_ui.dispose()


def _on_save_plot(self, event):
    _save_figure(self.canvas)
```

  Delete: `_stat_combo`, `_dpi_combo`, `_format_combo`, `_axis_syncers`,
  `_sync_controls`, `_on_plot_stat_changed`, and every Qt
  combo/checkbox/spinbox construction line. Keep
  `_on_progress_text_changed` and `_save_figure` unchanged. `destroy()`
  becomes:

```python
def destroy(self):
    # Everything below was registered in create_contents, which a
    # constructed-but-never-shown pane never ran (pyface's own
    # destroy() guards its teardown the same way).
    if self.control is not None:
        self.canvas.detach()
        self.table.detach()
        self._controls_ui.dispose()
        roi_analysis_model.observe(self._on_session_swapped, "session", remove=True)
        roi_analysis_model.observe(self._on_save_plot, "save_plot_button", remove=True)
        roi_analysis_model.observe(
            self._on_progress_text_changed, "progress_text", remove=True
        )
    super().destroy()
```

- [ ] **Step 5: Offscreen smoke.** Run (scratchpad script, not committed):
  build `_plot_controls_view.ui` against session A with a figure whose
  `x_auto=True`; assert the `x_min` editor widget is disabled; set
  `session.figure.x_auto = False`; assert it enabled (proves the
  `enabled_when` context choice). Swap to session B, call the pane's
  rebuild path (or rebuild the ui with B's context) and assert editing the
  combo writes B's `plot_stat`, not A's. Expected: all asserts pass.

- [ ] **Step 6: Suite still at baseline**

Run: the Global Constraints test command.
Expected: 185 passed, 2 known failures.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/
git commit -m "refactor(analysis): TraitsUI plot controls, scrollable pane"
```

---

### Task 3: Fluorescence Images pane — sidebar layout (Option A)

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/model.py` (show_* block)
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (groups +
  `ImageViewerView`)

**Interfaces:**
- Consumes: `ICON_CHEVRON_LEFT`, `ICON_CHEVRON_RIGHT` (Task 1),
  `IconToggleEditor`, `HSplit` (add to the traitsui.api import).
- Produces: `show_sidebar = Bool(True)` on
  `FluorescenceImageViewerModel`; `show_analysis` is deleted (the
  toolbar is always visible now — grep confirms view.py is its only
  consumer before deleting).

- [ ] **Step 1: Model traits.** In the show_* block: add
  `show_sidebar = Bool(True)` with a comment
  (`#: Master toggle: the whole selector sidebar collapses to the left
  edge (device-viewer chevron parity).`) and delete `show_analysis`.

- [ ] **Step 2: Restructure `view.py`.** Add `HSplit` to the traitsui
  import and the chevron icons to the microdrop_style import; drop
  `visible_when="show_analysis"` handling. The groups become:

```python
# Selector sidebar: the four collapsible sections stacked, hidden as one
# unit by the chevron toggle (device-viewer sidebar parity).
sidebar_group = VGroup(
    _collapse_header("show_experiments", "Experiments"),
    experiments_group,
    _collapse_header("show_bursts", "Image Groups"),
    bursts_group,
    _collapse_header("show_images", "Images"),
    images_group,
    _collapse_header("show_contrast", "Contrast"),
    contrast_group,
    visible_when="show_sidebar",
    scrollable=True,
)

# Analysis tools as an always-visible vertical toolbar on the image's
# right edge (was a collapsible horizontal row above the image).
analysis_toolbar = VGroup(
    ...the eight existing UItem(...) analysis buttons verbatim,
    minus the wrapping HGroup/progress text/visible_when...
)

ImageViewerView = View(
    HGroup(
        VGroup(UItem("show_sidebar", editor=IconToggleEditor(
            on_glyph=ICON_CHEVRON_LEFT, off_glyph=ICON_CHEVRON_RIGHT,
            tooltip="Hide or show the selector sidebar"))),
        HSplit(
            sidebar_group,
            VGroup(
                buttons_group,
                UItem("array", editor=ImageCanvasEditor(), springy=True,
                      resizable=True),
                HGroup(
                    UItem("pixel_text", style="readonly"),
                    UItem("object.roi_analysis.progress_text",
                          style="readonly"),
                ),
            ),
        ),
        analysis_toolbar,
    ),
    resizable=True,
)
```

  `experiments_group`/`bursts_group`/`images_group`/`contrast_group`/
  `buttons_group`/`_collapse_header` keep their definitions;
  `analysis_group` (the old bordered group with `visible_when=
  "show_analysis"` and the inline progress text) is deleted.

- [ ] **Step 3: Offscreen smoke.** Instantiate
  `FluorescenceImageViewerModel`, `edit_traits` the view `kind="subpanel"`
  (with the controller as handler not required for layout), toggle
  `show_sidebar` False/True, dispose. Expected: builds and toggles
  without traceback.

- [ ] **Step 4: Suite still at baseline**

Run: the Global Constraints test command.
Expected: 185 passed, 2 known failures.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/model.py \
        fluorescence_controls_ui/image_viewer/view.py
git commit -m "feat(viewer): sidebar layout with vertical analysis toolbar"
```

---

### Task 4: Final verification + review

- [ ] **Step 1:** Full plugin suite at baseline; capture_service
  lazy-import guard still holds (run `tests/test_led_controls.py`
  explicitly).
- [ ] **Step 2:** Offscreen import smoke of both panes
  (`plot_pane`, `view`, `dock_pane` modules).
- [ ] **Step 3:** Code review pass of the diff since `40de9da` against
  the spec + microdrop-conventions; fix findings; commit.
- [ ] **Step 4:** Report with the manual GUI checklist:
  1. Plot pane: shrink narrow → scrollbars appear both directions.
  2. Plot pane: stat/axis/DPI/format edits behave as before; switch
     experiments → controls show the new experiment's settings.
  3. Save plot… works via the new toolbar-row button.
  4. Images pane: chevron collapses/reveals the sidebar; splitter drags.
  5. Analysis toolbar vertical on the right; all 8 actions work.
  6. pixel readout + batch progress share the bottom status row.
