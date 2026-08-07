# Image Scale Bar — Design

Date: 2026-08-04
Branch: `feat/roi-intensity-analysis`
Status: approved (calibration per experiment, seeded from the last
one; map-style bar that snaps to a round value; units m, cm, mm, µm,
nm with mm the default)

## Problem

Nothing on the image says how big anything is. A user reading a
fluorescence field has no way to judge a droplet's size, and no way to
communicate it in an exported figure. Microscopes give no usable pixel
size either, since it depends on the objective, the camera and any
digital zoom in play.

## Scope

Calibrate by drawing a line of known length, then show a map-style
scale bar over the image. Reporting ROI areas or lengths in real units
is a natural follow-on but touches the stats table, the CSV and the
plots, so it stays out of this cycle.

## Design

### `image_viewer/scale_bar.py` (new, Qt-free)

The whole of the maths, so the snapping ladder is unit-tested without a
canvas. It owns its own tunables rather than reaching into the
analysis subpackage's `consts.py`, which belongs to a different
concern.

```python
#: Dropdown order (largest first) and each unit's size in metres.
UNITS = ("m", "cm", "mm", "µm", "nm")
UNIT_METRES = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "µm": 1e-6, "nm": 1e-9}
DEFAULT_UNIT = "mm"

#: About how wide the drawn bar should be, in screen pixels, before
#: its length is snapped down to a round number.
SCALE_BAR_TARGET_PX = 120.0

#: Shorter calibration drags are treated as a misclick, not a line.
MIN_SCALE_LINE_PX = 5.0
```

- `metres_per_pixel(line_px, value, unit) -> float | None` — the
  calibration a drawn line implies. None for a line under
  `MIN_SCALE_LINE_PX` or a value that is not positive, so a misclick
  or an empty form cannot poison the calibration.
- `nice_scale(metres_per_screen_px, target_px=SCALE_BAR_TARGET_PX) ->
  (float, str) | None` — the bar to draw: the length spanning about
  `target_px`, snapped **down** to the nearest 1/2/5 × 10ⁿ metres, as
  `(bar_px, label)`. None when the calibration is absent or
  non-finite.
- `format_length(length_m) -> str` — the label, in the largest unit
  that still renders the number at or above 1: 0.0005 m becomes
  "500 µm", 40 m stays "40 m". Values below a nanometre clamp to nm
  rather than reading "0 nm".

Because the caller passes metres per **screen** pixel, zoom is already
folded in: the label walks 2 mm → 1 mm → 500 µm → 200 µm as the view
zooms, and never shows "0.0004 m".

### Calibration state and persistence

`ScaleCalibration` joins `RoiStyle` and `FigureSettings` in
`analysis/roi_model.py`, as another slice of per-experiment session
state:

```python
class ScaleCalibration(HasTraits):
    """Image scale for the on-canvas bar (persisted per experiment)."""

    #: Metres one image pixel spans; 0.0 means not calibrated.
    metres_per_pixel = Float(0.0)
    #: What the user typed, kept for the readout and for re-editing.
    value = Float(0.0)
    unit = Enum(DEFAULT_UNIT, UNITS)
    show_bar = Bool(True)
```

`AnalysisSession` gains `scale = Instance(ScaleCalibration, ())`, and
`roi_store` persists its four fields under a `scale` key with the same
tolerated-missing loading the figure settings use, so older configs
open uncalibrated instead of failing.

Reusing `roi_config.json` rather than adding a second per-experiment
file is deliberate: the session already swaps on experiment change,
debounces its writes, and survives missing keys — a new store would
duplicate all of that for four numbers.

Per the approved seeding, `FluorescencePreferences` gains
`fluorescence_last_scale_metres_per_px` (Float) and
`fluorescence_last_scale_unit` (Str). Two rules connect them:

- Completing a calibration writes both preference fields.
- `RoiAnalysisController._on_experiment_changed`, right after
  `load_session`, seeds an uncalibrated session from those preferences
  **and saves it into that experiment's config immediately**. The
  experiment's record then states what it was measured with, instead
  of drifting later with whatever was calibrated elsewhere.

### Drawing the line — `image_viewer/scale_layer.py` (new)

`ScaleCanvasLayer` is its own layer beside `RoiCanvasLayer`, not a
mode inside it: the ROI layer already owns creation, editing,
selection and the contour state machine, and a calibration line is
none of those. It holds only a draft `QGraphicsLineItem` and the
`on_line_drawn(length_px)` callback.

`_ImageView` offers each mouse event to the scale layer first and
falls through to the ROI layer, the handled-or-`super()` contract
already in place. In `draw_scale` mode a press-drag-release
rubber-bands the line; on release the layer reports
`math.hypot(dx, dy)` in image pixels and clears its draft. The line is
not kept: once its length becomes a calibration, the number is the
artefact, and recalibrating means drawing again.

### Entering the value

A `ScaleEntry(HasTraits)` with `value = Float` and `unit = Enum` opened
through `edit_traits(kind="livemodal")` from the canvas editor's
`on_line_drawn` handler, seeded with the session's current unit.
`microdrop_application.dialogs.pyface_wrapper` is not used here because
it covers message dialogs — confirm, choose, information, error — and
offers nothing for a two-field form. Cancelling, or an entry that
`metres_per_pixel` rejects, leaves the existing calibration untouched.

### Drawing the bar

`_ImageView.drawForeground(painter, rect)` paints it, the standard
QGraphicsView hook for a HUD: the painter's transform is reset so the
bar is laid out in viewport pixels, and the metres one **screen** pixel
spans is `metres_per_pixel / transform().m11()` — m11 being screen
pixels per image pixel, so zooming in shrinks it. Feeding that to
`nice_scale` re-labels the bar on every repaint, with nothing to
observe and no state to invalidate.

It sits at the bottom-left over a translucent dark plate, drawn as a
white bar with end caps and its label centred above — legible on a
bright field and on a dark raw alike. Nothing is added to the scene,
so the bar cannot be selected, dragged, or picked up by anything that
walks the scene's items.

The canvas editor observes `session:scale:metres_per_pixel` and
`session:scale:show_bar` (plus the session swap) and pushes the pair
into the view with `set_scale(metres_per_pixel, show_bar)`, which
stores them and calls `viewport().update()`.

### Controls

Two buttons join the analysis toolbar beside the ROI tools, since both
act on the canvas: a ruler button (`straighten`, verified present in
the bundled Material Symbols font) arming `draw_scale`, and an
`IconToggleEditor` over `RoiAnalysisModel.show_scale_bar` showing or
hiding the bar. That toggle lives on the model rather than binding
straight to `session.scale.show_bar` because the toolbar is built once
against the viewer model while sessions swap underneath it; the
controller mirrors it both ways, exactly as `edit_mode` relates to
`interaction_mode`.

`interaction_mode` gains `"draw_scale"`, and the toolbar's readout
shows the calibration as text ("1 px = 2.5 µm", or "not calibrated").

## Error handling

An uncalibrated session draws no bar and no error. A calibration whose
line was too short or whose value was not positive is refused by
`metres_per_pixel` returning None, leaving any previous calibration in
place. A zoom so extreme that the snapped bar would be sub-pixel or
wider than the viewport simply draws whatever `nice_scale` returns —
the label stays truthful — and `drawForeground` skips painting
entirely when there is no calibration.

## Testing

Qt-free, in `tests/test_scale_bar.py`:

- `metres_per_pixel` for a known line, and None for a too-short line
  and a zero value.
- `nice_scale` snapping across decades (a 1.7 mm target giving 1 mm, a
  6 mm target giving 5 mm), and the unit ladder switching from mm to
  µm as metres-per-pixel shrinks.
- `format_length` for 40 m, 500 µm, 1 nm, and a sub-nanometre clamp.

Plus a persistence round-trip in `test_roi_store.py` (a calibrated
session reloads its four fields; a config without a `scale` key loads
uncalibrated), and an offscreen smoke that drags a calibration line
through the layer, feeds a value straight to the handler, and renders
`drawForeground` at two zoom levels to confirm the label changes.

## Out of scope

- ROI areas, lengths or intensities reported in real units.
- Burning the bar into an exported image, or a scale on the plots.
- Non-square pixels, lens distortion, or per-wavelength calibration.
- Dragging the bar to a different corner.
