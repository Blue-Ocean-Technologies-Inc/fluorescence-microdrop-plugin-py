# Plot Transforms — Design

Date: 2026-08-05
Branch: `feat/roi-intensity-analysis`
Status: approved (three combinable toggles; normalize per ROI against
its own min/max; flat curves stay at 0%; the CSV gains a normalized
column beside the raw ones)

## Problem

The plot draws one linear scale over raw values. Curves whose
brightnesses differ by an order of magnitude cannot be compared for
shape or timing, and a signal that rises exponentially reads as a wall.

## Scope

Log X, log Y and 0–100% normalization, each independently switchable.
No other transforms (no smoothing, no derivative-of-data, no baseline
subtraction beyond the existing background correction).

## Design

### The two kinds of transform are not the same thing

A log axis is a **display** scale: matplotlib rescales the axis and the
data is untouched, so the fits keep their meaning and a fitted curve
merely bends. Normalization is a **data** transform: it rewrites the
values, and therefore everything derived from them.

Keeping that split explicit is most of this design. Log lives in the
canvas's shared tail; normalization lives one step after
`visible_series`, so every view draws the same numbers.

### `FigureSettings` and the controls

Three persisted booleans — `log_x`, `log_y`, `normalize` — joining
`_FIGURE_FIELDS`, and three `InPlaceToggleEditor` buttons ("Log X",
"Log Y", "Normalize") in the existing toggle row. All three combine.

### `analysis/plot_series.py` — the normalizer

```python
def normalized_series(series):
    """Each ROI stretched to 0-100% of its own finite range..."""
```

Per ROI: `(value − min) / (max − min) × 100` over the finite values,
NaN preserved so gaps stay gaps. A curve with no range (min == max)
stays flat at 0% — there is nothing to stretch, and its zero span
would otherwise divide.

`RoiPlotCanvas._refresh` applies it right after `visible_series`, so
the intensity lines, the fit overlays, the d² curves and the
fastest-change bars all see one set of numbers.

### What normalization does and does not change

The fits are computed on whatever series the canvas holds, so with the
toggle on they are fitted to percentages. Because the transform is
affine in y:

- **Unchanged:** the sigmoid's midpoint, `fastest_change_time`, the d²
  extremum *times*, and R² (scale-invariant — residuals and total
  variance scale together).
- **Changed:** amplitude, offset, the d² magnitudes and the equation
  text, all now in % units.

So the inflection analysis keeps working under normalization, and the
fastest-change bar chart reads the same seconds either way. That bar
chart therefore looks identical whether or not normalization is on,
which is correct rather than a bug.

The stats **table** stays raw throughout: it reports what was measured
on the image in view, not a rendering of the plot.

### Log axes, and the points they silently eat

`_refresh`'s tail sets `set_xscale`/`set_yscale` after the existing
`AutoLocator`/`ScalarFormatter` reset (which would otherwise fight the
log locators) and before `relim`, so autoscaling sees the final scale.

Matplotlib drops non-positive values on a log axis without a word, and
two of those cases are guaranteed rather than hypothetical: elapsed
time starts at exactly 0, so log X always hides the first frame; and
normalization puts an exact 0% at every curve's minimum, so log Y with
normalize on hides one point per curve. The canvas therefore counts
the non-positive values it is about to plot and draws the same gray
hint the other views use — "Log axis hides 4 non-positive points" —
rather than letting data disappear silently.

Manual axis limits of ≤ 0 are invalid on a log axis, so those are
skipped while that axis is logarithmic; the autoscaled range stands.

Both scales apply only where the x axis is time — the intensity and
2nd-derivative views. The fastest-change view keeps linear scales: its
x is ROI names and its y is a duration.

### `analysis/plot_pane.py` — the label

`y_axis_label(plot_stat, scale, normalize)` gains the flag and appends
" (% of range)" when set, alongside the area unit it already splices
in.

### `analysis/roi_store.py` — the CSV column

`write_intensity_csv` gains `normalize_stat=None`. When set, each ROI
gains one `<roi>_<stat>_norm_pct` column after its raw ones, the
header naming the stat it came from so the file explains itself. Every
existing column keeps its position and meaning.

The values come from `normalized_series` itself, fed a series built
from the exported rows — the plot and the CSV cannot disagree, because
they run the same function.

## Error handling

Nothing here raises. A flat curve normalizes to 0% rather than
dividing by zero; a series that is entirely NaN normalizes to NaN and
draws as a gap; a log axis with no positive values draws an empty axis
plus the hint; manual limits that a log scale would reject are
skipped.

## Testing

Qt-free:

- `tests/test_plot_series.py`: `normalized_series` stretching two ROIs
  independently to 0 and 100, preserving NaN gaps, and leaving a flat
  curve at 0.
- `tests/test_roi_store.py`: the `_norm_pct` column's header and one
  computed percentage; no such column when `normalize_stat` is None.

Plus an offscreen smoke: each toggle alone and all three together, the
axis scales actually applied, the hint appearing when log X hides
`t = 0`, and a sigmoid's fitted midpoint identical with and without
normalization (the invariance this design leans on).

## Out of scope

- Smoothing, resampling, or baseline subtraction.
- Log scales on the fastest-change bar chart.
- Per-ROI transform choices (the toggles are figure-wide).
