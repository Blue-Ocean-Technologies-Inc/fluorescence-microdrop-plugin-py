# Contour ROIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trace an ROI as a closed contour: click to place anchor nodes, close the loop, then drag the nodes to refine it.

**Architecture:** A `polygon` kind whose geometry is a flat vertex list with no angle — rotation is baked into the coordinates. `roi_geometry` gains the pass-through normalization and one `outline_of` that answers for every polygon-shaped kind; `roi_compute` collapses to that single call. On the canvas, `roi_items.py` splits into handles / items / layer, a `PolygonRoiItem` carries one node grip per vertex, and the layer runs the drawing state machine — which needs two new event forwards from `_ImageView`.

**Tech Stack:** numpy, OpenCV (`fillPoly`, `polylines`), PySide6 QGraphicsScene items, Traits/TraitsUI.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-contour-roi-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- Canonical geometry for the parametric kinds is 5 floats ending in degrees clockwise; a `polygon` is instead `[x1, y1, x2, y2, …]`, even-length, `MIN_POLYGON_POINTS` pairs or more, with rotation already applied.
- f-strings everywhere; module-level imports; constants in `analysis/consts.py`; no aliasing of constants; conventional commits.
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/<file> -q"` (always from `microdrop-py`, or pixi resolves the wrong manifest).
- Known pre-existing failures, not yours: `test_chain_model.py::test_model_has_single_param_set_with_old_br_defaults`, `test_image_viewer.py::test_viewer_model_navigation_wraps_and_positions`, and two in `fluorescence_controller/tests/test_command_setter.py`.
- Never launch the GUI (the user tests manually). Never push.

---

### Task 1: Polygon geometry and masks

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_geometry.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_compute.py:16-45`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Test: `fluorescence_controls_ui/tests/test_roi_geometry.py`, `fluorescence_controls_ui/tests/test_roi_compute.py`

**Interfaces:**
- Produces: `normalize("polygon", …)` passing vertex lists through; `centre_of("polygon", …)` as the mean vertex; `outline_of(kind, geometry) -> ndarray (N, 2)` for box/capsule/polygon, empty below the minimum; `MIN_POLYGON_POINTS`, `POLYGON_CLOSE_DISTANCE_PX` in `consts.py`. Tasks 2–4 import all of these.

- [ ] **Step 1: Add the constants** to `analysis/consts.py`, below `ROTATE_SNAP_DEGREES`:

```python
#: Fewest vertices a contour ROI can close on.
MIN_POLYGON_POINTS = 3

#: How near (image px) a click must land on a contour's first node to
#: close it while drawing.
POLYGON_CLOSE_DISTANCE_PX = 8.0
```

- [ ] **Step 2: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_roi_geometry.py`:

```python
def test_normalize_passes_a_contour_through():
    kind, geometry = normalize("polygon", [0.0, 0.0, 10.0, 0.0, 0.0, 8.0])
    assert kind == "polygon"
    assert geometry == [0.0, 0.0, 10.0, 0.0, 0.0, 8.0]


def test_normalize_drops_a_contours_stray_value():
    _kind, geometry = normalize("polygon", [0.0, 0.0, 10.0, 0.0, 5.0])
    assert geometry == [0.0, 0.0, 10.0, 0.0]


def test_centre_of_contour_is_its_mean_vertex():
    centre = centre_of("polygon", [0.0, 0.0, 10.0, 0.0, 5.0, 9.0])
    assert centre == (5.0, 3.0)


def test_outline_of_answers_for_every_polygon_shaped_kind():
    box = outline_of("box", [0.0, 0.0, 10.0, 20.0, 0.0])
    capsule = outline_of("capsule", [0.0, 0.0, 10.0, 2.0, 0.0])
    contour = outline_of("polygon", [0.0, 0.0, 10.0, 0.0, 0.0, 8.0])
    assert box.shape == (4, 2)
    assert capsule.shape[1] == 2 and len(capsule) > 4
    assert contour.tolist() == [[0.0, 0.0], [10.0, 0.0], [0.0, 8.0]]


def test_outline_of_is_empty_below_the_minimum_vertices():
    assert len(outline_of("polygon", [0.0, 0.0, 10.0, 0.0])) == 0
```

Extend that file's import to `box_polygon, capsule_polygon, centre_of, normalize, outline_of`.

Append to `fluorescence_controls_ui/tests/test_roi_compute.py`:

```python
def test_contour_mask_area_matches_the_triangle():
    interior, outline = roi_masks(
        (200, 200), "polygon", (20.0, 20.0, 120.0, 20.0, 20.0, 100.0)
    )
    expected = 0.5 * 100.0 * 80.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05
    assert 0 < np.count_nonzero(outline) < np.count_nonzero(interior)


def test_contour_below_minimum_vertices_masks_nothing():
    array = np.full((50, 50), 7, dtype=np.uint16)
    interior, _outline = roi_masks((50, 50), "polygon", (10.0, 10.0, 20.0, 20.0))
    stats = masked_stats(array, interior)
    assert np.count_nonzero(interior) == 0
    assert stats["count"] == 0.0 and math.isnan(stats["mean"])
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_geometry.py fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: the geometry file errors on importing `outline_of`; the contour mask tests fail once it exists.

- [ ] **Step 4: Extend `roi_geometry.py`**

In the `GEOMETRY_LENGTH` comment block, document the new kind: `polygon [x1, y1, x2, y2, …]`, even-length, rotation already applied to the coordinates.

Add the early return at the top of `normalize`, right after the kind lookup:

```python
kind = _LEGACY_KINDS.get(kind, kind)
values = [float(value) for value in geometry]
if kind == "polygon":
    # A contour is a vertex list, so it has no fixed length to pad
    # to and no angle: rotating one rewrites its coordinates.
    return kind, values[: len(values) - len(values) % 2]
```

Extend `centre_of` before its box branch:

```python
    if kind == "polygon":
        points = np.asarray(values, dtype=float).reshape(-1, 2)
        return float(points[:, 0].mean()), float(points[:, 1].mean())
```

Add `outline_of` at the end of the module:

```python
def outline_of(kind, geometry):
    """The polygon cv2 fills and strokes for a box, capsule or
    contour, (N, 2) in image pixels. Empty for a contour with too few
    vertices — callers draw nothing rather than raising."""
    kind, values = normalize(kind, geometry)
    if kind == "box":
        return box_polygon(values)
    if kind == "capsule":
        return capsule_polygon(values)
    points = np.asarray(values, dtype=float).reshape(-1, 2)
    if len(points) < MIN_POLYGON_POINTS:
        return np.empty((0, 2), dtype=float)
    return points
```

with `from .consts import MIN_POLYGON_POINTS` at the top. Note `centre_of` is called on already-normalized values by `box_polygon`, so the polygon branch must sit before the box one.

- [ ] **Step 5: Collapse the mask branch** in `roi_compute.py`

Replace the `else:` body of `roi_masks` (the `box_polygon`/`capsule_polygon` choice) with:

```python
    else:
        polygon = outline_of(kind, geometry)
        if len(polygon):
            points = np.round(polygon).astype(np.int32)
            cv2.fillPoly(interior, [points], 255)
            cv2.polylines(outline, [points], True, 255, perimeter_px)
```

and change its import to `from .roi_geometry import normalize, outline_of`.

- [ ] **Step 6: Run both test files and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_geometry.py fluorescence_controls_ui/tests/test_roi_compute.py -q"`
Expected: all pass (12 geometry, 14 compute).

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_geometry.py fluorescence_controls_ui/image_viewer/analysis/roi_compute.py fluorescence_controls_ui/image_viewer/analysis/consts.py fluorescence_controls_ui/tests/test_roi_geometry.py fluorescence_controls_ui/tests/test_roi_compute.py
git commit -m "feat(analysis): mask contour ROIs from a vertex list"
```

---

### Task 2: The contour kind through model and store

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py` (kind enum, `interaction_mode`, buttons)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (arm the tool)
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Consumes: Task 1's constants.
- Produces: `Roi.kind = Enum("ellipse", "box", "capsule", "polygon")`; `interaction_mode` including `"draw_polygon"`; `RoiAnalysisModel.draw_polygon_button`; `RoiAnalysisController._arm_draw_polygon`. Tasks 3–4 rely on these names.

- [ ] **Step 1: Write the failing test** — append to `fluorescence_controls_ui/tests/test_roi_store.py`:

```python
def test_contour_round_trips_its_vertex_list(tmp_path):
    roi = Roi(
        name="Cell edge",
        kind="polygon",
        geometry=[10.0, 10.0, 40.0, 12.0, 35.0, 50.0, 8.0, 44.0],
        base_anchor=0.0,
        overrides={90.0: [11.0, 11.0, 41.0, 13.0, 36.0, 51.0, 9.0, 45.0]},
    )
    save_session(tmp_path, AnalysisSession(directory=str(tmp_path), rois=[roi]))

    (back,) = load_session(tmp_path).rois
    assert back.kind == "polygon"
    assert back.geometry == roi.geometry
    assert back.overrides == roi.overrides
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: `TraitError: The 'kind' trait of a Roi instance must be 'ellipse', 'box' or 'capsule'`.

- [ ] **Step 3: Widen the model** in `roi_model.py`

```python
    kind = Enum("ellipse", "box", "capsule", "polygon")
```

extending the trait's comment with `polygon [x1, y1, x2, y2, ...]` (a vertex list with rotation already applied), and:

```python
interaction_mode = Enum(
    "pan", "draw_ellipse", "draw_box", "draw_capsule", "draw_polygon", "edit"
)
```

```python
    draw_capsule_button = Button()
    draw_polygon_button = Button()
```

- [ ] **Step 4: Arm the tool** — in `roi_controller.py`, beside `_arm_draw_capsule`:

```python
    @observe("analysis_model:draw_polygon_button")
    def _arm_draw_polygon(self, event):
        self.analysis_model.interaction_mode = "draw_polygon"
```

- [ ] **Step 5: Run the store tests and watch them pass**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests/test_roi_store.py -q"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_model.py fluorescence_controls_ui/image_viewer/analysis/roi_controller.py fluorescence_controls_ui/tests/test_roi_store.py
git commit -m "feat(analysis): add the polygon ROI kind and its tool mode"
```

---

### Task 3: Split roi_items.py three ways

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_handles.py`
- Create: `fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_items.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (one import line)

**Interfaces:**
- Produces: `roi_handles.ResizeHandle`, `roi_handles.RotateHandle` (renamed from the underscore-private names, since they now cross a module boundary); `roi_items` keeps `_RoiItemBase`, `EllipseRoiItem`, `BoxRoiItem`, `CapsuleRoiItem`, `capsule_path`; `roi_canvas_layer.RoiCanvasLayer`, `ITEM_CLASSES`, `DRAW_KINDS`.

This task moves code only. No behaviour changes, so the whole suite is the test.

- [ ] **Step 1: Create `roi_handles.py`** with the module docstring, the pen/brush constants the handles need, and the two handle classes moved verbatim except for the rename:

```python
"""Drag grips shared by the ROI canvas items: resize, rotate and
contour-node. Each marks its parent dragging on press so the layer's
sync() leaves the shape alone, edits it on move, and commits one edit
on release."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem

from .consts import ROTATE_SNAP_DEGREES

#: Cosmetic (zoom-independent 1px) pens; cyan reads on dark raws.
ROI_PEN = QPen(QColor(0, 229, 255), 0)
ROI_SELECTED_PEN = QPen(QColor(255, 214, 0), 0)
HANDLE_BRUSH = QBrush(QColor(255, 214, 0))
HANDLE_SIZE_PX = 9.0
```

Then move `_ResizeHandle` and `_RotateHandle` in unchanged, renamed to `ResizeHandle` and `RotateHandle`.

- [ ] **Step 2: Trim `roi_items.py`** to the items: drop the handle classes and the constants that moved, and import what it still needs:

```python
from .consts import MIN_ROI_SIZE_PX
from .roi_geometry import centre_of, normalize
from .roi_handles import (
    HANDLE_SIZE_PX,
    ROI_PEN,
    ROI_SELECTED_PEN,
    ResizeHandle,
    RotateHandle,
)
```

Update `_setup` to construct `ResizeHandle(self)` / `RotateHandle(self)`. Rewrite the module docstring to describe only the item classes. `HANDLE_BRUSH` stays behind in `roi_handles` — only the grips paint with it.

- [ ] **Step 3: Create `roi_canvas_layer.py`** and move `ITEM_CLASSES`, `DRAW_KINDS` and the whole `RoiCanvasLayer` class into it verbatim, with:

```python
"""Owns the ROI items on the image scene and turns the canvas view's
forwarded mouse and key events into creation/edit/selection callbacks.
Stateless wiring around Qt items, so it stays a plain class; it never
touches the analysis model."""

import math

from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
)

from .consts import MIN_ROI_SIZE_PX
from .roi_handles import ROI_SELECTED_PEN
from .roi_items import (
    BoxRoiItem,
    CapsuleRoiItem,
    EllipseRoiItem,
    capsule_path,
)
```

- [ ] **Step 4: Point `view.py` at the new module**

Change `from .analysis.roi_items import RoiCanvasLayer` to `from .analysis.roi_canvas_layer import RoiCanvasLayer` (check the exact existing line first — it may be grouped with other analysis imports).

- [ ] **Step 5: Verify nothing else imported the moved names**

Run: `cd microdrop-py/src/fluorescence-microdrop-plugin-py && grep -rn "roi_items import\|_ResizeHandle\|_RotateHandle" --include=*.py .`
Expected: only `roi_canvas_layer.py`'s import of the item classes. Fix anything else.

- [ ] **Step 6: Run the whole controls_ui suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui/tests -q"`
Expected: only the two known pre-existing failures. A pure move must not change a single result.

- [ ] **Step 7: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_handles.py fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py fluorescence_controls_ui/image_viewer/analysis/roi_items.py fluorescence_controls_ui/image_viewer/view.py
git commit -m "refactor(analysis): split ROI handles and canvas layer out"
```

---

### Task 4: The contour item and its node grips

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_handles.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_items.py`

**Interfaces:**
- Consumes: Task 1's `normalize`/`centre_of`, Task 3's module split.
- Produces: `roi_handles.NodeHandle`; `roi_items.PolygonRoiItem` with `set_geometry`, `geometry()` (flat vertex list, transform applied), `move_node(index, scene_point)`, and node grips visible only while selected and editable. Task 5's layer maps `"polygon"` to it.

- [ ] **Step 1: Add the node grip** to `roi_handles.py`:

```python
class NodeHandle(QGraphicsRectItem):
    """Grip on one contour vertex; dragging reshapes that vertex."""

    def __init__(self, parent, index):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX, parent)
        self._index = index
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event):
        self.parentItem()._dragging = True
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem().move_node(self._index, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        parent = self.parentItem()
        parent.commit_geometry()
        parent._dragging = False
        event.accept()
```

- [ ] **Step 2: Add `PolygonRoiItem`** to `roi_items.py`, after `CapsuleRoiItem`:

```python
class PolygonRoiItem(_RoiItemBase, QGraphicsPolygonItem):
    """Contour ROI: geometry is the flat vertex list
    [x1, y1, x2, y2, ...], with any rotation already applied to the
    coordinates. One node grip per vertex, shown while selected."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsPolygonItem.__init__(self)
        self._node_handles = []
        self._selected = False
        self._editable = False
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("polygon", geometry)
        points = [
            QPointF(values[index], values[index + 1])
            for index in range(0, len(values), 2)
        ]
        self.setPos(0, 0)
        self.setRotation(0)  # a stored contour is already oriented
        self.setPolygon(QPolygonF(points))
        self.setTransformOriginPoint(*centre_of("polygon", values))
        self._rebuild_node_handles()
        self._place_attachments()

    def geometry(self):
        # Through the item transform, so a move or a live rotation
        # lands in the coordinates and never needs storing as an angle.
        return [
            value
            for point in self.polygon()
            for value in (self.mapToScene(point).x(), self.mapToScene(point).y())
        ]

    def move_node(self, index, scene_point):
        polygon = self.polygon()
        polygon[index] = self.mapFromScene(scene_point)
        self.setPolygon(polygon)
        self._node_handles[index].setPos(polygon[index])
        self._place_attachments()

    def set_editable(self, editable):
        super().set_editable(editable)
        self._editable = editable
        # Contours are shaped by their nodes, so the resize grip stays
        # hidden (a hidden item receives no mouse events).
        self._handle.setVisible(False)
        self._update_node_visibility()

    def set_selected_style(self, selected):
        super().set_selected_style(selected)
        self._selected = selected
        self._update_node_visibility()

    def _update_node_visibility(self):
        for handle in self._node_handles:
            handle.setVisible(self._selected and self._editable)

    def _rebuild_node_handles(self):
        for handle in self._node_handles:
            handle.setParentItem(None)
        self._node_handles = []
        for index, point in enumerate(self.polygon()):
            handle = NodeHandle(self, index)
            handle.setPos(point)
            self._node_handles.append(handle)
        self._update_node_visibility()

    def _apply_size(self, point, uniform):
        """No-op: the resize grip is hidden for contours."""

    def _place_attachments(self):
        bounds = self.polygon().boundingRect()
        self._place_grips(
            bounds.center().x(),
            bounds.center().y(),
            bounds.width() / 2,
            bounds.height() / 2,
        )
```

Add to the imports: `QPointF` from `PySide6.QtCore`, `QPolygonF` from `PySide6.QtGui`, `QGraphicsPolygonItem` from `PySide6.QtWidgets`, and `NodeHandle` from `.roi_handles`.

- [ ] **Step 3: Check it holds together offscreen** — a throwaway in the scratchpad:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QGraphicsScene

app = QApplication.instance() or QApplication([])
from fluorescence_controls_ui.image_viewer.analysis.roi_items import (
    PolygonRoiItem,
)

edits = []
scene = QGraphicsScene()
item = PolygonRoiItem(
    "p",
    "ROI 1",
    [0.0, 0.0, 10.0, 0.0, 0.0, 8.0],
    lambda roi_id, geometry: edits.append(geometry),
)
scene.addItem(item)
assert item.geometry() == [0.0, 0.0, 10.0, 0.0, 0.0, 8.0], item.geometry()
item.move_node(2, QPointF(1.0, 9.0))
assert item.geometry() == [0.0, 0.0, 10.0, 0.0, 1.0, 9.0], item.geometry()
item.set_angle(90.0)
turned = [round(value, 6) for value in item.geometry()]
item.commit_geometry()
assert edits == [item.geometry()] and turned != [0.0, 0.0, 10.0, 0.0, 1.0, 9.0]
print(f"rotated contour: {turned}")
print("ok")
```

Run it; expected: `ok`, with the rotated coordinates differing from the flat ones. A `TypeError` on `polygon[index] = …` means this PySide6 build's `QPolygonF` is not assignable — fall back to rebuilding it from a list of points in `move_node`.

- [ ] **Step 4: Commit**

```bash
git add fluorescence_controls_ui/image_viewer/analysis/roi_handles.py fluorescence_controls_ui/image_viewer/analysis/roi_items.py
git commit -m "feat(analysis): add the contour ROI item with node grips"
```

---

### Task 5: Drawing contours

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py`
- Modify: `fluorescence_controls_ui/image_viewer/view.py` (`_ImageView` events, toolbar button)
- Modify: `src/microdrop_style/icons/icons.py` (Microdrop submodule)

**Interfaces:**
- Consumes: `PolygonRoiItem` from Task 4, the constants from Task 1, `draw_polygon_button` from Task 2.
- Produces: `RoiCanvasLayer.mouse_double_click(scene_point)`, `RoiCanvasLayer.key_press(key)`, contour drafting inside the existing mouse handlers; `ICON_CONTOUR` in the shared icon module.

- [ ] **Step 1: Register the kind** in `roi_canvas_layer.py`:

```python
ITEM_CLASSES = {
    "ellipse": EllipseRoiItem,
    "box": BoxRoiItem,
    "capsule": CapsuleRoiItem,
    "polygon": PolygonRoiItem,
}
DRAW_KINDS = {
    "draw_ellipse": "ellipse",
    "draw_box": "box",
    "draw_capsule": "capsule",
    "draw_polygon": "polygon",
}
```

importing `PolygonRoiItem`, `QPainterPath` (from `PySide6.QtGui`), and `MIN_POLYGON_POINTS, POLYGON_CLOSE_DISTANCE_PX` from `.consts`. The draft's vertices arrive as scene points from the view, so no `QPointF` import is needed here.

In `__init__`, beside `self._draft = None`, add the draft's vertices:

```python
self._draft_points = []  # contour vertices placed so far
```

- [ ] **Step 2: Branch the mouse handlers to the contour state machine**

At the top of `mouse_press`, before the existing rubber-band start:

```python
        if self.mode == "draw_polygon":
            return self._press_contour(scene_point)
```

At the top of `mouse_move`:

```python
        if self.mode == "draw_polygon":
            if not self._draft_points:
                return False
            self._draft.setPath(self._contour_path(scene_point))
            return True
```

At the top of `mouse_release`:

```python
        if self.mode == "draw_polygon":
            # Swallow it so a click that placed a node cannot also pan.
            return bool(self._draft_points)
```

- [ ] **Step 3: Add the contour methods** to `RoiCanvasLayer`:

```python
def _press_contour(self, scene_point):
    """Place a vertex, or close the contour when the click lands
    back on its first one."""
    if self._draft_points:
        first = self._draft_points[0]
        near_first = math.hypot(
            scene_point.x() - first.x(), scene_point.y() - first.y()
        )
        if near_first <= POLYGON_CLOSE_DISTANCE_PX:
            self._close_contour()
            return True
    else:
        self._draft_kind = "polygon"
        self._draft = QGraphicsPathItem()
        self._draft.setPen(ROI_SELECTED_PEN)
        self._scene.addItem(self._draft)
    self._draft_points.append(scene_point)
    self._draft.setPath(self._contour_path(scene_point))
    return True


def _contour_path(self, cursor_point):
    """The placed vertices, rubber-banded to the cursor."""
    path = QPainterPath(self._draft_points[0])
    for point in self._draft_points[1:]:
        path.lineTo(point)
    path.lineTo(cursor_point)
    return path


def _close_contour(self):
    """Finish the draft into an ROI, if it has enough vertices."""
    points = self._draft_points
    self._discard_contour()
    if len(points) < MIN_POLYGON_POINTS:
        return
    self.on_roi_created(
        "polygon", [value for point in points for value in (point.x(), point.y())]
    )


def _discard_contour(self):
    if self._draft is not None:
        self._scene.removeItem(self._draft)
    self._draft = None
    self._draft_points = []


def mouse_double_click(self, scene_point):
    """Close the contour on the vertices already placed."""
    if self.mode != "draw_polygon" or not self._draft_points:
        return False
    self._close_contour()
    return True


def key_press(self, key):
    """Enter closes the contour, Escape discards it, Backspace
    takes back the last vertex."""
    if self.mode != "draw_polygon" or not self._draft_points:
        return False
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        self._close_contour()
    elif key == Qt.Key.Key_Escape:
        self._discard_contour()
    elif key == Qt.Key.Key_Backspace:
        self._draft_points.pop()
        if self._draft_points:
            self._draft.setPath(self._contour_path(self._draft_points[-1]))
        else:
            self._discard_contour()
    else:
        return False
    return True
```

Import `Qt` from `PySide6.QtCore`. Then make mode and experiment switches discard a draft — in `set_mode`, before the loop, and at the top of `clear_items`:

```python
        self._discard_contour()
```

- [ ] **Step 4: Forward double-clicks and keys** — in `view.py`'s `_ImageView`, after `mouseReleaseEvent`:

```python
def mouseDoubleClickEvent(self, event):
    point = self.mapToScene(event.position().toPoint())
    if self._roi_layer.mouse_double_click(point):
        event.accept()
        return
    super().mouseDoubleClickEvent(event)


def keyPressEvent(self, event):
    if self._roi_layer.key_press(event.key()):
        event.accept()
        return
    super().keyPressEvent(event)
```

and in `__init__`, beside `setMouseTracking(True)`:

```python
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
```

so a clicked canvas receives the keys.

- [ ] **Step 5: Add the icon and the button**

In the Microdrop submodule's `src/microdrop_style/icons/icons.py`, beside `ICON_CAPSULE`:

```python
ICON_CONTOUR = "pentagon"  # trace a contour (polygon) ROI
```

In `image_viewer/view.py`, after the capsule button (add `ICON_CONTOUR` to the icon import):

```python
(
    UItem(
        "object.roi_analysis.draw_polygon_button",
        editor=IconButtonEditor(
            glyph=ICON_CONTOUR,
            tooltip="Draw a contour ROI (click to place nodes; "
            "close on the first node, double-click, or "
            "Enter — Esc cancels, Backspace undoes)",
        ),
    ),
)
```

and extend the Edit toggle's tooltip with ", drag a node to reshape a contour" after the rotate-grip clause.

- [ ] **Step 6: Run every suite**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python -m pytest fluorescence_controls_ui fluorescence_controller fluorescence_protocol_controls -q"`
Expected: only the four known pre-existing failures.

- [ ] **Step 7: Commit** (the icon is in the submodule, so it commits separately)

```bash
cd microdrop-py/src && git add microdrop_style/icons/icons.py && git commit -m "feat(icons): add the contour ROI glyph"
cd fluorescence-microdrop-plugin-py && git add fluorescence_controls_ui
git commit -m "feat(analysis): draw contour ROIs by placing nodes"
```

---

### Task 6: Offscreen verification

**Files:**
- Create (scratchpad, never committed): `C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_contour_roi.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the smoke script**

```python
"""Offscreen smoke for contour drawing: every closing gesture makes
exactly one ROI, cancelling makes none, and a node drag reports one
edit."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsScene

app = QApplication.instance() or QApplication([])

from fluorescence_controls_ui.image_viewer.analysis.roi_canvas_layer import (
    RoiCanvasLayer,
)

created, edits = [], []
scene = QGraphicsScene()
layer = RoiCanvasLayer(scene)
layer.on_roi_created = lambda kind, geometry: created.append(
    (kind, [round(value, 3) for value in geometry])
)
layer.on_roi_edited = lambda roi_id, geometry: edits.append(roi_id)


def place(*points):
    layer.set_mode("draw_polygon")
    for x, y in points:
        layer.mouse_press(QPointF(x, y))
        layer.mouse_release(QPointF(x, y))


TRIANGLE = ((10.0, 10.0), (60.0, 10.0), (60.0, 50.0))

place(*TRIANGLE)  # close on the first node
layer.mouse_press(QPointF(12.0, 11.0))
assert len(created) == 1, created
assert created[0][0] == "polygon" and len(created[0][1]) == 6

place(*TRIANGLE)  # close by double-click
layer.mouse_double_click(QPointF(60.0, 50.0))
assert len(created) == 2, created

place(*TRIANGLE)  # close by Enter
layer.key_press(Qt.Key.Key_Return)
assert len(created) == 3, created

place(*TRIANGLE)  # Escape discards
layer.key_press(Qt.Key.Key_Escape)
assert len(created) == 3, created

place(*TRIANGLE)  # too few vertices to close
layer.key_press(Qt.Key.Key_Backspace)
layer.key_press(Qt.Key.Key_Return)
assert len(created) == 3, created
layer.key_press(Qt.Key.Key_Escape)
print(f"created: {created}")

layer.set_mode("edit")
layer.sync([("p", "ROI 1", "polygon", [10.0, 10.0, 60.0, 10.0, 60.0, 50.0])], "p")
item = layer._items["p"]
assert len(item._node_handles) == 3
assert all(handle.isVisible() for handle in item._node_handles)
item.move_node(1, QPointF(70.0, 12.0))
item.commit_geometry()
assert edits == ["p"], edits
assert item.geometry() == [10.0, 10.0, 70.0, 12.0, 60.0, 50.0]

layer.sync([("p", "ROI 1", "polygon", [10.0, 10.0, 70.0, 12.0, 60.0, 50.0])], "")
assert not any(handle.isVisible() for handle in item._node_handles), (
    "node grips must hide when the contour is not selected"
)
print("smoke passed")
```

- [ ] **Step 2: Run it**

Run: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && python 'C:/Users/Info/AppData/Local/Temp/claude/C--Users-Info-PycharmProjects-pixi-microdrop/0d07a70c-3ea8-4cf0-a1e8-636093cc9c4a/scratchpad/smoke_contour_roi.py'"`
Expected: "smoke passed", with three contours created from five drafts.

- [ ] **Step 3: Report to the user**

Summarize: how to trace a contour and the three ways to close it, that node grips appear on the selected contour in Edit mode, that rotation rewrites the vertices, what was split out of `roi_items.py`, and that nothing is pushed. Mention what still needs manual GUI testing: whether the 8-pixel close radius feels right at typical zoom, and whether Backspace/Escape reach the canvas when other panes have focus.
