# ROI editing ergonomics: sticky tools, copy/paste, rounded corners

Date: 2026-08-05
Status: approved

Three independent improvements to placing and shaping ROIs on the image
canvas. They share no state; each can be read on its own.

(A fourth item shipped separately: the scale bar's show/hide toggle is
gone and the bar always draws once a calibration exists.)

## 1. Draw tools stay armed

**Now:** every draw tool is one-shot. Placing a shape drops the canvas
back to pan/edit, so laying down six circles means six trips to the
toolbar.

**Change:** a completed shape leaves the tool armed. Draw a circle,
draw the next one immediately.

Leaving the tool:

- `Esc` returns to the resting mode (edit if the Edit toggle is on,
  otherwise pan).
- Picking another tool, or toggling Edit, switches as it always did.

Contours already use `Esc` to abandon an in-progress trace. That wins:
the first `Esc` drops the trace, a second leaves the tool. Nothing else
about contour drawing changes.

The scale-calibration tool stays one-shot — it measures a fixed
property of the image, so a second line is never wanted.

**Mechanism:** `RoiCanvasLayer` gains an `on_draw_cancelled` callback,
wired (like the other three) to an event trait the controller observes.
The controller stops resetting `interaction_mode` after a creation.

## 2. Copy and paste an ROI

`Ctrl+C` copies the selected ROI; `Ctrl+V` places a copy. Two toolbar
buttons do the same, so the feature is discoverable without knowing the
shortcuts.

What is copied: the ROI's **kind** and the geometry **in force on the
image being viewed** — what the user sees, not the base geometry that a
drift override may have superseded.

What the paste creates: a new ROI, offset by `PASTE_OFFSET_PX` (12 px,
down-right) so it doesn't hide under the original, with

- the next free `ROI N` name,
- the next colour in the cycle — *not* the source's colour, because two
  identically-coloured curves on the plot are unreadable,
- `base_anchor` at the current image, exactly like a freshly drawn ROI.

The clipboard survives selection changes and image navigation (it lives
on the analysis model), so one copy can seed many pastes. It is not the
system clipboard, and does not persist across sessions.

Copy with nothing selected sets the same kind of hint the delete button
uses. Paste with an empty clipboard does nothing.

**Mechanism:** the creation path in `RoiAnalysisController` factors out
to `_create_roi(kind, geometry)`, which both the canvas callback and
paste call, so a pasted ROI is saved, recomputed and drawn by exactly
the code that handles a drawn one.

## 3. Rounded-corner rectangles

A box grows a corner radius, dragged from a third grip — PowerPoint's
rounded rectangle.

**Geometry:** box becomes `[x, y, width, height, angle, corner_radius]`,
a sixth value. `normalize()` pads a stored 5-value box with `0.0`, so
every existing box loads as the sharp rectangle it was. Geometry length
becomes per-kind (`ellipse` and `capsule` stay at 5).

`normalize()` also clamps the radius to `min(width, height) / 2`, so no
consumer has to defend against a radius larger than the shape.

**Cached statistics are not disturbed.** Both halves of the cache
migrate through the same `normalize()` — the ROI config on load, and
the persisted stats keys in `_stats_key()` — so a stored 5-value box
and the stats computed for it grow their sixth value together and go on
matching. This is the same mechanism that carried the cache across the
rotation migration, and a regression test pins it.

**Grip:** on the top edge at the top-right corner, sliding left to
round and right to sharpen (drag inward = rounder, as in PowerPoint).
Top-left and bottom-right are already the rotate and resize grips. Only
boxes get it.

**Everything downstream follows for free.** `outline_of("box", ...)`
returns the rounded outline — corners sampled as quarter-circle arcs —
and that one polygon is what `cv2.fillPoly` measures, what the
background ring dilates from, and what the area column counts. The Qt
item switches from `QGraphicsRectItem` to a path item drawing
`addRoundedRect`, matching the capsule's existing shape.

The rubber-band draft while dragging out a new box stays sharp; the
radius is something you add afterwards.

## Testing

Qt-free unit tests for the geometry (padding, clamping, arc sampling,
translation for paste) and the controller (sticky mode, copy/paste
naming and colour). The grips and key handling are exercised by the
existing offscreen smoke tests, which construct real items on a scene.
