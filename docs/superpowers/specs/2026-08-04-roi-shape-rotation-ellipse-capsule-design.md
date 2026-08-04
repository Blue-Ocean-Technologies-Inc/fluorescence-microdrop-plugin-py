# ROI Shapes: Rotation, Ellipses, Capsules — Design

Date: 2026-08-04
Branch: `feat/roi-intensity-analysis`
Status: approved (parametric shapes this cycle, contour ROIs next;
kind renamed to `ellipse` with load-time migration; one resize grip
with Shift for a circle)

## Problem

ROIs are axis-aligned circles and boxes. Cells, channels and droplets
are not: they sit at an angle, they are elongated, and a channel
segment is a spherocylinder rather than a rectangle. The canvas offers
one bottom-right grip that resizes uniformly, so the only way to cover
a tilted feature today is an oversized box that drags background into
the statistics.

## Scope

This cycle: a rotation grip, ellipses (independent radii), and a
capsule/spherocylinder shape. Custom contour ROIs (vector tracing with
anchor nodes) are a separate cycle; this design leaves the geometry
model ready for them but adds none of that interaction.

## Design

### `analysis/roi_geometry.py` (new, Qt-free)

Single source of truth for what a geometry list means, imported by the
worker-safe compute path, the store, and the Qt items.

| kind | geometry | notes |
| --- | --- | --- |
| `ellipse` | `[cx, cy, rx, ry, angle]` | replaces `circle`; a circle is `rx == ry` |
| `box` | `[x, y, w, h, angle]` | top-left anchored as today, rotates about its centre |
| `capsule` | `[cx, cy, half_length, radius, angle]` | `half_length` reaches the cap centre; total extent `2*(half_length + radius)` |

`angle` is degrees clockwise, the convention both `cv2.ellipse` and
`QGraphicsItem.setRotation` already use in y-down image coordinates, so
no sign conversion exists anywhere in the stack.

- `normalize(kind, geometry) -> (kind, geometry)` — maps kind
  `"circle"` to `"ellipse"`, pads a 3-value circle to
  `[cx, cy, r, r, 0.0]` and a 4-value box to `[x, y, w, h, 0.0]`, and
  passes canonical input through unchanged. Idempotent.
- `capsule_polygon(geometry, samples=32) -> ndarray (N, 2)` — the
  stadium outline: both semicircular caps sampled and joined by the
  two flanks, rotated by `angle` about the centre. The contour cycle
  reuses the same fill/stroke path.
- `box_polygon(geometry) -> ndarray (4, 2)` — the rotated corners.
- `centre_of(kind, geometry)` — the rotation pivot, shared by the Qt
  items and the polygon helpers.

### `analysis/roi_compute.py`

`roi_masks(shape, kind, geometry, perimeter_px)` keeps its exact
`(interior, outline)` uint8 contract, so `roi_batch`, the process pool
and the drift-override plumbing are untouched. It normalizes its input
first (defence for any stale caller), then:

- `ellipse` — `cv2.ellipse(mask, centre, (rx, ry), angle, 0, 360, 255,
  -1)` for the interior and the same call with `perimeter_px` for the
  ring; cv2 supports the rotation natively, so this stays exact.
- `box` — `cv2.fillPoly` / `cv2.polylines(closed=True)` over
  `box_polygon`.
- `capsule` — the same two calls over `capsule_polygon`.

### `analysis/roi_model.py`

`Roi.kind = Enum("ellipse", "box", "capsule")`.
`RoiAnalysisModel.interaction_mode` gains `"draw_capsule"`, and the
model gains a `draw_capsule_button`. Nothing else moves: the geometry
stays a flat `List(Float)`, so drift overrides, cache keys and the CSV
export are unaffected by shape or angle beyond carrying more numbers.

### `analysis/roi_store.py`

`load_session` normalizes the base geometry **and every drift
override** of every ROI. `load_roi_stats` normalizes the `kind` and
`geometry` inside its cache keys the identical way. Because both sides
migrate through the same function, stats computed before this change
still match their ROI after it — an existing experiment reopens with
its intensities intact and needs no recalculation. Saving always
writes canonical 5-value geometry; no version bump is needed since the
tolerated-missing/migrating loader defines the compatibility.

### `analysis/roi_items.py`

A `_ParametricRoiItem` mixin (extending today's `_RoiItemBase`) owns
the shared behaviour:

- `setTransformOriginPoint(centre)` + `setRotation(angle)`. Qt applies
  the rotation, so grips and resize math stay in **unrotated local
  coordinates** and the existing per-shape code barely changes.
- The bottom-right `_ResizeHandle` maps its dragged local position to
  the shape's two size parameters: `(rx, ry)` for the ellipse,
  `(half_w, half_h)` for the box, `(half_length, radius)` for the
  capsule. Holding Shift keeps an ellipse circular (`rx == ry`).
- A new top-left `_RotateHandle`, a round grip in the handle colour.
  Its drag sets `angle` from `atan2(cursor - centre)` minus the offset
  at grab time, so the shape does not jump when grabbed; Shift snaps to
  15°. It shares `_ResizeHandle`'s press/commit protocol (set the
  parent's `_dragging`, commit on release), so `sync()` keeps skipping
  a shape mid-drag and one edit still produces one drift override.
- Both grips and the name label are children of a rotated item and so
  inherit its rotation. That is wanted for the grips; the label is
  counter-rotated by `-angle` to stay upright.

`CircleRoiItem` becomes `EllipseRoiItem`; `CapsuleRoiItem` is a
`QGraphicsPathItem` whose path is the stadium (two arcs plus flanks).
`RoiCanvasLayer` maps the three kinds to their item classes, and its
draw modes gain `"draw_capsule"`: the press-to-release drag defines the
capsule's axis (press = one cap centre, release = the other), the
radius starts at a quarter of that length (floor `MIN_ROI_SIZE_PX`),
and the grip tunes both afterwards. Ellipse drawing is unchanged —
drag from the centre creates `rx == ry`, and it becomes an ellipse when
the grip is dragged.

### `image_viewer/view.py`

A fourth draw button in `analysis_toolbar` using the bundled Material
Symbols `pill` ligature (verified present in the font), tooltip "Draw a
capsule ROI (drag the axis, then use the grip)". The Edit toggle's
tooltip gains the rotation grip.

## Error handling

`normalize` never raises on a short or over-long geometry: it pads with
zeros and truncates to the canonical length, so a corrupt config
degrades to a placeable shape rather than a traceback. Radii and side
lengths are clamped to `MIN_ROI_SIZE_PX` during drags. Masks for shapes
partly outside the image keep relying on cv2's clipping, unchanged.

## Testing

Qt-free tests only, matching the existing suite:

- `tests/test_roi_geometry.py` (new): `normalize` migration of the
  legacy circle/box forms and its idempotence; `capsule_polygon` area
  against the analytic `πr² + 2·r·(2·half_length)` within ~1%; polygon
  rotation moving the expected extreme point.
- `tests/test_roi_compute.py`: a rotated box mask covering the pixels
  its rotated corners imply and not the axis-aligned ones; an ellipse
  mask area ≈ `π·rx·ry`; a capsule mask area ≈ its analytic area; the
  outline ring staying strictly inside the shape's bounding box.
- `tests/test_roi_store.py`: a v2 config holding a `circle` ROI with an
  override loads as an `ellipse` with 5-value geometry everywhere, and
  a stats store written against the old key still resolves for the
  migrated ROI (the no-recompute guarantee).
- Offscreen smoke script (scratchpad, not committed): create each kind,
  drag the resize and rotate grips, confirm one commit per drag and the
  geometry round-trips through the model.

## Out of scope

- Contour/polygon ROIs (next cycle).
- Numeric entry of angle/radii, snapping ROIs to image features,
  per-ROI mask preview, and rotating the underlying image.
- Reporting the angle in the CSV export or the stats table.
