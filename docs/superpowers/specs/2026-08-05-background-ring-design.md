# Background Ring, Fixed and Visible — Design

Date: 2026-08-05
Branch: `feat/roi-intensity-analysis`
Status: approved (gap + thickness spinners; dashed outline on every
ROI with a toggle; neighbouring ROIs excluded; canvas drawing in this
same cycle; subtract-first transform included)

## Problem

The background correction measures the wrong pixels. `roi_masks`
strokes the ROI's own boundary with a 2-pixel line and calls that the
background, but cv2 centres a stroke on its path, so roughly half the
ring lies *inside* the ROI. Measured on a 3000-on-100 synthetic disk:

```
ring pixels    : 562  ->  258 inside the ROI, 304 outside
interior mean  : 3000.0
ring mean      : 1431.3
bg_corrected   : 1568.7      (true signal over background: 2900)
```

It reads 1569 where the answer is 2900 — a 46% under-read. Worse, the
error depends on how tightly the ROI was drawn, so nothing on screen
says which case you are in.

## Scope

Make the ring a true annulus outside the ROI, with the user choosing
how far out it sits and how thick it is, drawn on the canvas so it can
be seen. Add the subtract-first transform toggle alongside. The
`outline_*` stat names stay: renaming them would churn the CSV headers
a second time in three cycles.

## Design

### The annulus — `analysis/roi_compute.py`

```python
def ring_mask(interior, gap_px, thickness_px):
    """The annulus outside ``interior``: the shape dilated by
    gap + thickness, less the shape dilated by gap."""
```

Morphological dilation with an elliptical structuring element, which
is exactly "expand by N pixels" and works identically for every kind —
including traced contours, where analytically offsetting a polygon
would need a whole clipping library. With `gap_px = 0` the inner edge
is the ROI boundary itself, so the ring can never contain interior
pixels: that alone is the bug fixed.

Both dilations run on a crop of the ROI's bounding box padded by
`gap + thickness`, so cost tracks ROI size rather than image size.

`roi_masks(shape, kind, geometry, gap_px, thickness_px)` returns
`(interior, ring)` as before — the same contract, so `roi_batch` and
the worker pool are unchanged in shape.

### Neighbours

`compute_image_stats` computes every ROI's interior first, ORs them
into one union, then clears from each ring the union less that ROI's
own interior. A droplet sitting close by can no longer masquerade as
background. One extra mask per image, not per ROI.

### Parameters and invalidation

`BackgroundRing(gap_px=2, thickness_px=4, show_on_canvas=True)` joins
the session beside `scale`, persisted per experiment, with two
spinners in the plot pane's controls.

These parameters change what is measured, so they join the stats cache
key, which becomes `(path, mtime, roi_id, kind, geometry, ring)`.
Entries written before this change carry no ring; `_stats_key` gives
them `None`, which no current key can equal, so they are ignored and
recomputed. That is the honest outcome: those numbers came from the
broken ring.

Work items become `(path, effective_rois, ring)` so the pool computes
with the session's parameters.

### Drawing it — `analysis/roi_canvas_layer.py`

`ring_contours(shape, kind, geometry, gap_px, thickness_px)` runs
`cv2.findContours` over the *same* cropped ring mask and returns the
boundaries in image coordinates, so what is drawn cannot disagree with
what is averaged. The layer draws them per ROI as a dashed
`QGraphicsPathItem` in the ROI's own colour, no fill, rebuilt on sync
(image change, ROI edit) rather than on every repaint. A toolbar
toggle over `show_on_canvas` hides them all.

### Subtract first — `analysis/plot_series.py`

`subtracted_series(series)`: each curve less its own first finite
value, NaN preserved. A fourth transform toggle beside Normalize,
applied before normalization — with both on the result equals
normalization alone, since both are affine. The y-label gains
"(change from first)".

## Error handling

An ROI whose mask is empty (fully off-image) yields an empty ring and
NaN stats, as today. A ring whose pixels are all claimed by neighbours
yields an empty mask and NaN `outline_*`, so `bg_corrected` becomes
NaN and the plot gaps — better than silently averaging nothing.
`gap_px` and `thickness_px` are `Range(0, 50)` and `Range(1, 50)`, so
the ring always has at least one pixel of width.

## Testing

- `tests/test_roi_compute.py`: the ring never overlaps the interior;
  its area matches the analytic annulus within a few percent; a gap
  pushes its inner edge out by that many pixels; a neighbouring ROI's
  interior is excluded; and **the regression that names this cycle** —
  the 3000-on-100 disk yielding `bg_corrected` ≈ 2900 where it read
  1569.
- `tests/test_roi_store.py`: `BackgroundRing` round-trips; a stats
  entry without a ring never matches a current key.
- `tests/test_analysis_session.py`: the cache key changes when either
  ring parameter changes.
- `tests/test_plot_series.py`: `subtracted_series` starting every curve
  at 0 and preserving gaps.
- Offscreen smoke: the ring contours drawn per ROI, the toggle hiding
  them, and the drawn outer extent matching `radius + gap + thickness`.

## Out of scope

- Renaming `outline_*` to `ring_*`.
- Per-ROI ring parameters (they are session-wide).
- Excluding saturated or masked-out pixels from the ring.
