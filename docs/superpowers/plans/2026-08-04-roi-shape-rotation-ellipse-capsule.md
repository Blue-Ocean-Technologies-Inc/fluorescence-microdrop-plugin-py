# ROI Shapes: Rotation, Ellipses, Capsules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let ROIs rotate, let circles become ellipses, and add a capsule (spherocylinder) shape, without invalidating any experiment's already-computed intensities.

**Architecture:** A new Qt-free `roi_geometry.py` defines the canonical 5-value geometry per kind (`[.., angle]`), migrates the legacy 3/4-value forms, and produces the polygons for a rotated box and a capsule. `roi_compute.roi_masks` and the store's loaders call it, so worker processes and persisted stats agree. On the canvas each item sets `setTransformOriginPoint(centre)` + `setRotation(angle)`, which keeps every grip and resize computation in unrotated local coordinates.

**Tech Stack:** numpy, OpenCV (`cv2.ellipse`, `fillPoly`, `polylines`), PySide6 QGraphicsScene items, Traits/TraitsUI.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-roi-shape-rotation-ellipse-capsule-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- Angles are **degrees clockwise** everywhere (cv2 and Qt agree in y-down image coordinates). Never convert signs.
- Canonical geometry is always 5 floats: `ellipse [cx, cy, rx, ry, angle]`, `box [x, y, w, h, angle]`, `capsule [cx, cy, half_length, radius, angle]`.
- f-strings everywhere; module-level imports; constants in `analysis/consts.py`; no aliasing of constants; conventional commits.
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/<file> -q"`.
- Known pre-existing failures, not yours: `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults`, `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions`.
- Never launch the GUI (the user tests manually). Never push.

---

### Task 1: Canonical geometry module

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_geometry.py`
- Test: `fluorescence_controls_ui/tests/test_roi_geometry.py`

**Interfaces:**
- Produces: `normalize(kind, geometry) -> (str, list[float])`, `centre_of(kind, geometry) -> (float, float)`, `box_polygon(geometry) -> ndarray (4, 2)`, `capsule_polygon(geometry, samples=32) -> ndarray (N, 2)`, `GEOMETRY_LENGTH = 5`. Every later task imports from here.

- [ ] **Step 1: Write the failing tests** — create `fluorescence_controls_ui/tests/test_roi_geometry.py`:

```python
"""Unit tests for the canonical ROI geometry helpers."""

import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_geometry import (
    box_polygon,
    capsule_polygon,
    centre_of,
    normalize,
)


def test_normalize_upgrades_a_legacy_circle():
    kind, geometry = normalize("circle", [10.0, 20.0, 5.0])
    assert kind == "ellipse"
    assert geometry == [10.0, 20.0, 5.0, 5.0, 0.0]


def test_normalize_upgrades_a_legacy_box():
    kind, geometry = normalize("box", [1.0, 2.0, 30.0, 40.0])
    assert kind == "box"
    assert geometry == [1.0, 2.0, 30.0, 40.0, 0.0]


def test_normalize_is_idempotent():
    once = normalize("circle", [10.0, 20.0, 5.0])
    assert normalize(*once) == once


def test_centre_of_box_is_its_middle():
    assert centre_of("box", [0.0, 0.0, 10.0, 20.0, 0.0]) == (5.0, 10.0)
    assert centre_of("ellipse", [3.0, 4.0, 1.0, 1.0, 0.0]) == (3.0, 4.0)


def test_box_polygon_rotates_clockwise_in_image_coordinates():
    # y grows downward, so +90 degrees carries +x onto +y.
    polygon = box_polygon([0.0, 0.0, 10.0, 0.0, 90.0])
    corners = {(round(x, 6), round(y, 6)) for x, y in polygon}
    assert (5.0, -5.0) in corners
    assert (5.0, 5.0) in corners


def test_capsule_polygon_area_matches_the_analytic_value():
    half_length, radius = 20.0, 6.0
    polygon = capsule_polygon([50.0, 50.0, half_length, radius, 0.0], samples=256)
    x, y = polygon[:, 0], polygon[:, 1]
    # Shoelace formula over the closed outline.
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    expected = np.pi * radius**2 + 4.0 * radius * half_length
    assert abs(area - expected) / expected < 0.01


def test_capsule_polygon_rotation_moves_the_tip():
    flat = capsule_polygon([0.0, 0.0, 10.0, 2.0, 0.0], samples=64)
    turned = capsule_polygon([0.0, 0.0, 10.0, 2.0, 90.0], samples=64)
    assert flat[:, 0].max() > 11.0 and abs(flat[:, 1].max() - 2.0) < 0.01
    assert turned[:, 1].max() > 11.0 and abs(turned[:, 0].max() - 2.0) < 0.01
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_geometry.py -q"`
Expected: collection error — `ModuleNotFoundError: ... roi_geometry`.

- [ ] **Step 3: Write the module** — create `fluorescence_controls_ui/image_viewer/analysis/roi_geometry.py`:

```python
"""Canonical ROI geometry: what each kind's flat float list means, how
the older shorter lists migrate onto it, and the polygons cv2 and Qt
draw from it. Qt-free (numpy only) so the worker processes that compute
statistics can import it."""

import numpy as np

#: Values in every canonical geometry list:
#:   ellipse [cx, cy, rx, ry, angle]
#:   box     [x, y, width, height, angle]  (x, y = top-left corner)
#:   capsule [cx, cy, half_length, radius, angle]
#: half_length reaches the cap CENTRE, so a capsule spans
#: 2 * (half_length + radius). Angles are degrees clockwise, the
#: convention cv2.ellipse and QGraphicsItem.setRotation share in y-down
#: image coordinates.
GEOMETRY_LENGTH = 5

#: Pre-rotation kind that could only ever be a circle.
_LEGACY_KINDS = {"circle": "ellipse"}


def normalize(kind, geometry):
    """(kind, geometry) in canonical form: "circle" becomes "ellipse"
    with equal radii, a 4-value box gains its angle, and canonical
    input passes through unchanged. Never raises — a corrupt entry
    degrades to a placeable shape instead of a traceback."""
    kind = _LEGACY_KINDS.get(kind, kind)
    values = [float(value) for value in geometry]
    if kind == "ellipse" and len(values) == 3:
        values = [values[0], values[1], values[2], values[2], 0.0]
    values = (values + [0.0] * GEOMETRY_LENGTH)[:GEOMETRY_LENGTH]
    return kind, values


def centre_of(kind, geometry):
    """The (x, y) the shape rotates about — its middle, which the box
    stores only implicitly (it is anchored at its top-left corner)."""
    kind, values = normalize(kind, geometry)
    if kind == "box":
        return values[0] + values[2] / 2.0, values[1] + values[3] / 2.0
    return values[0], values[1]


def _rotated(points, centre, angle_degrees):
    """``points`` (N, 2) turned clockwise about ``centre``."""
    radians = np.radians(float(angle_degrees))
    cosine, sine = np.cos(radians), np.sin(radians)
    matrix = np.array([[cosine, -sine], [sine, cosine]])
    centre = np.asarray(centre, dtype=float)
    return (np.asarray(points, dtype=float) - centre) @ matrix.T + centre


def box_polygon(geometry):
    """The box's four rotated corners, clockwise from its top-left."""
    _, values = normalize("box", geometry)
    x, y, width, height, angle = values
    corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    return _rotated(corners, centre_of("box", values), angle)


def capsule_polygon(geometry, samples=32):
    """The stadium outline: both semicircular caps sampled with
    ``samples`` points each and joined by the flanks, in one winding."""
    _, values = normalize("capsule", geometry)
    centre_x, centre_y, half_length, radius, angle = values
    sweep = np.linspace(-np.pi / 2.0, np.pi / 2.0, samples)
    right = np.column_stack(
        [half_length + radius * np.cos(sweep), radius * np.sin(sweep)]
    )
    left = np.column_stack(
        [-half_length - radius * np.cos(sweep), -radius * np.sin(sweep)]
    )
    points = np.vstack([right, left]) + (centre_x, centre_y)
    return _rotated(points, (centre_x, centre_y), angle)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_geometry.py -q"`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_geometry.py fluorescence_controls_ui/tests/test_roi_geometry.py
git commit -m "feat(analysis): add canonical ROI geometry with an angle"
```

---

### Task 2: Rotation-aware masks

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_compute.py:16-32`
- Test: `fluorescence_controls_ui/tests/test_roi_compute.py`

**Interfaces:**
- Consumes: `normalize`, `box_polygon`, `capsule_polygon` from Task 1.
- Produces: `roi_masks(shape, kind, geometry, perimeter_px)` unchanged in signature and return contract, now accepting `ellipse`/`box`/`capsule` with an angle. `roi_batch` and the process pool need no changes.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_roi_compute.py`:

```python
def test_ellipse_mask_area_matches_pi_rx_ry():
    interior, _outline = roi_masks(
        (200, 200), "ellipse", (100.0, 100.0, 40.0, 10.0, 0.0)
    )
    expected = math.pi * 40.0 * 10.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05


def test_rotated_ellipse_swaps_its_extent():
    flat, _ = roi_masks((200, 200), "ellipse", (100.0, 100.0, 40.0, 10.0, 0.0))
    turned, _ = roi_masks((200, 200), "ellipse", (100.0, 100.0, 40.0, 10.0, 90.0))
    rows_flat, columns_flat = np.nonzero(flat)
    rows_turned, columns_turned = np.nonzero(turned)
    assert np.ptp(columns_flat) > np.ptp(rows_flat)
    assert np.ptp(rows_turned) > np.ptp(columns_turned)
    assert abs(np.count_nonzero(flat) - np.count_nonzero(turned)) < 40


def test_rotated_box_covers_its_diagonal_corners():
    interior, _outline = roi_masks((200, 200), "box", (80.0, 90.0, 40.0, 20.0, 45.0))
    # Centre stays inside; the axis-aligned corner leaves the shape.
    assert interior[100, 100] == 255
    assert interior[90, 80] == 0


def test_capsule_mask_area_matches_the_analytic_value():
    interior, _outline = roi_masks(
        (200, 200), "capsule", (100.0, 100.0, 30.0, 8.0, 0.0)
    )
    expected = math.pi * 8.0**2 + 4.0 * 8.0 * 30.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05


def test_capsule_outline_stays_inside_its_bounding_box():
    _interior, outline = roi_masks(
        (200, 200), "capsule", (100.0, 100.0, 30.0, 8.0, 0.0)
    )
    rows, columns = np.nonzero(outline)
    assert columns.min() >= 100 - 38 - 2 and columns.max() <= 100 + 38 + 2
    assert rows.min() >= 100 - 8 - 2 and rows.max() <= 100 + 8 + 2


def test_legacy_circle_geometry_still_masks():
    interior, _outline = roi_masks((100, 100), "circle", (50.0, 50.0, 10.0))
    expected = math.pi * 10.0**2
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05
```

Check the file's existing imports first: it must import `math` and `numpy as np` (add `import math` at the top if absent, keeping imports module-level and alphabetical).

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: the ellipse/box/capsule tests fail — today's `roi_masks` treats any non-`circle` kind as a rectangle and unpacks 4 values.

- [ ] **Step 3: Rewrite `roi_masks`** in `roi_compute.py`, replacing the body between the docstring and `return interior, outline`:

```python
def roi_masks(shape, kind, geometry, perimeter_px=OUTLINE_PERIMETER_PX):
    """(interior, outline) uint8 masks (255 inside) for one ROI on an
    image of ``shape`` (height, width); cv2 clips to the image bounds.
    Geometry is normalized first, so a pre-rotation config still
    computes the same pixels it always did."""
    interior = np.zeros(shape, dtype=np.uint8)
    outline = np.zeros(shape, dtype=np.uint8)
    kind, geometry = normalize(kind, geometry)
    if kind == "ellipse":
        centre_x, centre_y, radius_x, radius_y, angle = geometry
        centre = (int(round(centre_x)), int(round(centre_y)))
        axes = (int(round(radius_x)), int(round(radius_y)))
        cv2.ellipse(interior, centre, axes, angle, 0, 360, 255, -1)
        cv2.ellipse(outline, centre, axes, angle, 0, 360, 255, perimeter_px)
    else:
        polygon = box_polygon(geometry) if kind == "box" else capsule_polygon(geometry)
        points = np.round(polygon).astype(np.int32)
        cv2.fillPoly(interior, [points], 255)
        cv2.polylines(outline, [points], True, 255, perimeter_px)
    return interior, outline
```

Add the import beside the existing `from .consts import ...`:

```python
from .roi_geometry import box_polygon, capsule_polygon, normalize
```

- [ ] **Step 4: Run the whole compute test file**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: all pass, including the pre-existing circle/box tests (they go through `normalize`).

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_compute.py fluorescence_controls_ui/tests/test_roi_compute.py
git commit -m "feat(analysis): mask rotated ellipses, boxes and capsules"
```

---

### Task 3: Model kinds and migrating loaders

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py:81` (kind enum), `:205` (interaction_mode), `:221` (draw buttons)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py:60-72` (`_roi_from`), `:145-149` (`load_roi_stats` keys)
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`, plus kind updates in `test_analysis_session.py`, `test_plot_series.py`, `test_roi_model.py`, `test_roi_batch.py`

**Interfaces:**
- Consumes: `normalize` from Task 1.
- Produces: `Roi.kind = Enum("ellipse", "box", "capsule")`; `RoiAnalysisModel.interaction_mode = Enum("pan", "draw_ellipse", "draw_box", "draw_capsule", "edit")`; `RoiAnalysisModel.draw_ellipse_button` (renamed from `draw_circle_button`) and `draw_capsule_button`. Tasks 4 and 5 rely on these names.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_roi_store.py`:

```python
def test_legacy_circle_config_loads_as_a_migrated_ellipse(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_config.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plot_stat": "mean",
                "figure": {},
                "rois": [
                    {
                        "roi_id": "abcd1234",
                        "name": "ROI 1",
                        "kind": "circle",
                        "geometry": [50.0, 60.0, 10.0],
                        "base_anchor": 0.0,
                        "overrides": {"120.0": [52.0, 61.0, 11.0]},
                        "style": {},
                    }
                ],
            }
        )
    )

    (roi,) = load_session(tmp_path).rois
    assert roi.kind == "ellipse"
    assert roi.geometry == [50.0, 60.0, 10.0, 10.0, 0.0]
    assert roi.overrides == {120.0: [52.0, 61.0, 11.0, 11.0, 0.0]}


def test_legacy_stats_keys_migrate_with_their_roi(tmp_path):
    # The no-recompute guarantee: a store written before rotation must
    # still resolve against the migrated ROI's cache key.
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "roi_stats.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "path": str(tmp_path / "a_raw.png"),
                        "mtime": 123.5,
                        "roi_id": "abcd1234",
                        "kind": "circle",
                        "geometry": [50.0, 60.0, 10.0],
                        "stats": {"mean": 7.0},
                    }
                ],
            }
        )
    )
    session = AnalysisSession(
        directory=str(tmp_path),
        rois=[
            Roi(
                roi_id="abcd1234",
                name="ROI 1",
                kind="ellipse",
                geometry=[50.0, 60.0, 10.0, 10.0, 0.0],
            )
        ],
    )

    store = load_roi_stats(tmp_path)
    key = (
        str(tmp_path / "a_raw.png"),
        123.5,
        "abcd1234",
        "ellipse",
        (50.0, 60.0, 10.0, 10.0, 0.0),
    )
    assert store[key] == {"mean": 7.0}
    assert session.roi_by_id("abcd1234").kind == "ellipse"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: both fail — the loader keeps `"circle"` and the 3-value geometry.

- [ ] **Step 3: Widen the model enums** in `roi_model.py`:

```python
    kind = Enum("ellipse", "box", "capsule")
```

```python
interaction_mode = Enum("pan", "draw_ellipse", "draw_box", "draw_capsule", "edit")
```

```python
    draw_ellipse_button = Button()
    draw_box_button = Button()
    draw_capsule_button = Button()
```

Update the `kind` docstring above the trait to name all three geometries (the canonical lists from `roi_geometry`), and leave `geometry = List(Float)` alone.

- [ ] **Step 4: Migrate in the loaders** — in `roi_store.py`, replace `_roi_from` and the `load_roi_stats` dict comprehension:

```python
def _roi_from(entry):
    style = RoiStyle()
    style.trait_set(
        **{
            name: entry.get("style", {})[name]
            for name in _STYLE_FIELDS
            if name in entry.get("style", {})
        }
    )
    kind, geometry = normalize(entry["kind"], entry["geometry"])
    return Roi(
        roi_id=entry["roi_id"],
        name=entry["name"],
        kind=kind,
        geometry=geometry,
        base_anchor=float(entry["base_anchor"]),
        overrides={
            float(anchor): normalize(kind, override)[1]
            for anchor, override in entry["overrides"].items()
        },
        style=style,
    )
```

```python
return {_stats_key(entry): entry["stats"] for entry in payload["entries"]}
```

with, above `load_roi_stats`:

```python
def _stats_key(entry):
    """The cache key a stats entry answers to, migrated the same way
    the ROI it belongs to is — so intensities computed before shapes
    could rotate keep matching after."""
    kind, geometry = normalize(entry["kind"], entry["geometry"])
    return (
        entry["path"],
        float(entry["mtime"]),
        entry["roi_id"],
        kind,
        tuple(geometry),
    )
```

Import at the top: `from .roi_geometry import normalize`.

- [ ] **Step 5: Run the store tests**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: all pass. `test_load_session_accepts_v1_bare_list` and the older legacy tests now assert `"circle"` — update those assertions to `"ellipse"` and to the padded 5-value geometry; the JSON payloads they write must keep saying `"circle"`, since that is the legacy input under test.

- [ ] **Step 6: Update the other suites' ROI kinds**

In `test_analysis_session.py`, `test_plot_series.py`, `test_roi_model.py` and `test_roi_batch.py`, replace `kind="circle"` with `kind="ellipse"` and pad every geometry literal to five values (`[5.0, 5.0, 2.0]` becomes `[5.0, 5.0, 2.0, 2.0, 0.0]`), including the cache-key tuples that spell a kind out (`test_analysis_session.py:38,71`) and `test_roi_batch.py:51`'s `{"r1": ("circle", (10.0, 10.0, 4.0))}`.

- [ ] **Step 7: Update the demo generator, which constructs ROIs directly**

`examples/generate_fit_demo_experiment.py:104-107` builds `Roi(..., kind="circle", geometry=list(geometry))` from `DEMO_ROIS`, whose entries are `(cx, cy, r)` tuples also fed to `cv2.circle`. Keep the tuples as they are (the frame drawing needs three values) and canonicalize only at construction:

```python
Roi(
    roi_id=f"demo-{name}",
    name=name,
    kind="ellipse",
    geometry=[geometry[0], geometry[1], geometry[2], geometry[2], 0.0],
    base_anchor=0.0,
)
```

Run it into the scratchpad (never the user's Documents) and confirm the report still prints five ROIs with their fits intact:
`cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && PYTHONIOENCODING=utf-8 python examples/generate_fit_demo_experiment.py 'C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad'"`

- [ ] **Step 8: Run the whole controls_ui suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests -q"`
Expected: only the two known pre-existing failures.

- [ ] **Step 9: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_store.py fluorescence_controls_ui/tests examples/generate_fit_demo_experiment.py
git commit -m "feat(analysis): migrate ROI kinds to ellipse/box/capsule"
```

---

### Task 4: Rotation and resize grips on the canvas items

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_items.py:25-174` (handles, base, shape items)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py` (snap constant)

**Interfaces:**
- Consumes: `normalize`, `centre_of` from Task 1; the canonical geometries from Task 3.
- Produces: `EllipseRoiItem`, `BoxRoiItem`, `CapsuleRoiItem`, each with `set_geometry(geometry)`, `geometry() -> list[float]` (5 values), `resize_to(scene_point, uniform)`, `set_angle(degrees)`, `angle_to(scene_point)`; plus `capsule_path(geometry) -> QPainterPath` for Task 5's draft item.

- [ ] **Step 1: Add the snap constant** to `analysis/consts.py`:

```python
#: Rotation-grip snap (degrees) while Shift is held.
ROTATE_SNAP_DEGREES = 15.0
```

- [ ] **Step 2: Teach the handles about rotation** — in `roi_items.py`, extend `_ResizeHandle.mouseMoveEvent` to forward the modifier and add the new handle beside it:

```python
    def mouseMoveEvent(self, event):
        uniform = bool(event.modifiers()
                       & Qt.KeyboardModifier.ShiftModifier)
        self.parentItem().resize_to(event.scenePos(), uniform)
        event.accept()


class _RotateHandle(QGraphicsEllipseItem):
    """Round grip riding the parent ROI's top-left; dragging spins it
    about its centre. Shares the resize grip's protocol: mark the
    parent dragging so sync() leaves it alone, commit on release."""

    def __init__(self, parent):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX,
                         parent)
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self._grab_offset = 0.0

    def mousePressEvent(self, event):
        parent = self.parentItem()
        parent._dragging = True
        # Remember where on the circle it was grabbed, so the shape
        # does not jump to the cursor on the first move.
        self._grab_offset = (parent.angle_to(event.scenePos())
                             - parent.rotation())
        event.accept()

    def mouseMoveEvent(self, event):
        parent = self.parentItem()
        angle = parent.angle_to(event.scenePos()) - self._grab_offset
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            angle = (round(angle / ROTATE_SNAP_DEGREES)
                     * ROTATE_SNAP_DEGREES)
        parent.set_angle(angle)
        event.accept()

    def mouseReleaseEvent(self, event):
        parent = self.parentItem()
        parent.commit_geometry()
        parent._dragging = False
        event.accept()
```

Imports needed at the top: `QGraphicsEllipseItem` and `QGraphicsPathItem` from `PySide6.QtWidgets`, `QPainterPath` from `PySide6.QtGui`, `QRectF` from `PySide6.QtCore`, `ROTATE_SNAP_DEGREES` from `.consts`, and `centre_of, normalize` from `.roi_geometry`.

- [ ] **Step 3: Move the shared rotation behaviour into `_RoiItemBase`**

In `_setup`, after `self._handle = _ResizeHandle(self)`:

```python
        self._rotate_handle = _RotateHandle(self)
```

Extend `set_editable` and add the shared angle/resize plumbing:

```python
def set_editable(self, editable):
    self.setFlag(self.GraphicsItemFlag.ItemIsMovable, editable)
    self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, editable)
    self._handle.setVisible(editable)
    self._rotate_handle.setVisible(editable)


def angle_to(self, scene_point):
    """Degrees clockwise from the shape's centre to a scene point."""
    centre = self.mapToScene(self.transformOriginPoint())
    return math.degrees(
        math.atan2(scene_point.y() - centre.y(), scene_point.x() - centre.x())
    )


def set_angle(self, degrees):
    self.setRotation(degrees)


def resize_to(self, scene_point, uniform=False):
    # mapFromScene undoes the item's rotation, so every shape sizes
    # itself in the unrotated frame it was authored in.
    self._apply_size(self.mapFromScene(scene_point), uniform)
    self._place_attachments()


def _place_grips(self, centre_x, centre_y, half_width, half_height):
    """Resize grip at the local bottom-right, rotate grip at the
    top-left, label clear of both."""
    self._handle.setPos(centre_x + half_width, centre_y + half_height)
    self._rotate_handle.setPos(centre_x - half_width, centre_y - half_height)
    self._label.setPos(
        centre_x - half_width + HANDLE_SIZE_PX, centre_y - half_height - 2
    )
```

- [ ] **Step 4: Rewrite the shape items**

Replace `CircleRoiItem` and `BoxRoiItem`, and add the capsule:

```python
def capsule_path(geometry):
    """The stadium QPainterPath for a canonical capsule geometry, in
    unrotated local coordinates (the item transform adds the angle)."""
    _, values = normalize("capsule", geometry)
    centre_x, centre_y, half_length, radius, _angle = values
    rectangle = QRectF(
        centre_x - half_length - radius,
        centre_y - radius,
        2 * (half_length + radius),
        2 * radius,
    )
    path = QPainterPath()
    path.addRoundedRect(rectangle, radius, radius)
    return path


class EllipseRoiItem(_RoiItemBase, QGraphicsEllipseItem):
    """Ellipse ROI: geometry [cx, cy, rx, ry, angle]; a circle is
    simply rx == ry."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsEllipseItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("ellipse", geometry)
        centre_x, centre_y, radius_x, radius_y, angle = values
        self.setPos(0, 0)
        self.setRect(
            centre_x - radius_x, centre_y - radius_y, 2 * radius_x, 2 * radius_y
        )
        self.setTransformOriginPoint(centre_x, centre_y)
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        centre = rect.center() + self.pos()
        return [
            centre.x(),
            centre.y(),
            rect.width() / 2,
            rect.height() / 2,
            self.rotation(),
        ]

    def _apply_size(self, point, uniform):
        centre = self.rect().center()
        radius_x = max(abs(point.x() - centre.x()), MIN_ROI_SIZE_PX)
        radius_y = max(abs(point.y() - centre.y()), MIN_ROI_SIZE_PX)
        if uniform:
            radius_x = radius_y = max(radius_x, radius_y)
        self.setRect(
            centre.x() - radius_x, centre.y() - radius_y, 2 * radius_x, 2 * radius_y
        )

    def _place_attachments(self):
        rect = self.rect()
        self._place_grips(
            rect.center().x(), rect.center().y(), rect.width() / 2, rect.height() / 2
        )


class BoxRoiItem(_RoiItemBase, QGraphicsRectItem):
    """Box ROI: geometry [x, y, width, height, angle] with (x, y) the
    unrotated top-left corner; it rotates about its centre."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsRectItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("box", geometry)
        x, y, width, height, angle = values
        self.setPos(0, 0)
        self.setRect(x, y, width, height)
        self.setTransformOriginPoint(*centre_of("box", values))
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        return [
            rect.x() + self.pos().x(),
            rect.y() + self.pos().y(),
            rect.width(),
            rect.height(),
            self.rotation(),
        ]

    def _apply_size(self, point, uniform):
        # Centre-anchored, unlike the pre-rotation top-left anchoring:
        # a moving centre would drag the rotation pivot mid-drag.
        centre = self.rect().center()
        half_width = max(abs(point.x() - centre.x()), MIN_ROI_SIZE_PX)
        half_height = max(abs(point.y() - centre.y()), MIN_ROI_SIZE_PX)
        self.setRect(
            centre.x() - half_width,
            centre.y() - half_height,
            2 * half_width,
            2 * half_height,
        )

    def _place_attachments(self):
        rect = self.rect()
        self._place_grips(
            rect.center().x(), rect.center().y(), rect.width() / 2, rect.height() / 2
        )


class CapsuleRoiItem(_RoiItemBase, QGraphicsPathItem):
    """Capsule (spherocylinder) ROI: geometry
    [cx, cy, half_length, radius, angle]."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsPathItem.__init__(self)
        self._centre_x = 0.0
        self._centre_y = 0.0
        self._half_length = MIN_ROI_SIZE_PX
        self._radius = MIN_ROI_SIZE_PX
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("capsule", geometry)
        (self._centre_x, self._centre_y, self._half_length, self._radius, angle) = (
            values
        )
        self.setPos(0, 0)
        self.setPath(capsule_path(values))
        self.setTransformOriginPoint(self._centre_x, self._centre_y)
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        return [
            self._centre_x + self.pos().x(),
            self._centre_y + self.pos().y(),
            self._half_length,
            self._radius,
            self.rotation(),
        ]

    def _apply_size(self, point, uniform):
        # The grip rides the bounding corner, so its x distance covers
        # the cap radius as well as the straight half-length.
        self._radius = max(abs(point.y() - self._centre_y), MIN_ROI_SIZE_PX)
        self._half_length = max(
            abs(point.x() - self._centre_x) - self._radius, MIN_ROI_SIZE_PX
        )
        self.setPath(
            capsule_path(
                [self._centre_x, self._centre_y, self._half_length, self._radius, 0.0]
            )
        )

    def _place_attachments(self):
        self._place_grips(
            self._centre_x,
            self._centre_y,
            self._half_length + self._radius,
            self._radius,
        )
```

- [ ] **Step 5: Check the label under rotation and correct the spec if needed**

`ItemIgnoresTransformations` is documented to ignore *inherited* transforms, which should keep the label and grips upright while their positions still follow the rotation. Verify with the smoke script in Task 6. If the label does rotate, counter-rotate it in `_place_grips` with `self._label.setRotation(-self.rotation())`. Either way, update the spec's "Canvas" section so it states the behaviour that actually holds, in the same commit.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_items.py fluorescence_controls_ui/image_viewer/analysis/consts.py docs/superpowers/specs/2026-08-04-roi-shape-rotation-ellipse-capsule-design.md
git commit -m "feat(analysis): add a rotation grip and ellipse resizing"
```

---

### Task 5: Drawing capsules, arming the tool, toolbar button

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_items.py:176-294` (`RoiCanvasLayer`)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py:63-69`
- Modify: `fluorescence_controls_ui/image_viewer/view.py:305-320`
- Modify: `src/microdrop_style/icons/icons.py` (Microdrop submodule — add the glyph constant)

**Interfaces:**
- Consumes: the item classes and `capsule_path` from Task 4; the renamed buttons and modes from Task 3.
- Produces: canvas drawing for all three kinds; `ICON_CAPSULE` in the shared icon module.

- [ ] **Step 1: Map kinds to items and modes to kinds** — in `RoiCanvasLayer`, add module-level tables above the class:

```python
#: Canvas item per ROI kind, and the kind each draw mode creates.
ITEM_CLASSES = {"ellipse": EllipseRoiItem, "box": BoxRoiItem, "capsule": CapsuleRoiItem}
DRAW_KINDS = {"draw_ellipse": "ellipse", "draw_box": "box", "draw_capsule": "capsule"}
```

In `sync`, replace the two-way `item_class` line:

```python
            item_class = ITEM_CLASSES[kind]
```

- [ ] **Step 2: Rewrite the draft drawing** — replace `mouse_press`, `mouse_move`, `mouse_release` and `_drag_geometry`:

```python
def mouse_press(self, scene_point):
    if self.mode not in DRAW_KINDS:
        return False
    self._press_point = scene_point
    self._draft_kind = DRAW_KINDS[self.mode]
    self._draft = {
        "ellipse": QGraphicsEllipseItem,
        "box": QGraphicsRectItem,
        "capsule": QGraphicsPathItem,
    }[self._draft_kind]()
    self._draft.setPen(ROI_SELECTED_PEN)
    self._scene.addItem(self._draft)
    return True


def mouse_move(self, scene_point):
    if self._draft is None:
        return False
    geometry = self._drag_geometry(scene_point)
    if self._draft_kind == "ellipse":
        centre_x, centre_y, radius_x, radius_y, _angle = geometry
        self._draft.setRect(
            centre_x - radius_x, centre_y - radius_y, 2 * radius_x, 2 * radius_y
        )
    elif self._draft_kind == "box":
        self._draft.setRect(*geometry[:4])
    else:
        self._draft.setPath(capsule_path(geometry))
        self._draft.setTransformOriginPoint(geometry[0], geometry[1])
        self._draft.setRotation(geometry[4])
    return True


def mouse_release(self, scene_point):
    if self._draft is None:
        return False
    geometry = self._drag_geometry(scene_point)
    self._scene.removeItem(self._draft)
    self._draft = None
    if self._draft_kind == "box":
        size = min(geometry[2], geometry[3])
    elif self._draft_kind == "capsule":
        size = geometry[3]
    else:
        size = geometry[2]
    if size >= MIN_ROI_SIZE_PX:
        self.on_roi_created(self._draft_kind, geometry)
    return True


def _drag_geometry(self, scene_point):
    """Geometry of the press->current drag. Ellipse: press is the
    centre. Box: press is a corner. Capsule: press and release are
    the two cap centres, and the radius starts at a quarter of that
    axis for the grip to tune."""
    press = self._press_point
    span_x = scene_point.x() - press.x()
    span_y = scene_point.y() - press.y()
    if self._draft_kind == "ellipse":
        radius = math.hypot(span_x, span_y)
        return [press.x(), press.y(), radius, radius, 0.0]
    if self._draft_kind == "box":
        return [
            min(press.x(), scene_point.x()),
            min(press.y(), scene_point.y()),
            abs(span_x),
            abs(span_y),
            0.0,
        ]
    length = math.hypot(span_x, span_y)
    return [
        press.x() + span_x / 2,
        press.y() + span_y / 2,
        length / 2,
        max(length / 4, MIN_ROI_SIZE_PX),
        math.degrees(math.atan2(span_y, span_x)),
    ]
```

- [ ] **Step 3: Arm the new tool** — in `roi_controller.py`, rename the ellipse observer and add the capsule one:

```python
@observe("analysis_model:draw_ellipse_button")
def _arm_draw_ellipse(self, event):
    self.analysis_model.interaction_mode = "draw_ellipse"


@observe("analysis_model:draw_box_button")
def _arm_draw_box(self, event):
    self.analysis_model.interaction_mode = "draw_box"


@observe("analysis_model:draw_capsule_button")
def _arm_draw_capsule(self, event):
    self.analysis_model.interaction_mode = "draw_capsule"
```

- [ ] **Step 4: Add the icon and the toolbar button**

In the Microdrop submodule's `src/microdrop_style/icons/icons.py`, beside `ICON_CIRCLE`/`ICON_RECTANGLE`:

```python
ICON_CAPSULE = "pill"  # draw capsule (spherocylinder) ROI
```

In `image_viewer/view.py`, rename the first button's trait and add the third, importing `ICON_CAPSULE` alongside the existing icon imports:

```python
(
    UItem(
        "object.roi_analysis.draw_ellipse_button",
        editor=IconButtonEditor(
            glyph=ICON_CIRCLE,
            tooltip="Draw an elliptical ROI (click-drag from its "
            "centre; the grip makes it an ellipse)",
        ),
    ),
)
(
    UItem(
        "object.roi_analysis.draw_box_button",
        editor=IconButtonEditor(
            glyph=ICON_RECTANGLE,
            tooltip="Draw a rectangular ROI (click-drag on the image)",
        ),
    ),
)
(
    UItem(
        "object.roi_analysis.draw_capsule_button",
        editor=IconButtonEditor(
            glyph=ICON_CAPSULE,
            tooltip="Draw a capsule ROI (click-drag its axis, then "
            "use the grip for its radius)",
        ),
    ),
)
```

and extend the Edit toggle's tooltip to "Edit ROIs: drag to move, bottom-right grip to resize, top-left grip to rotate, click to select. Editing on a later image adds a drift override from there on".

- [ ] **Step 5: Check nothing else references the old names**

Run: `cd microdrop-py/src/fluorescence-microdrop-plugin-py && grep -rn "draw_circle\|CircleRoiItem" --include=*.py .`
Expected: no hits. Fix any that appear.

- [ ] **Step 6: Run the full plugin suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui fluorescence_controller fluorescence_protocol_controls -q"`
Expected: only the four known pre-existing failures (two in `fluorescence_controls_ui`, two in `test_command_setter`).

- [ ] **Step 7: Commit** (the icon lives in the submodule, so it is its own commit there)

```bash
cd microdrop-py/src && git add microdrop_style/icons/icons.py && git commit -m "feat(icons): add the capsule ROI glyph"
cd fluorescence-microdrop-plugin-py && git add fluorescence_controls_ui
git commit -m "feat(analysis): draw capsule ROIs from the toolbar"
```

---

### Task 6: Offscreen verification

**Files:**
- Create (scratchpad, never committed): `C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_roi_shapes.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the smoke script** in the session scratchpad directory:

```python
"""Offscreen smoke for the shape items: each kind round-trips its
geometry, the grips resize and rotate, and one drag reports one edit."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QGraphicsScene

app = QApplication.instance() or QApplication([])

from fluorescence_controls_ui.image_viewer.analysis.roi_items import (
    RoiCanvasLayer,
)

edits = []
scene = QGraphicsScene()
layer = RoiCanvasLayer(scene)
layer.on_roi_edited = lambda roi_id, geometry: edits.append(
    (roi_id, [round(value, 3) for value in geometry])
)
layer.set_mode("edit")

WANTED = {
    "a": ("ellipse", [100.0, 100.0, 20.0, 20.0, 0.0]),
    "b": ("box", [10.0, 10.0, 40.0, 20.0, 30.0]),
    "c": ("capsule", [80.0, 40.0, 25.0, 6.0, 45.0]),
}
layer.sync(
    [
        (roi_id, f"ROI {roi_id}", kind, list(geometry))
        for roi_id, (kind, geometry) in WANTED.items()
    ],
    "",
)
for roi_id, item in layer._items.items():
    kind, geometry = WANTED[roi_id]
    read_back = [round(value, 6) for value in item.geometry()]
    assert read_back == geometry, f"{roi_id}: {read_back} != {geometry}"
    print(f"{roi_id}: {type(item).__name__} {read_back}")
    print(f"   label rotation: {item._label.rotation()}, item angle: {item.rotation()}")

ellipse = layer._items["a"]
ellipse.resize_to(QPointF(140.0, 110.0), False)
print(f"free resize -> {ellipse.geometry()}")
assert ellipse.geometry()[2] != ellipse.geometry()[3]
ellipse.resize_to(QPointF(140.0, 110.0), True)
print(f"shift resize -> {ellipse.geometry()}")
assert ellipse.geometry()[2] == ellipse.geometry()[3]

ellipse.set_angle(ellipse.angle_to(QPointF(100.0, 140.0)))
print(f"rotated to {ellipse.geometry()[4]} degrees")
assert abs(ellipse.geometry()[4] - 90.0) < 1e-6
ellipse.commit_geometry()
assert len(edits) == 1, edits
print(f"committed: {edits}")
print("smoke passed")
```

- [ ] **Step 2: Run it**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python <scratchpad>/smoke_roi_shapes.py"`
Expected: "smoke passed", each item printing a 5-value geometry, and the label's rotation reported (0 means Qt keeps it upright and Task 4 Step 5 needs no counter-rotation).

- [ ] **Step 3: Report to the user**

Summarize: the three kinds, what the two grips do, that old experiments keep their computed intensities, the demo command they can re-run, and the fact that nothing is pushed. Then stop — the contour/polygon ROI is the next cycle and needs its own spec.
