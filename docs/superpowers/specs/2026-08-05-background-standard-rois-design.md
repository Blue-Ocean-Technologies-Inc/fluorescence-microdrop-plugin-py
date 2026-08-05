# Background standards: ROIs as an internal control

Date: 2026-08-05
Status: approved

Mark one or more ROIs as **background standards** — regions that
should hold no signal — and subtract their average from every other
ROI, per image. An internal control, measured in the same frame under
the same illumination as the samples.

## Marking

A **Std** checkbox column in the stats table, beside the eye. Any
number of ROIs can be marked; their mean is the baseline, so nobody
has to nominate a single blessed region or trust one patch of a noisy
frame.

`Roi.is_standard` is persisted with the ROI, like its name and style.

## What is subtracted

For each image, the baseline is the **mean of the standard ROIs' value
of the stat being plotted**, and it is subtracted from every ROI's
value for that image.

Reading the standards through the same stat is what lets this stack
with the ring: plot `mean` and the baseline is the standards' mean;
plot `bg_corrected` and it is their ring-corrected mean, so both
corrections apply and neither is applied twice.

The standards are corrected too, and settle at (or near) zero. That is
the point — a flat line at zero is the visible evidence the control
behaved, so they are not hidden from the plot automatically.

## Stacking

Three corrections, applied in this order:

1. **Background ring** — inside the stat itself (`bg_corrected` and
   friends), so it is already in the numbers everything else sees.
2. **Background standard** — this feature: a per-image baseline from
   the marked ROIs.
3. **Subtract first** — each curve less its own first value, the
   baseline shift.

Then the display transforms (normalise, log axes) as before.

Each is independent and any combination is allowed. The order above is
the physical reading — remove what the frame contributes, then what the
region started at — but the last two are both subtractions of a
constant per point, so on complete data they commute and ticking the
boxes in either order gives the same curve. (A test pins this; they can
only diverge where curves have their first finite value on different
images.) Normalise stays last because it is the one transform that is
not linear.

**The baseline is computed before hidden ROIs are dropped.** Anyone
using this will hide the standards' flat lines to unclutter the plot,
and if the correction ran on the filtered series that click would
quietly switch the correction off. It runs on the full set instead, so
the eye stays a display control and nothing else.

## Edge cases

- **Toggle on, nothing marked:** the plot says so, in the same hint
  space that reports "all ROIs are hidden". A toggle that silently
  does nothing reads as broken.
- **A standard has no value for an image** (uncomputed, or a failed
  fit of the mask): the baseline averages whichever standards do. With
  none, that image's corrected values are NaN and the curves gap
  there, which is what every other missing value already does.

## Not included

The CSV keeps exporting raw and ring-corrected stats. The normalise
transform has an exported column because a normalised curve cannot be
recovered from the raw numbers; a standard-corrected one can (the
standards are in the file), and `subtract_first` — the sibling
transform — is not exported either.

## Testing

Qt-free tests over the series functions: the baseline from several
standards, stacking with subtract-first, the hidden-standard case, NaN
handling, and nothing marked. The checkbox column gets an offscreen
smoke alongside the eye's.
