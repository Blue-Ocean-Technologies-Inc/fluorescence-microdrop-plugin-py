# Automatic ROI Identification (SAM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SAM-segmented droplet ROIs in the image viewer: click-to-pick, grid detect-all with a reviewable candidate preview, and drift tracking across the series — per `docs/superpowers/specs/2026-08-07-automatic-roi-identification-design.md`.

**Architecture:** One new Qt-free module (`analysis/sam_detect.py`) ports the osam session/refiner/dedup from the prototype at `C:\Users\Info\PycharmProjects\labelme\droplet_roi\` ("PROTO" below); a Qt-free job runner (`analysis/sam_jobs.py`) follows the `roi_batch.py` queue idiom; a focused `AiRoiController` glues them to the existing models; accepted candidates funnel through a new bulk `_create_rois` on `RoiAnalysisController`, and tracking writes `Roi.apply_edit` overrides. Model weights and the osam package itself are optional, installed/downloaded only on demand.

**Tech Stack:** traits/TraitsUI, PySide6 (views only), numpy/cv2, `osam` (optional, ONNX runtime), existing `IconButtonEditor`/`IconModeButtonEditor`/`IconToggleEditor` helpers.

## Global Constraints

- Branch: `feat/automatic-roi-identification` in `fluorescence-microdrop-plugin-py`; conventional commits; commit after each task.
- HasTraits everywhere a stateful class appears; precise trait types; `Union`/`Either` over `Any` (user directive).
- Qt imports only in view/dialog modules — never in `analysis/` (except existing canvas/plot modules).
- `from logger.logger_service import get_logger; logger = get_logger(__name__)`; f-strings; no bare except.
- Constants in the package `consts.py` (`analysis/consts.py` for analysis constants), UPPER_SNAKE_CASE, one name per constant.
- `osam` must stay optional: guarded module-top import (`try: import osam / except ImportError: osam = None`), never a hard dependency.
- Default model `efficientsam:latest`. Weight downloads only when needed, always through the cancellable dialog.
- Tests are light (project convention): run only the test files this plan names, via `pixi run python -m pytest <file> -q` from `microdrop-py/`.
- PROTO = `C:\Users\Info\PycharmProjects\labelme\droplet_roi\` (read-only reference; never import from it).

---

### Task 1: `sam_detect.py` — availability, imaging, model options, consts

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/sam_detect.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py` (append)
- Test: `fluorescence_controls_ui/tests/test_sam_candidates.py`

**Interfaces:**
- Produces: `sam_available() -> bool`; `AI_MODEL_OPTIONS: tuple[tuple[str, str], ...]` (model_name, display_name); `DEFAULT_AI_MODEL = "efficientsam:latest"`; `normalize_to_uint8(arr, low_pct, high_pct) -> uint8 ndarray`; `to_rgb(gray_u8) -> (H,W,3) uint8`.

- [ ] **Step 1: Append AI constants to `analysis/consts.py`**

```python
# --------------------------------------------------------------------------- #
# AI (SAM) ROI detection                                                       #
# --------------------------------------------------------------------------- #
#: Percentile stretch bounds fed to the SAM encoder (PROTO imaging.py:
#: the high bound must sit below saturated glare or droplet rings vanish).
AI_NORMALIZE_LOW_PERCENTILE = 1.0
AI_NORMALIZE_HIGH_PERCENTILE = 99.5
#: Width the frame is downscaled to before encoding (models resize to
#: ~1024 internally, so nothing is lost).
AI_ENCODE_WORK_WIDTH_PX = 1920
#: Target prompt count for the detect-all grid sweep.
AI_DETECT_GRID_TARGET_POINTS = 144
#: Detect-all mask sanity bounds: reject specks and background grabs.
AI_DETECT_MIN_MASK_AREA_PX = 500
AI_DETECT_MAX_MASK_AREA_FRACTION = 0.35
#: Default candidate filters and drift-check interval (options row).
AI_SIGNIFICANCE_DEFAULT = 2
AI_MIN_SIZE_DEFAULT_PX = 0
AI_DRIFT_CHECK_INTERVAL_DEFAULT = 3
```

- [ ] **Step 2: Create `sam_detect.py` with the guarded import, model list, and imaging helpers**

Header + availability + options (the rest of the module grows in Tasks 2-3):

```python
"""SAM droplet detection: osam session, point/grid segmentation, and
candidate conversion. Qt-free (numpy/cv2 in-and-out), importable with or
without the optional ``osam`` package — ``sam_available()`` reports which.

Ported from the standalone droplet_roi prototype (labelme-derived); see
docs/superpowers/specs/2026-08-07-automatic-roi-identification-design.md.
"""

import collections
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from traits.api import (
    Array,
    Bool,
    Float,
    HasTraits,
    Int,
    List,
    Property,
    Str,
)

from logger.logger_service import get_logger

from .consts import (
    AI_DETECT_GRID_TARGET_POINTS,
    AI_DETECT_MAX_MASK_AREA_FRACTION,
    AI_DETECT_MIN_MASK_AREA_PX,
    AI_ENCODE_WORK_WIDTH_PX,
    AI_NORMALIZE_HIGH_PERCENTILE,
    AI_NORMALIZE_LOW_PERCENTILE,
)
from .roi_geometry import normalize

logger = get_logger(__name__)

try:
    import osam
except ImportError:  # optional dependency: Help menu installs it
    osam = None

#: (model_name, display_name) — PROTO sam.py MODEL_OPTIONS, labelme's
#: point-prompt AI-assist list, speed -> accuracy within each family.
AI_MODEL_OPTIONS = (
    ("efficientsam:10m", "EfficientSam (speed)"),
    ("efficientsam:latest", "EfficientSam (accuracy)"),
    ("sam:100m", "Sam (speed)"),
    ("sam:300m", "Sam (balanced)"),
    ("sam:latest", "Sam (accuracy)"),
    ("sam2:small", "Sam2 (speed)"),
    ("sam2:latest", "Sam2 (balanced)"),
    ("sam2:large", "Sam2 (accuracy)"),
)
DEFAULT_AI_MODEL = "efficientsam:latest"


def sam_available():
    """Whether the optional osam stack imported."""
    return osam is not None


def normalize_to_uint8(
    array, low_pct=AI_NORMALIZE_LOW_PERCENTILE, high_pct=AI_NORMALIZE_HIGH_PERCENTILE
):
    """Percentile-clip contrast stretch to uint8 (PROTO imaging.py)."""
    if array.dtype == np.uint8 and array.max() > 200:
        return array
    array = array.astype(np.float64)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return np.zeros(array.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [low_pct, high_pct])
    if high - low <= 0:
        return np.zeros(array.shape, dtype=np.uint8)
    normalized = (array - low) / (high - low) * 255
    return np.nan_to_num(np.clip(normalized, 0, 255), nan=0.0).astype(np.uint8)


def to_rgb(gray_u8):
    """Stack grayscale to (H, W, 3) as the SAM encoder requires."""
    return np.stack([gray_u8] * 3, axis=-1)
```

- [ ] **Step 3: Write the first tests**

```python
"""Tests for SAM candidate conversion and filtering (no osam needed)."""

import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.sam_detect import (
    AI_MODEL_OPTIONS,
    DEFAULT_AI_MODEL,
    normalize_to_uint8,
    sam_available,
)


def test_default_model_is_one_of_the_options():
    assert DEFAULT_AI_MODEL in {name for name, _ in AI_MODEL_OPTIONS}
    assert isinstance(sam_available(), bool)


def test_normalize_stretches_16bit_to_full_range():
    ramp = np.linspace(1000, 3000, 256 * 256).reshape(256, 256)
    out = normalize_to_uint8(ramp.astype(np.uint16))
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_normalize_of_flat_frame_is_black():
    flat = np.full((16, 16), 500, dtype=np.uint16)
    assert normalize_to_uint8(flat).max() == 0
```

- [ ] **Step 4: Run** `pixi run python -m pytest "src/fluorescence-microdrop-plugin-py/fluorescence_controls_ui/tests/test_sam_candidates.py" -q` — expect 3 passed.

- [ ] **Step 5: Commit** — `feat(analysis): SAM detection module skeleton with optional osam`

---

### Task 2: `Candidate` HasTraits + mask conversion + vote dedup

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/sam_detect.py` (append)
- Test: `fluorescence_controls_ui/tests/test_sam_candidates.py` (append)

**Interfaces:**
- Produces: `Detection(HasTraits)` — `bbox: List(Float)` (xmin, ymin, xmax, ymax), `mask: Array` (bool, bbox-sized), `score: Float`; `Candidate(HasTraits)` — `polygon: List(Float)` (flat x1,y1,…), `ellipse: List(Float)` (cx,cy,rx,ry,angle), `votes: Int`, `score: Float`, `prompt: List(Float)`, `discarded: Bool`, `size: Property(Float)` (rx+ry), `source: Str` ("auto"|"click"), `geometry_for(kind) -> (str, list[float])`, `passes(min_votes, min_size) -> bool` (click-source is exempt from votes); `candidate_from_detection(detection, prompt, votes, source) -> Candidate | None`; `suppress_with_votes(pairs, iou_threshold=0.5) -> list[(Detection, int)]`.

- [ ] **Step 1: Port the geometry conversion** — adapt PROTO `geometry.py` (`roi_from_detection`, `suppress_with_votes`, `_is_redundant`, `_mask_intersection_area`) into `sam_detect.py` with these exact changes; everything else verbatim:
  - `Detection` becomes the HasTraits class in Interfaces (`from traits.api import Array`; construct with keywords: `Detection(bbox=[...], mask=mask, score=...)`).
  - `roi_from_detection` is renamed `candidate_from_detection` and returns a `Candidate` where the prototype's `Roi(bbox=…, ellipse=…, polygon=…)` was built: `polygon` flattens the `[[x, y], ...]` list to `[x1, y1, x2, y2, ...]`; `ellipse` keeps the 5 floats; drop `bbox` and `label` (unused here).
  - `Candidate.geometry_for(kind)`: `return normalize("polygon", list(self.polygon)) if kind == "polygon" else normalize("ellipse", list(self.ellipse))` — `normalize` from `roi_geometry` guarantees canonical plugin geometry.
  - `Candidate.passes(min_votes, min_size)`: `return (self.source == "click" or self.votes >= min_votes) and self.size >= min_size`.
  - `size` is `Property(Float)` with `def _get_size(self): return self.ellipse[2] + self.ellipse[3]` (guard: `0.0` when `len(self.ellipse) < 5`).

- [ ] **Step 2: Append the tests**

```python
from traits.api import TraitError  # noqa: F401  (import check only)

from fluorescence_controls_ui.image_viewer.analysis.sam_detect import (
    Candidate,
    Detection,
    candidate_from_detection,
    suppress_with_votes,
)


def _disk_detection(cx=30.0, cy=30.0, r=10, score=0.9):
    size = 2 * r + 1
    mask = np.zeros((size, size), dtype=bool)
    yy, xx = np.mgrid[0:size, 0:size]
    mask[(xx - r) ** 2 + (yy - r) ** 2 <= r**2] = True
    return Detection(bbox=[cx - r, cy - r, cx + r, cy + r], mask=mask, score=score)


def test_disk_mask_becomes_polygon_and_ellipse_candidate():
    candidate = candidate_from_detection(_disk_detection(), prompt=[30.0, 30.0])
    kind, geometry = candidate.geometry_for("ellipse")
    assert kind == "ellipse"
    cx, cy, rx, ry, _angle = geometry
    assert abs(cx - 30.0) < 1.5 and abs(cy - 30.0) < 1.5
    assert abs(rx - 10.0) < 1.5 and abs(ry - 10.0) < 1.5
    kind, polygon = candidate.geometry_for("polygon")
    assert kind == "polygon" and len(polygon) >= 6
    assert abs(candidate.size - 20.0) < 3.0


def test_duplicate_masks_merge_and_sum_votes():
    kept = suppress_with_votes(
        [(_disk_detection(score=0.9), 1), (_disk_detection(score=0.5), 1)]
    )
    assert len(kept) == 1 and kept[0][1] == 2


def test_click_candidates_are_exempt_from_significance():
    clicked = candidate_from_detection(
        _disk_detection(), prompt=[30.0, 30.0], source="click"
    )
    swept = candidate_from_detection(_disk_detection(), votes=1)
    assert clicked.passes(min_votes=2, min_size=0)
    assert not swept.passes(min_votes=2, min_size=0)
    assert not clicked.passes(min_votes=2, min_size=50)
```

- [ ] **Step 3: Run the test file** — expect all passed.
- [ ] **Step 4: Commit** — `feat(analysis): SAM mask -> Candidate conversion with vote dedup`

---

### Task 3: `OsamSession` + `SamRefiner` port

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/sam_detect.py` (append)

**Interfaces:**
- Produces: `SamRefiner(model_name)` with `.model_name`, `.prepare(image_id, gray_u8)`, `.segment_point(image_id, x_full, y_full) -> Detection | None`, `.segment_grid(image_id, image_shape, progress_cb=None) -> list[(Detection, list[float], int)]`.

- [ ] **Step 1: Port PROTO `sam.py`** — copy `_patch_osam_providers`, `OsamSession`, and `SamRefiner` with these exact changes; everything else verbatim:
  - All code must tolerate `osam is None`: wrap the whole port in nothing — instead, `_patch_osam_providers()` is only CALLED under `if osam is not None:` at module bottom, and `SamRefiner.__init__` raises `RuntimeError("osam is not installed")` when `not sam_available()` (the controller gates on `ai_available`, this is a safety net).
  - Strip type annotations and dataclass usage to match plugin style; `WORK_WIDTH` → `AI_ENCODE_WORK_WIDTH_PX`; `target_points` default → `AI_DETECT_GRID_TARGET_POINTS`; the `500 <= area` / `0.35 *` literals in `segment_grid` → `AI_DETECT_MIN_MASK_AREA_PX` / `AI_DETECT_MAX_MASK_AREA_FRACTION`.
  - `segment_grid` loses its `rect` parameter (no detection region in v1): the grid always spans `image_shape`, and `_mostly_inside` is not ported.
  - `_upscale` returns the Task-2 `Detection` (keyword construction) instead of the dataclass.
  - `OsamSession`/`SamRefiner` keep plain-class internals? No — convert both to `HasTraits`: locks and caches become typed traits (`Instance(threading.Lock)` won't validate an `RLock`; use `_lock = Instance(object)` — NO: per the Union/Either directive use `_lock = Either(None, Instance(type(threading.Lock())))`… **Decision:** these two classes hold locks, deques and ONNX handles — implement them as `HasTraits` with `traits_init` creating the members as traits: `_model_name = Str()`, `_embedding_cache = Instance(collections.deque)`, `_lock = Instance(threading.Lock().__class__)` is unnameable, so declare `_lock = Instance(object)` is forbidden by the Any-avoidance rule only for *Any*; `Instance(object)` is acceptable as "any object, validated non-primitively". Use `Instance(object)` for the lock and `Instance(collections.deque)` / `Instance(collections.OrderedDict)` for the caches, `Str` for names, `Int` for sizes.
- [ ] **Step 2: Sanity-import** — `pixi run python -c "from fluorescence_controls_ui.image_viewer.analysis.sam_detect import SamRefiner, sam_available; print(sam_available())"` (run from `src/fluorescence-microdrop-plugin-py`); expect it to print `False` (osam not installed) with no traceback.
- [ ] **Step 3: Run the Task-1/2 test file** (unchanged) — still green.
- [ ] **Step 4: Commit** — `feat(analysis): port osam session and SamRefiner`

---

### Task 4: `sam_jobs.py` — off-GUI pick / detect / track runner

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/sam_jobs.py`

**Interfaces:**
- Consumes: `SamRefiner`, `candidate_from_detection`, `suppress_with_votes`, `normalize_to_uint8` (Task 1-3); queue-kind constants defined here.
- Produces: `PICK_RESULT = "pick"`, `DETECT_PROGRESS = "detect_progress"`, `DETECT_RESULT = "detect"`, `TRACK_FRAME = "track_frame"`, `TRACK_FINISHED = "track_finished"`, `AI_FAILED = "ai_failed"`; `SamJobRunner(HasTraits)` with `.results` (`queue.SimpleQueue` of `(kind, payload)`), `.pick(refiner, image_id, gray_u16, x, y)`, `.detect_all(refiner, image_id, gray_u16, image_shape)`, `.track(refiner, frames, start_geometries, interval)` where `frames = [(path_str, capture_time), ...]` and `start_geometries = {roi_id: (cx, cy)}`, `.cancel()`, `.track_running` (`Bool`).

- [ ] **Step 1: Write the runner** following `roi_batch.py`'s shape exactly (fresh `SimpleQueue` per job family, `threading.Event` cancel, daemon threads). Payloads:
  - pick → `{"image_id": …, "candidate": Candidate | None}` (candidate has `source="click"`)
  - detect progress → `{"done": int, "total": int}`; detect result → `{"image_id": …, "capture_time": float, "candidates": [Candidate, ...]}` (built: `segment_grid` → `suppress_with_votes` → `candidate_from_detection` per kept pair, exactly PROTO `workers.py DetectAllWorker.run`)
  - track: port PROTO `workers.py TrackWorker.run` minus Qt — prefetch thread loads each frame with `cv2.imread(path, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)` → `normalize_to_uint8` → `refiner.prepare`; consumer decodes each ROI's center in a 4-worker pool; **interval**: only every `interval`-th frame (plus always the final frame) is segmented — skipped frames are simply not emitted (inheritance is free via `effective_geometry`). Per segmented frame emit `(TRACK_FRAME, {"capture_time": t, "geometries": {roi_id: (cx, cy, detection)}})` → the payload carries `{roi_id: Candidate | None}` (None = keep previous; centers chain from the candidate's ellipse center when found, else stay).
  - Every worker wraps its body in `try/except Exception` → `results.put((AI_FAILED, {"stage": …, "error": str(error)}))` and logs `logger.warning(f"SAM {stage} failed: {error}")`.
- [ ] **Step 2: Sanity-import** the module (same pattern as Task 3 Step 2).
- [ ] **Step 3: Commit** — `feat(analysis): SAM job runner (pick/detect/track) off the GUI thread`

---

### Task 5: Model & preferences plumbing

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py` (RoiAnalysisModel, after the `fit_method_choices` block)
- Modify: `fluorescence_controls_ui/preferences.py`

**Interfaces:**
- Produces (on `RoiAnalysisModel`): `ai_available = Bool(False)`; `ai_pick_button`, `ai_detect_button`, `ai_track_button`, `ai_accept_button`, `ai_clear_button` (all `Button()`); `ai_candidates = List(Instance(Candidate))`; `ai_significance = Int(AI_SIGNIFICANCE_DEFAULT)`; `ai_min_size = Int(AI_MIN_SIZE_DEFAULT_PX)`; `ai_output_kind = Enum("polygon", "ellipse")`; `ai_drift_interval = Range(1, 50, AI_DRIFT_CHECK_INTERVAL_DEFAULT)`; `ai_track_running = Bool(False)`; `ai_accept_count = Int(0)`; `canvas_ai_pick = Event()` (# (x, y)); `canvas_candidate_clicked = Event()` (# candidate index); `ai_rois_accepted = Event()` (# list of (kind, geometry) pairs, plus anchor float: payload `(pairs, anchor)`); `interaction_mode` gains `"ai_pick"`.
- Produces (preferences): `fluorescence_ai_model = Str(DEFAULT_AI_MODEL, desc="SAM model for AI ROI detection")` on `FluorescencePreferences`; an "AI ROI detection" group on the pane.

- [ ] **Step 1: Add the traits to `RoiAnalysisModel`** exactly as in Interfaces (imports: `Range`, `Event`, `Button` already partly present; `Candidate` from `.sam_detect`; the three `AI_*_DEFAULT` consts). Add `"ai_pick"` to the `interaction_mode = Enum(...)` list.
- [ ] **Step 2: Preferences** — in `preferences.py` add to `FluorescencePreferences` (below the fit-presets trait):

```python
# SAM model for AI ROI detection in the image viewer. Weights are
# downloaded on demand (cancellable dialog); cancel reverts this.
fluorescence_ai_model = Str(DEFAULT_AI_MODEL, desc="SAM model for AI ROI detection")
```

with `from .image_viewer.analysis.sam_detect import AI_MODEL_OPTIONS, DEFAULT_AI_MODEL` at the top, and on the pane a new group after `controls_group`, following the existing pattern:

```python
ai_group = create_item_label_group(
    "fluorescence_ai_model",
    label_text="AI ROI detection model",
    item_editor=EnumEditor(
        values={
            name: f"{index}:{label}"
            for index, (name, label) in enumerate(AI_MODEL_OPTIONS)
        }
    ),
    group_label="AI ROI Detection",
    group_show_border=True,
    group_style_sheet=preferences_group_style_sheet,
)
```

(`EnumEditor` from `traitsui.api`; check `create_item_label_group`'s signature in `microdrop_utils/preferences_UI_helpers.py` first — if it takes no `item_editor` argument, build the group as the `settings` VGroup does, with an explicit `Item("fluorescence_ai_model", editor=EnumEditor(...), show_label=False)`.) Add `ai_group` to the pane's `View(...)`.
- [ ] **Step 3: Sanity-import** `fluorescence_controls_ui.preferences` and `...analysis.roi_model` (Task 3 Step 2 pattern).
- [ ] **Step 4: Commit** — `feat(controls-ui): AI model preference and analysis-model AI traits`

---

### Task 6: `sam_download.py` — cancellable weight download (Qt)

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/sam_download.py`

**Interfaces:**
- Produces: `model_is_cached(model_name) -> bool`; `download_ai_model(model_name, parent=None) -> bool` (True = weights present at return; instant True when cached; False on cancel/failure).

- [ ] **Step 1: Port PROTO `download.py` verbatim** with these changes: module docstring names this plugin; `logging.getLogger` → `get_logger` (convention); add

```python
def model_is_cached(model_name):
    """Whether the model's weights are already in the osam cache."""
    return osam.apis.get_model_type_by_name(model_name).get_size() is not None
```

and have `download_ai_model` early-return `True` via `model_is_cached`. Top import is `import osam` guarded like Task 1 (`osam = None` fallback; both functions raise `RuntimeError("osam is not installed")` when it is None — callers gate on `ai_available` first).
- [ ] **Step 2: Sanity-import** the module headlessly (it must import without osam and without a QApplication).
- [ ] **Step 3: Commit** — `feat(controls-ui): cancellable SAM weight download dialog`

---

### Task 7: `AiRoiController` — glue, gates, drain, accept

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/ai_controller.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (add `_create_rois` + `ai_rois_accepted` observer)
- Modify: `fluorescence_controls_ui/image_viewer/dock_pane.py`
- Test: `fluorescence_controls_ui/tests/test_ai_candidate_flow.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `AiRoiController(HasTraits)` with `viewer_model`, `analysis_model`, `runner = Instance(SamJobRunner, ())`, `refiner = Either(None, Instance(SamRefiner))`, `drain_results()`; `RoiAnalysisController._create_rois(pairs, anchor)`.

- [ ] **Step 1: `RoiAnalysisController._create_rois`** — below `_create_roi`:

```python
@observe("analysis_model:ai_rois_accepted")
def _on_ai_rois_accepted(self, event):
    pairs, anchor = event.new
    self._create_rois(pairs, anchor)


def _create_rois(self, pairs, anchor):
    """Bulk sibling of _create_roi for accepted AI candidates: one
    save and one batch restart for the whole set."""
    created = []
    for kind, geometry in pairs:
        roi = Roi(
            name=self.session.next_roi_name(),
            kind=kind,
            geometry=[float(value) for value in geometry],
            base_anchor=anchor,
            style=RoiStyle(
                color=DEFAULT_ROI_COLORS[
                    len(self.session.rois) % len(DEFAULT_ROI_COLORS)
                ]
            ),
        )
        self.session.rois.append(roi)
        created.append(roi)
    if not created:
        return created
    self._save_config()
    self._restart_batch_if_running()
    for roi in created:
        self._instant_stats(roi)
    return created
```

- [ ] **Step 2: Write `AiRoiController`** (module mirrors `roi_controller.py`'s header conventions). Responsibilities, each an `@observe` handler or method:
  - `traits_init`: `self.analysis_model.ai_available = sam_available()`.
  - **Model gate** `_ensure_model_ready() -> bool`: `sam_available()` and (`model_is_cached(name)` or `download_ai_model(name)`); `name = self.viewer_model.preferences.fluorescence_ai_model`. Called at the top of every launcher; False aborts with `progress_text = "AI model not available"`.
  - **Refiner lifecycle**: `_refiner_for_current_model()` builds/caches `SamRefiner(model_name)`; `@observe` on the preference trait — on change to an uncached model run `download_ai_model`; on False **revert** the preference to the previous value (keep `_last_ai_model = Str()` updated on every successful switch) without re-triggering the download (guard with a `_reverting = Bool` flag); on success drop `self.refiner` so the next use rebuilds.
  - `@observe("analysis_model:ai_pick_button")` → arm/disarm `"ai_pick"` via the same toggle idiom as `RoiAnalysisController._arm`.
  - `@observe("analysis_model:canvas_ai_pick")` → gate → `runner.pick(refiner, current_path, self.viewer_model.array, x, y)`; `progress_text = "Segmenting…"`.
  - `@observe("analysis_model:ai_detect_button")` → gate → clear `ai_candidates`, `runner.detect_all(...)` with the current array + `capture_timestamp(current_path)`.
  - `@observe("analysis_model:ai_track_button")` → if `runner.track_running`: `runner.cancel()`; else gate → snapshot `frames = [(str(p), capture_timestamp(p)) for p in viewer_model.paths after current]`, `start_geometries` from `session.effective_for(current_path)` centers (`centre_of` from `roi_geometry`), `runner.track(refiner, frames, start_geometries, analysis_model.ai_drift_interval)`; mirror `ai_track_running`.
  - `@observe("analysis_model:canvas_candidate_clicked")` → toggle `ai_candidates[index].discarded`.
  - `@observe("analysis_model:ai_accept_button")` → `pairs = [c.geometry_for(model.ai_output_kind) for c in model.ai_candidates if not c.discarded and c.passes(model.ai_significance, model.ai_min_size)]`; fire `model.ai_rois_accepted = (pairs, anchor)` (anchor = the detect frame's capture time, stored on the controller when the detect result drained); clear `ai_candidates`.
  - `@observe("analysis_model:ai_clear_button")` → clear `ai_candidates`.
  - `@observe("analysis_model:ai_candidates.items, analysis_model:ai_candidates, analysis_model:ai_significance, analysis_model:ai_min_size")` → recompute `ai_accept_count`.
  - `drain_results()`: empty `runner.results`; `PICK_RESULT` with a candidate → immediate single accept (`ai_rois_accepted = ([candidate.geometry_for(kind)], anchor_of_current_image)`), None → `progress_text = "No droplet found there"`; `DETECT_PROGRESS` → `progress_text = f"AI detect {done}/{total}"`; `DETECT_RESULT` → set `ai_candidates`, remember its `capture_time`; `TRACK_FRAME` → for each `roi_id, candidate`: `session.roi_by_id(roi_id).apply_edit(capture_time, candidate.geometry_for(model.ai_output_kind)[1])` when candidate is not None, then `_save_config()`-equivalent via firing the existing save path (call `analysis_model` — no: fire nothing; instead the controller holds a reference to `RoiAnalysisController`? It must not. **Persist via the shared model**: fire `analysis_model.canvas_roi_edited = (roi_id, geometry)`? That anchors at the *displayed* image — wrong frame. **Decision:** give `RoiAnalysisModel` one more event `ai_roi_tracked = Event()` (# (roi_id, capture_time, geometry)) and let `RoiAnalysisController` observe it, calling `roi.apply_edit(capture_time, geometry)` + debounced `_save_config()` (save once per drain: collect during drain, save at end — implement in the observer by marking a `_config_dirty` Bool on RoiAnalysisController flushed in its existing `drain_results`). `TRACK_FINISHED` → `ai_track_running = False`, progress text; `AI_FAILED` → progress text + already logged.
- [ ] **Step 3: Dock pane wiring** — in `dock_pane.py`: import `AiRoiController`, add `ai_controller = Instance(AiRoiController)` trait, build it in `traits_init` beside `analysis_controller` (same two models), and extend `_drain_tick` with `self.ai_controller.drain_results()`.
- [ ] **Step 4: Controller test** (`test_ai_candidate_flow.py`, pattern of `test_roi_editing.py` — fresh `RoiAnalysisModel()`/`FluorescenceImageViewerModel()`, both controllers instantiated):

```python
"""Accept/discard flow: candidates -> filters -> session ROIs."""

import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.ai_controller import (
    AiRoiController,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_controller import (
    RoiAnalysisController,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    RoiAnalysisModel,
)
from fluorescence_controls_ui.image_viewer.analysis.sam_detect import (
    Candidate,
)
from fluorescence_controls_ui.image_viewer.model import (
    FluorescenceImageViewerModel,
)


def _candidate(votes, rx=10.0):
    return Candidate(
        polygon=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
        ellipse=[10.0, 10.0, rx, rx, 0.0],
        votes=votes,
        score=0.9,
    )


def _controllers():
    viewer = FluorescenceImageViewerModel()
    analysis = RoiAnalysisModel()
    roi_controller = RoiAnalysisController(viewer_model=viewer, analysis_model=analysis)
    ai_controller = AiRoiController(viewer_model=viewer, analysis_model=analysis)
    return analysis, roi_controller, ai_controller


def test_accept_commits_only_filter_passing_undiscarded_candidates():
    analysis, roi_controller, _ai = _controllers()
    analysis.ai_candidates = [
        _candidate(votes=3),
        _candidate(votes=1),
        _candidate(votes=3),
    ]
    analysis.ai_candidates[2].discarded = True
    analysis.ai_significance = 2
    analysis.ai_accept_button = True
    assert len(roi_controller.session.rois) == 1
    assert analysis.ai_candidates == []


def test_output_kind_controls_accepted_geometry():
    analysis, roi_controller, _ai = _controllers()
    analysis.ai_output_kind = "ellipse"
    analysis.ai_candidates = [_candidate(votes=5)]
    analysis.ai_accept_button = True
    assert roi_controller.session.rois[0].kind == "ellipse"
```

- [ ] **Step 5: Run** both test files named so far — all green.
- [ ] **Step 6: Commit** — `feat(controls-ui): AI ROI controller with candidate accept flow`

---

### Task 8: Canvas — candidate outlines + ai_pick clicks

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (`_ImageCanvasEditor` wiring)

**Interfaces:**
- Produces: `RoiCanvasLayer.set_candidates(candidates)` (list of `(index, kind, geometry, discarded)` tuples — the layer stays model-agnostic); `RoiCanvasLayer.on_ai_pick` and `.on_candidate_clicked` callbacks; mode `"ai_pick"` accepted by `set_mode`.

- [ ] **Step 1: Candidate items** — follow the `BallReferenceItem` pattern (own sentinel id-space, never in `session.rois`): dashed 1.5-px pen, discarded candidates at 30% alpha; rebuild items in `set_candidates`. Clicking a candidate item (in any mode) calls `on_candidate_clicked(index)`. In `"ai_pick"` mode a click on empty image calls `on_ai_pick(x, y)` (image coordinates, same transform as the draw tools).
- [ ] **Step 2: Wire in `view.py`** — where `on_ball_radius_changed` / draw callbacks are bound (`view.py:279-291`): `layer.on_ai_pick = lambda x, y: setattr(analysis_model, "canvas_ai_pick", (x, y))`; `layer.on_candidate_clicked = lambda index: setattr(analysis_model, "canvas_candidate_clicked", index)`. Observe `analysis_model.ai_candidates` (+`.items` and each candidate's `discarded`) in `_ImageCanvasEditor` to push `set_candidates([(i, *c.geometry_for(analysis_model.ai_output_kind), c.discarded) ...])` — reuse the existing `_on_roi_state_changed` re-sync idiom.
- [ ] **Step 3: Manual smoke** — none possible without osam; instead run the full named test files (green) and `pixi run python -m py_compile` on both modified files.
- [ ] **Step 4: Commit** — `feat(controls-ui): candidate preview layer and AI-pick clicks on the canvas`

---

### Task 9: Toolbar glyphs + options row

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (`analysis_toolbar`, `correction_group` area)

**Interfaces:**
- Consumes: model traits from Task 5; `analysis` context object (registered by `dock_pane.trait_context`).

- [ ] **Step 1: Toolbar** — append to `analysis_toolbar` after the reset button, using icons from `microdrop_style.icons.icons` (pick existing glyphs: `ICON_AUTO_AWESOME` or nearest available "AI/sparkle" glyph for the picker, `ICON_GRID_ON`-style for detect-all, `ICON_TIMELINE`-style for tracking — check `icons.py` for what exists and choose the closest three, no new font assets):

```python
(
    UItem(
        "object.roi_analysis.ai_pick_button",
        editor=IconModeButtonEditor(
            glyph=ICON_AI_PICK,
            mode="ai_pick",
            tooltip="AI picker: click a droplet and the model segments "
            "it into an ROI. Stays armed — Esc puts it away",
        ),
        enabled_when="analysis.ai_available",
    ),
)
(
    UItem(
        "object.roi_analysis.ai_detect_button",
        editor=IconButtonEditor(
            glyph=ICON_AI_DETECT,
            tooltip="Detect all droplets on this frame (AI grid "
            "sweep). Results appear as dashed candidates: "
            "click to discard, then Accept",
        ),
        enabled_when="analysis.ai_available",
    ),
)
(
    UItem(
        "object.roi_analysis.ai_track_button",
        editor=IconButtonEditor(
            glyph=ICON_AI_TRACK,
            tooltip="Track the ROIs across later frames (drift). "
            "Press again to stop; finished frames are kept",
        ),
        enabled_when="analysis.ai_available",
    ),
)
```

  When AI is unavailable the buttons are disabled; extend each tooltip with "— install via Help > Install AI support" ONLY in the disabled state if the editor supports it, otherwise append that sentence to all three tooltips unconditionally.
- [ ] **Step 2: Options row** — a new `ai_group = HGroup(...)` directly under `correction_group`, `visible_when="analysis.ai_available"`: `Label("AI")`, significance spinner (`RangeEditor(low=1, high=20, mode="spinner", auto_set=True)` on `object.roi_analysis.ai_significance`, tooltip from the README: "grid votes — clear droplets score 2-4, noise 1"), min-size spinner (`low=0, high=500`) on `ai_min_size`, output-kind `EnumEditor` on `ai_output_kind`, drift-interval spinner on `ai_drift_interval` (label "drift every N"), then `UItem("object.roi_analysis.ai_accept_button", editor=IconButtonEditor(glyph=ICON_CHECK, tooltip="Accept the filter-passing candidates as ROIs"), visible_when="analysis.ai_accept_count > 0")` and the matching Clear button (`visible_when="len(analysis.ai_candidates) > 0"`). Add `ai_group` to the `View` right after `correction_group`.
- [ ] **Step 3: Compile + run named tests.**
- [ ] **Step 4: Commit** — `feat(controls-ui): AI toolbar glyphs and detection options row`

---

### Task 10: Help-menu installer + optional extra

**Files:**
- Create: `fluorescence_controls_ui/ai_install.py`
- Modify: `fluorescence_controls_ui/menus.py`, `pyproject.toml`

**Interfaces:**
- Produces: `install_ai_support(parent=None) -> bool` (runs `pixi add --pypi osam` — plus `onnxruntime-directml` on Windows — from the pixi project root, cancellable-safe, returns success); `InstallAiSupportAction` in the Help group.

- [ ] **Step 1: `ai_install.py`** — locate the pixi root by walking up from the running executable/env (`Path(sys.prefix)` parents until a `pixi.toml`/`pyproject.toml` with `[tool.pixi]` is found; fall back to `Path.cwd()`); run `["pixi", "add", "--pypi", "osam"]` (append a second call with `onnxruntime-directml` when `sys.platform == "win32"`, tolerated failure) via `subprocess.Popen` in a worker thread; show a `QProgressDialog` (indeterminate, cancellable — cancel kills the process) streaming the last output line into the label; on exit 0 re-probe by `importlib.invalidate_caches()` + attempting `import osam`, and return whether it imported.
- [ ] **Step 2: menus.py** — add

```python
class InstallAiSupportAction(Action):
    name = Str("Install &AI ROI Support...")
    tooltip = "Install the SAM segmentation stack (osam) with pixi"

    def perform(self, event):
        from .ai_install import install_ai_support

        if install_ai_support():
            roi_analysis_model.ai_available = True
```

(`from .image_viewer.analysis.roi_model import roi_analysis_model` at module top — same singleton the pane uses, so the toolbar enables live) and append it to `help_menu_factory()`'s `SGroup`.
- [ ] **Step 3: pyproject.toml** — add under `[project.optional-dependencies]` (create the table if absent): `ai = ["osam"]`.
- [ ] **Step 4: Compile, run all three named test files, commit** — `feat(controls-ui): Help-menu AI support installer and optional extra`

---

### Task 11: End-to-end verification + PR

- [ ] **Step 1:** `pixi run python -m py_compile` over every created/modified file; run the three test files.
- [ ] **Step 2:** Manual GUI pass (user, with `pixi add --pypi osam` done via the new menu action): pick model in Preferences (watch download dialog + cancel-revert), AI-pick a droplet, Detect all → slider filtering → Accept, Track drift over a burst, confirm overrides land (drag-check a later frame) and stats recompute.
- [ ] **Step 3:** Report results; on approval push `feat/automatic-roi-identification` and open the PR (`gh pr create --base main`) titled `feat(controls-ui): AI-assisted automatic ROI identification`, body summarizing the spec; wait for user before merging.

## Self-review notes

- Spec coverage: model prefs + guarded download (T5/T6/T7), picker (T7/T8/T9), detect+review (T2/T4/T7/T8/T9), tracking→overrides (T4/T7), installer/extra (T10), tests (T1/T2/T7). Region rect & electrode seeding: explicitly out of scope.
- Type consistency: `Candidate.geometry_for` returns `(kind, geometry)` everywhere; `ai_rois_accepted` payload is `(pairs, anchor)` in T5/T7; runner queue kinds defined once in T4.
- Known judgment calls for implementers: exact icon constants (pick nearest existing in `icons.py`); `create_item_label_group` signature (check before use, fallback shown); `Instance(object)` for lock traits is the sanctioned narrow-not-Any choice.
