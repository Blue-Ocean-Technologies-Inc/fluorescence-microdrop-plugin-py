# Contour ROIs — Design

Date: 2026-08-04
Branch: `feat/roi-intensity-analysis` (stacks on the rotated-shape work)
Status: approved (polygon nodes: place, close, drag; closing by first
node / double-click / Enter, Escape cancels, Backspace undoes; node
handles only on the selected contour; rotation baked into the points)

## Problem

Every ROI is still a parametric shape. A cell, a droplet trail or an
etched channel that follows no ellipse or capsule can only be covered
by a shape that also swallows background, which biases every statistic
computed from it. Users want to trace the feature itself.

## Scope

A `polygon` kind drawn by placing anchor nodes and closing the loop,
with its nodes draggable afterwards. Inserting or deleting nodes on a
finished contour, freehand drag-tracing, and Bézier handles are out.

## Design

### `analysis/roi_geometry.py`

A fourth kind whose geometry is a flat vertex list, `[x1, y1, x2, y2,
…]`, with no trailing angle: rotation is baked into the coordinates,
so a contour has nothing to normalize against a fixed length.

- `normalize` gains an early return for `"polygon"`: the values pass
  through with a stray odd value dropped, never padded to
  `GEOMETRY_LENGTH`. Still idempotent, still never raises.
- `centre_of("polygon", …)` is the mean vertex — the rotation pivot.
- New `outline_of(kind, geometry) -> ndarray (N, 2)` returns the
  polygon cv2 fills for a box, capsule or contour, replacing the
  `box_polygon`/`capsule_polygon` pair at the mask call site (both
  stay, as `outline_of` and the Qt items still use them). A polygon
  with fewer than `MIN_POLYGON_POINTS` vertices returns an empty
  array.

### `analysis/roi_compute.py`

`roi_masks` keeps its `(interior, outline)` contract and its exact
special case for unrotated circles. Its non-ellipse branch collapses to
one `outline_of` call, and draws nothing when that array is empty, so a
half-formed contour degrades to zero-count NaN statistics rather than a
traceback in a worker process.

### `analysis/roi_model.py` and `consts.py`

`Roi.kind` gains `"polygon"`; `interaction_mode` gains
`"draw_polygon"`; the model gains `draw_polygon_button`. Two constants
join `analysis/consts.py`:

```python
#: Fewest vertices a contour ROI can close on.
MIN_POLYGON_POINTS = 3

#: How near (image px) a click must land on a contour's first node to
#: close it while drawing.
POLYGON_CLOSE_DISTANCE_PX = 8.0
```

### Module split

`roi_items.py` is 458 lines and this cycle would push it past 600, so
it becomes three files, each answering one question:

- `roi_handles.py` — `_ResizeHandle`, `_RotateHandle` and the new
  `_NodeHandle`: one family sharing one press/drag/commit protocol.
- `roi_items.py` — `_RoiItemBase` and the four shape items.
- `roi_canvas_layer.py` — `RoiCanvasLayer`: scene ownership, the
  kind→item table, and the drawing state machine, which is where this
  cycle's branching lands.

`view.py` is the only importer of `RoiCanvasLayer`, so the churn is one
import line. No behaviour moves with the code.

### `PolygonRoiItem`

A `QGraphicsPolygonItem` holding one `_NodeHandle` per vertex.

- `set_geometry` builds the `QPolygonF`, pins `pos` to (0, 0), sets the
  transform origin to the centroid and the rotation to 0 — a stored
  contour is always already in its final orientation.
- `geometry()` maps every vertex through the item transform, so a move
  or a live rotation lands in the coordinates it returns. Committing a
  rotation therefore writes rotated points, and the `sync()` that
  follows re-seats the item at rotation 0 without any visible jump.
- `set_selected_style` also toggles the node handles: they show only
  when the contour is both selected and editable, which keeps a
  40-node trace from burying its neighbours in grips.
- Dragging a `_NodeHandle` rewrites its vertex live and commits on
  release, through the same `_dragging` guard the other grips use — so
  `sync()` skips the shape mid-drag and one drag still produces one
  drift override.
- The inherited resize grip stays hidden for contours; hidden Qt items
  receive no mouse events, so it cannot be grabbed by accident.

### Drawing

`RoiCanvasLayer` gains a `draw_polygon` mode holding the draft's
vertices and a `QGraphicsPathItem` preview:

- A click appends a vertex. With at least `MIN_POLYGON_POINTS` down, a
  click within `POLYGON_CLOSE_DISTANCE_PX` of the first vertex closes
  the contour instead.
- Moving rubber-bands the preview from the last vertex to the cursor.
- `mouse_release` is swallowed while drafting, so a click never also
  pans the view.
- New `mouse_double_click(scene_point)` closes on the vertices placed.
- New `key_press(key)`: Enter closes, Escape discards the draft,
  Backspace removes the last vertex (and the draft with the first).
- `set_mode` and `clear_items` discard any draft, so switching tools or
  experiments mid-trace cannot strand a preview on the scene.

All of these return True only when they acted, so unhandled events keep
falling through to the view.

### `image_viewer/view.py`

`_ImageView` gains `mouseDoubleClickEvent` and `keyPressEvent`, each
forwarding a scene point or key to the layer and calling `super()` when
the layer did not handle it, plus `setFocusPolicy(StrongFocus)` so the
canvas receives keys once clicked. A fifth toolbar button arms the tool
with the bundled `pentagon` glyph (verified present in the Material
Symbols font), tooltip "Draw a contour ROI (click to place nodes;
close on the first node, double-click, or Enter — Esc cancels,
Backspace undoes)". The Edit tooltip gains "drag a node to reshape a
contour".

## Error handling

A draft below `MIN_POLYGON_POINTS` never becomes an ROI: closing
gestures ignore it, and Escape or Backspace past the first node simply
discards it. Contours with too few vertices mask as empty rather than
raising. Node drags clamp to nothing — a contour may be any shape,
including self-intersecting, which `fillPoly` renders by its even-odd
rule and which the user can see and fix.

## Testing

Qt-free tests:

- `tests/test_roi_geometry.py`: a polygon normalizes unchanged, keeps
  its length rather than padding to five, drops a stray odd value;
  `centre_of` returns the mean vertex; `outline_of` answers for all
  three polygon-shaped kinds and returns empty below the minimum.
- `tests/test_roi_compute.py`: a right-triangle contour's mask area is
  within a few percent of `½·base·height`, its outline is closed, and
  a two-point contour yields an empty mask with NaN statistics.
- `tests/test_roi_store.py`: a contour round-trips its variable-length
  geometry and its overrides.

The drawing state machine is Qt-bound and this repo has no Qt test
harness, so it gets the offscreen smoke script the last two cycles
used (scratchpad, not committed): place nodes; close by first node, by
double-click and by Enter; cancel with Escape; undo with Backspace;
drag a node; rotate; and confirm exactly one edit per gesture and one
creation per close.

## Out of scope

- Inserting or deleting nodes on a finished contour.
- Freehand drag-tracing with simplification, and Bézier handles.
- Snapping nodes to image features or to other ROIs.
- Scaling a contour as a whole (the resize grip stays hidden).
