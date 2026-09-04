# Background Ring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the background ring into a true annulus outside the ROI, under user control, excluding neighbouring ROIs, drawn on the canvas — plus the subtract-first transform toggle.

**Architecture:** `ring_mask` builds the annulus by dilating the ROI's own mask, so every shape kind including traced contours works through one path. The ring parameters live on the session, travel with the work items, and join the stats cache key so changing them recomputes. `ring_contours` gives the canvas the same mask as an outline.

**Tech Stack:** OpenCV morphology, numpy, PySide6 QGraphicsScene, Traits/TraitsUI.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-background-ring-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- The ring must **never** include interior pixels. `gap_px = 0` means its inner edge is the ROI boundary.
- `outline_*` stat names stay; only what they measure changes.
- Dilate on a crop of the ROI's bounding box padded by `gap + thickness`, not the whole frame.
- f-strings; module-level imports; constants in `analysis/consts.py`; conventional commits.
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/<file> -q"` (always from `microdrop-py`).
- Known pre-existing failures, not yours: `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults`, `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions`, two in `fluorescence_controller/tests/test_command_setter.py`.
- Never launch the GUI. Never push.

---

### Task 1: The annulus and its contours

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_compute.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Test: `fluorescence_controls_ui/tests/test_roi_compute.py`

**Interfaces:**
- Produces: `ring_mask(interior, gap_px, thickness_px) -> ndarray`; `ring_contours(shape, kind, geometry, gap_px, thickness_px) -> list[ndarray]`; `roi_masks(shape, kind, geometry, gap_px=RING_GAP_PX, thickness_px=RING_THICKNESS_PX) -> (interior, ring)`; `RING_GAP_PX = 2`, `RING_THICKNESS_PX = 4`.

- [ ] **Step 1: Add the constants** to `analysis/consts.py`, replacing `OUTLINE_PERIMETER_PX` (delete it — nothing should stroke a boundary as background again):

```python
#: Background annulus: how far outside the ROI edge it starts, and how
#: thick it is, in pixels. The gap exists because fluorescence bleeds a
#: pixel or two past the boundary and that halo is not background.
RING_GAP_PX = 2
RING_THICKNESS_PX = 4
```

- [ ] **Step 2: Write the failing tests** — replace the outline assertions in `test_roi_compute.py` and add:

```python
def test_ring_never_touches_the_interior():
    interior, ring = roi_masks((200, 200), "ellipse", (100.0, 100.0, 30.0, 30.0, 0.0))
    assert np.count_nonzero((interior == 255) & (ring == 255)) == 0


def test_ring_area_matches_the_annulus():
    gap, thickness = 2, 4
    interior, ring = roi_masks(
        (300, 300), "ellipse", (150.0, 150.0, 40.0, 40.0, 0.0), gap, thickness
    )
    inner, outer = 40.0 + gap, 40.0 + gap + thickness
    expected = math.pi * (outer**2 - inner**2)
    assert abs(np.count_nonzero(ring) - expected) / expected < 0.10


def test_gap_pushes_the_ring_outwards():
    centre = (150.0, 150.0, 40.0, 40.0, 0.0)
    _interior, tight = roi_masks((300, 300), "ellipse", centre, 0, 3)
    _interior, spaced = roi_masks((300, 300), "ellipse", centre, 6, 3)
    rows, columns = np.nonzero(tight)
    tight_inner = np.min(np.hypot(columns - 150.0, rows - 150.0))
    rows, columns = np.nonzero(spaced)
    spaced_inner = np.min(np.hypot(columns - 150.0, rows - 150.0))
    assert abs(tight_inner - 40.0) < 2.0
    assert abs(spaced_inner - 46.0) < 2.0


def test_background_correction_recovers_the_true_signal():
    # The regression this cycle exists for: the old boundary-stroke
    # ring read 1569 where the answer is 2900.
    image = np.full((200, 200), 100, dtype=np.uint16)
    cv2.circle(image, (100, 100), 30, 3000, -1)
    interior, ring = roi_masks((200, 200), "ellipse", (100.0, 100.0, 30.0, 30.0, 0.0))
    corrected = (
        masked_stats(image, interior)["mean"] - masked_stats(image, ring)["mean"]
    )
    assert abs(corrected - 2900.0) < 30.0


def test_ring_excludes_a_neighbouring_roi(tmp_path):
    array = np.full((200, 200), 100, dtype=np.uint16)
    cv2.circle(array, (100, 100), 20, 3000, -1)
    cv2.circle(array, (135, 100), 20, 3000, -1)  # neighbour, close by
    path = tmp_path / "img_2026_07_20-17_46_24_raw.png"
    cv2.imwrite(str(path), array)
    result = compute_image_stats(
        str(path),
        {
            "a": ("ellipse", (100.0, 100.0, 20.0, 20.0, 0.0)),
            "b": ("ellipse", (135.0, 100.0, 20.0, 20.0, 0.0)),
        },
    )
    # Without the exclusion the neighbour's 3000 would drag this up.
    assert result["stats"]["a"]["outline_mean"] < 200.0


def test_ring_contours_trace_the_annulus():
    contours = ring_contours(
        (300, 300), "ellipse", (150.0, 150.0, 40.0, 40.0, 0.0), 2, 4
    )
    assert len(contours) == 2  # an outer and an inner boundary
    extents = sorted(
        np.max(np.hypot(points[:, 0] - 150.0, points[:, 1] - 150.0))
        for points in contours
    )
    assert abs(extents[0] - 42.0) < 2.0  # inner edge: radius + gap
    assert abs(extents[1] - 46.0) < 2.0  # outer: + thickness
```

Keep the existing interior-mask tests; delete only assertions about the old boundary stroke.

- [ ] **Step 3: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: ImportError on `ring_contours`, and the ring tests failing on the stroked outline.

- [ ] **Step 4: Write the annulus** in `roi_compute.py`, replacing the outline half of `roi_masks`:

```python
def _disk(radius):
    return cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)
    )


def ring_mask(interior, gap_px, thickness_px):
    """The annulus outside ``interior``: the shape dilated by
    gap + thickness, less the shape dilated by gap. With gap 0 the
    inner edge is the shape's own boundary, so the ring can never
    contain interior pixels. Dilation is exactly 'expand by N', which
    is why this works for a traced contour as readily as an ellipse."""
    gap_px = max(int(gap_px), 0)
    thickness_px = max(int(thickness_px), 1)
    ring = np.zeros_like(interior)
    rows, columns = np.nonzero(interior)
    if not len(rows):
        return ring
    # Dilate on a crop, so cost tracks the ROI rather than the frame.
    pad = gap_px + thickness_px + 1
    top = max(int(rows.min()) - pad, 0)
    bottom = min(int(rows.max()) + pad + 1, interior.shape[0])
    left = max(int(columns.min()) - pad, 0)
    right = min(int(columns.max()) + pad + 1, interior.shape[1])
    patch = interior[top:bottom, left:right]
    outer = cv2.dilate(patch, _disk(gap_px + thickness_px))
    inner = cv2.dilate(patch, _disk(gap_px)) if gap_px else patch
    ring[top:bottom, left:right] = cv2.subtract(outer, inner)
    return ring


def ring_contours(
    shape, kind, geometry, gap_px=RING_GAP_PX, thickness_px=RING_THICKNESS_PX
):
    """The annulus's boundaries as (N, 2) image-pixel arrays — the
    canvas draws these, taken from the very mask that is averaged, so
    the two cannot disagree."""
    interior, ring = roi_masks(shape, kind, geometry, gap_px, thickness_px)
    found, _hierarchy = cv2.findContours(ring, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    return [points.reshape(-1, 2).astype(float) for points in found if len(points) >= 3]
```

and rewrite `roi_masks` to build the interior as it does today, then
`ring = ring_mask(interior, gap_px, thickness_px)`, importing the two
constants and dropping `OUTLINE_PERIMETER_PX`.

- [ ] **Step 5: Exclude the neighbours** — rewrite `compute_image_stats`'s loop into two passes:

```python
interiors, rings = {}, {}
for roi_id, (kind, geometry) in effective_rois.items():
    interiors[roi_id], rings[roi_id] = roi_masks(
        array.shape[:2], kind, geometry, gap_px, thickness_px
    )
union = np.zeros(array.shape[:2], dtype=np.uint8)
for interior in interiors.values():
    cv2.bitwise_or(union, interior, union)
for roi_id, ring in rings.items():
    # Another ROI's interior is not background, however close.
    others = cv2.subtract(union, interiors[roi_id])
    ring[others == 255] = 0
    stats = masked_stats(array, interiors[roi_id])
    for name, value in masked_stats(array, ring).items():
        stats[OUTLINE_STATS_PREFIX + name] = value
    result["stats"][roi_id] = stats
```

with the signature gaining the parameters:

```python
def compute_image_stats(image_path, effective_rois,
                        gap_px=RING_GAP_PX,
                        thickness_px=RING_THICKNESS_PX):
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: all pass, including `bg_corrected` ≈ 2900.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_compute.py fluorescence_controls_ui/image_viewer/analysis/consts.py fluorescence_controls_ui/tests/test_roi_compute.py
git commit -m "fix(analysis): measure background in a true annulus"
```

---

### Task 2: The parameters, the cache key, and the work items

**Files:**
- Modify: `roi_model.py` (`BackgroundRing`, `AnalysisSession.ring`, `cache_key`)
- Modify: `roi_store.py` (`_RING_FIELDS`, `_stats_key`, `save_roi_stats`)
- Modify: `roi_batch.py` (work items carry the ring)
- Modify: `roi_controller.py` (build work items, instant stats, persistence observer)
- Test: `test_roi_store.py`, `test_analysis_session.py`, `test_roi_batch.py`

**Interfaces:**
- Produces: `BackgroundRing(gap_px, thickness_px, show_on_canvas)`; `session.ring`; `cache_key(...)` returning a 6-tuple ending `(gap_px, thickness_px)`; work items `(path, effective_rois, ring)`.

- [ ] **Step 1: Write the failing tests**

In `test_analysis_session.py`:

```python
def test_cache_key_includes_the_ring(tmp_path):
    image = tmp_path / "a_2026_07_20-10_00_00_raw.png"
    image.write_bytes(b"")
    roi = Roi(name="ROI 1", kind="ellipse", geometry=[5.0, 5.0, 2.0, 2.0, 0.0])
    session = AnalysisSession(rois=[roi])
    before = session.cache_key(str(image), roi)
    session.ring.gap_px = 5
    after = session.cache_key(str(image), roi)
    assert before != after
    assert after[5] == (5, session.ring.thickness_px)
```

In `test_roi_store.py`:

```python
def test_background_ring_round_trips(tmp_path):
    session = AnalysisSession(directory=str(tmp_path))
    session.ring.trait_set(gap_px=3, thickness_px=7, show_on_canvas=False)
    save_session(tmp_path, session)

    ring = load_session(tmp_path).ring
    assert ring.gap_px == 3 and ring.thickness_px == 7
    assert ring.show_on_canvas is False


def test_stats_written_before_the_ring_are_ignored(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_stats.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "path": str(tmp_path / "a_raw.png"),
                        "mtime": 1.0,
                        "roi_id": "abcd1234",
                        "kind": "ellipse",
                        "geometry": [5.0, 5.0, 2.0, 2.0, 0.0],
                        "stats": {"mean": 7.0},
                    }
                ],
            }
        )
    )
    # They were measured with the boundary-stroke ring, so no current
    # key may match them.
    (key,) = load_roi_stats(tmp_path)
    assert key[5] is None
```

- [ ] **Step 2: Run them and watch them fail**

Run both files; expected `AttributeError: 'AnalysisSession' object has no attribute 'ring'`.

- [ ] **Step 3: Add the model** — in `roi_model.py`, beside `ScaleCalibration`:

```python
class BackgroundRing(HasTraits):
    """The annulus each ROI's background is read from (persisted per
    experiment). These change what is measured, so they are part of
    the stats cache key."""

    #: Pixels between the ROI's edge and the ring — fluorescence bleeds
    #: past the boundary and that halo is not background.
    gap_px = Range(0, 50, RING_GAP_PX, mode="spinner")
    thickness_px = Range(1, 50, RING_THICKNESS_PX, mode="spinner")
    show_on_canvas = Bool(True)
```

with `from .consts import RING_GAP_PX, RING_THICKNESS_PX`, plus
`ring = Instance(BackgroundRing, ())` on `AnalysisSession`, and the
key:

```python
return (
    str(path),
    mtime,
    roi.roi_id,
    roi.kind,
    tuple(roi.effective_geometry(capture_time)),
    (self.ring.gap_px, self.ring.thickness_px),
)
```

- [ ] **Step 4: Persist and migrate** — `roi_store.py` gains
`_RING_FIELDS = ("gap_px", "thickness_px", "show_on_canvas")`, a
`"ring"` block in `save_session` and its tolerated-missing load
mirroring the scale block, plus the key change:

```python
payload = {
    "version": 1,
    "entries": [
        {
            "path": key[0],
            "mtime": key[1],
            "roi_id": key[2],
            "kind": key[3],
            "geometry": list(key[4]),
            "ring": list(key[5]),
            "stats": value,
        }
        for key, value in stats.items()
    ],
}
```

```python
def _stats_key(entry):
    """...an entry without a ring gets None, which no current key can
    equal: those numbers came from the boundary-stroke ring and must
    be recomputed rather than trusted."""
    kind, geometry = normalize(entry["kind"], entry["geometry"])
    ring = entry.get("ring")
    return (
        entry["path"],
        float(entry["mtime"]),
        entry["roi_id"],
        kind,
        tuple(geometry),
        tuple(ring) if ring is not None else None,
    )
```

- [ ] **Step 5: Carry the ring to the workers** — `roi_batch._run` unpacks three-item work entries:

```python
futures = [
    executor.submit(compute_image_stats, path, rois, ring[0], ring[1])
    for path, rois, ring in work_items
]
```

and `compute_single(path, effective_rois, ring)` passes them too. In `roi_controller`, `_missing_work` appends `(path, missing, (ring.gap_px, ring.thickness_px))`, and `_instant_stats` passes the same pair. Add the two traits to the persistence observer:

```python
"analysis_model:session:ring:gap_px,"

"analysis_model:session:ring:thickness_px, "
"analysis_model:session:ring:show_on_canvas, "
```

- [ ] **Step 6: Run the whole controls_ui suite**

Expected: only the two known pre-existing failures. Fix any test that constructs work items or cache keys by hand.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis fluorescence_controls_ui/tests
git commit -m "feat(analysis): put the ring parameters in the cache key"
```

---

### Task 3: Drawing the ring

**Files:**
- Modify: `roi_canvas_layer.py` (draw the contours), `roi_items.py` if a helper fits better there
- Modify: `image_viewer/view.py` (sync passes the ring; toolbar toggle)

**Interfaces:**
- Consumes: `ring_contours` from Task 1, `session.ring` from Task 2.
- Produces: `RoiCanvasLayer.set_ring(gap_px, thickness_px, visible)` and dashed ring outlines per ROI.

- [ ] **Step 1: Draw them in the layer**

```python
#: Dashed, half-transparent: the ring is context for the ROI, not a
#: shape the user can grab.
RING_PEN = QPen(QColor(0, 229, 255, 140), 0, Qt.PenStyle.DashLine)
```

`RoiCanvasLayer` keeps `self._ring_items = []` and a `set_ring(gap_px, thickness_px, visible)` that stores the parameters and re-syncs. In `sync`, after the item loop, clear the old ring items and — when visible and the scene has a rect — build one `QGraphicsPathItem` per ROI from `ring_contours(shape, kind, geometry, gap, thickness)`, pen coloured from the ROI's style, `setZValue(-1)` so it never sits over the shape, and non-interactive (`setAcceptedMouseButtons(Qt.MouseButton.NoButton)`).

- [ ] **Step 2: Feed it from the canvas editor** — in `view.py`'s `_sync_roi_layer`, before `self._roi_layer.sync(...)`:

```python
ring = model.roi_analysis.session.ring
self._roi_layer.set_ring(ring.gap_px, ring.thickness_px, ring.show_on_canvas)
```

and add the three ring traits to the editor's `_on_roi_state_changed` observer list (and its `remove=True` twin in `dispose`).

- [ ] **Step 3: Add the toggle** — in `analysis_toolbar`, after the scale-bar toggle:

```python
(
    UItem(
        "object.roi_analysis.show_background_ring",
        editor=IconToggleEditor(
            on_glyph=ICON_VISIBILITY,
            off_glyph=ICON_VISIBILITY_OFF,
            tooltip="Show the background ring each ROI's correction is measured from",
        ),
    ),
)
```

with `show_background_ring = Bool(True)` on `RoiAnalysisModel` mirrored onto `session.ring.show_on_canvas` by the controller, exactly as `show_scale_bar` is — the toolbar outlives any one session.

- [ ] **Step 4: Add the spinners** — in the plot pane's controls, a group with `Item("session.ring.gap_px", label="BG gap")` and `Item("session.ring.thickness_px", label="BG width")`, each with a tooltip naming pixels.

- [ ] **Step 5: Offscreen smoke** — sync a session with two ROIs, assert one ring item per ROI, that hiding clears them, that each ring item's bounding rect is larger than its ROI's, and that no ring item accepts mouse buttons.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui
git commit -m "feat(analysis): draw the background ring on the canvas"
```

---

### Task 4: Subtract-first transform

**Files:**
- Modify: `plot_series.py`, `roi_model.py` (`FigureSettings.subtract_first`), `roi_store.py` (`_FIGURE_FIELDS`), `plot_pane.py` (toggle, application, label)
- Test: `test_plot_series.py`

**Interfaces:**
- Produces: `subtracted_series(series)`; `FigureSettings.subtract_first`.

- [ ] **Step 1: Write the failing tests**

```python
def test_subtracted_series_starts_every_curve_at_zero():
    series = {
        "a": ("ROI 1", [0.0, 1.0], [10.0, 30.0]),
        "b": ("ROI 2", [0.0, 1.0], [100.0, 90.0]),
    }
    result = subtracted_series(series)
    assert result["a"][2] == [0.0, 20.0]
    assert result["b"][2] == [0.0, -10.0]


def test_subtracted_series_uses_the_first_finite_value():
    series = {"a": ("ROI 1", [0.0, 1.0, 2.0], [math.nan, 10.0, 15.0])}
    values = subtracted_series(series)["a"][2]
    assert math.isnan(values[0])
    assert values[1] == 0.0 and values[2] == 5.0


def test_subtracted_series_passes_an_all_nan_curve_through():
    series = {"a": ("ROI 1", [0.0], [math.nan])}
    assert math.isnan(subtracted_series(series)["a"][2][0])
```

- [ ] **Step 2: Implement**

```python
def subtracted_series(series):
    """``series`` with each curve less its own first finite value, so
    every ROI starts at zero and shows change from baseline. NaN stays
    NaN; a curve with no finite value passes through untouched."""
    shifted = {}
    for roi_id, (name, elapsed, values) in series.items():
        first = next((value for value in values if value == value), None)
        shifted[roi_id] = (
            name,
            elapsed,
            values
            if first is None
            else [value if value != value else value - first for value in values],
        )
    return shifted
```

`FigureSettings.subtract_first = Bool(False)` joins `_FIGURE_FIELDS` and the persistence observer. In `_refresh`, before the normalisation:

```python
        if figure_settings.subtract_first:
            series = subtracted_series(series)
```

A fourth toggle in the transforms row ("Subtract first"), `_PLOT_STATE` gains the trait, and `y_axis_label` gains the flag, appending " (change from first)" before the "% of range" suffix.

- [ ] **Step 3: Run the suites and commit**

```bash
git add fluorescence_controls_ui
git commit -m "feat(analysis): add the subtract-first transform"
```

---

### Task 5: Verification

- [ ] **Step 1: Regenerate the demo** into the scratchpad and confirm the reported fits are unchanged in shape (the ring change moves `bg_corrected`, not `mean`).
- [ ] **Step 2: Offscreen smoke** over the demo: ring items drawn for every ROI, the toggle clearing them, `bg_corrected` on a demo ROI now sitting near its true signal-over-background rather than roughly half of it, and the subtract-first toggle starting every curve at 0.
- [ ] **Step 3: Run every suite.** Expected: only the four known pre-existing failures.
- [ ] **Step 4: Report**, including that reopening an experiment recomputes its statistics once because every cached entry predates the ring.
