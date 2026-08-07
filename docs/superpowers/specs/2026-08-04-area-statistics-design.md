# Area Statistics — Design

Date: 2026-08-04
Branch: `feat/roi-intensity-analysis` (stacks on the scale bar)
Status: approved (integrated and per-area plot stats, each with a
background-corrected sibling; area in the stats table and the CSV;
units follow the scale calibration)

## Problem

Every plotted stat is a per-pixel average, so nothing reports how much
signal an ROI holds or how big it is. Comparing two ROIs of different
sizes, or the same experiment shot at a different magnification, means
doing the arithmetic by hand — and the numbers needed for it (pixel
counts, the scale) are already on hand but never combined.

## The arithmetic, and what it implies

Total fluorescence is `mean × count` and area is `count × pixel_area`,
so `fluo / area` reduces to `mean / pixel_area`: the counts cancel.
Dividing by area therefore yields the mean curve times a constant —
identical shape, different numbers. That is still worth having as a
physical density (counts per mm², comparable across magnifications),
but it is not new information within one experiment.

The quantity that genuinely differs in shape from the mean is the
**integrated** intensity, which moves whenever an ROI's pixel count
moves: a drift override resizing it, or a shape clipped at the image
edge.

This design therefore ships both, each in a raw and a
background-corrected form, so the user can pick the one their question
needs rather than the one the phrase suggested.

## Scope

Four new plot stats, an area column in the stats table and the CSV,
and the unit plumbing they need. No change to the compute path, the
masks, or the persisted stats store: every value here is derived from
numbers already recorded.

## Design

### `image_viewer/scale_bar.py` — two helpers

```python
def pixel_area(metres_per_pixel_value, unit):
    """One pixel's area in ``unit`` squared; 1.0 (that is, px²) when
    there is no calibration, so every size-aware stat still
    computes."""
    if metres_per_pixel_value <= 0:
        return 1.0
    return (metres_per_pixel_value / UNIT_METRES[unit]) ** 2


def area_unit(metres_per_pixel_value, unit):
    """'mm²' when calibrated, 'px²' when not."""
    return f"{unit}²" if metres_per_pixel_value > 0 else "px²"
```

Both take the two calibration numbers rather than the model object, so
`scale_bar` stays Qt-free and model-free. The uncalibrated fallback is
what lets everything downstream work before a calibration exists: areas
read in px² and the per-area stats read counts per px².

### `analysis/plot_series.py` — the derivations

`stat_value(stats, stat, pixel_area=1.0)` gains one argument and five
branches, each a single line beside the existing `bg_corrected`:

| stat | value | notes |
| --- | --- | --- |
| `integrated` | `mean × count` | total signal in the ROI |
| `bg_integrated` | `(mean − outline_mean) × count` | total above background |
| `per_area` | `mean ÷ pixel_area` | counts per mm² |
| `bg_per_area` | `(mean − outline_mean) ÷ pixel_area` | background-corrected density |
| `area` | `count × pixel_area` | the ROI's size |

Two private helpers keep those lines honest: `_signal(stats,
background)` returns the mean, or the mean less the outline ring, and
NaN when either piece is missing; `_count(stats)` returns the pixel
count or NaN. NaN then propagates through the multiplication and
division on its own, so a missing stat still renders as a gap rather
than an exception.

`derive_series` computes `pixel_area` once from `session.scale` and
passes it down, so the whole series shares one calibration.

`PLOT_STATS` gains `integrated`, `bg_integrated`, `per_area` and
`bg_per_area`. `area` is deliberately not a plot stat: it is flat
unless an override resizes an ROI, and it is reported in the table and
the CSV where a number is wanted rather than a curve.

### `analysis/plot_pane.py` — labels that carry the unit

A per-area number is meaningless without its unit, and the unit is not
knowable when the labels dict is written. `PLOT_STAT_LABELS` keeps
static dropdown entries ("Integrated", "Per area", and the two
bg-corrected variants), and a new `y_axis_label(plot_stat, scale)`
composes the axis text, splicing `area_unit(...)` into a template for
the two per-area stats and returning the plain label otherwise. The
canvas asks it for the y-label instead of indexing the dict.

### `analysis/roi_table.py` — the area column

`_STAT_COLUMNS` gains `"area"`, and the headers move from the
constructor into `_rebuild` so `Area (mm²)` tracks the calibration.
`_TABLE_STRUCTURE` gains the session's scale traits, so recalibrating
rebuilds the table rather than leaving a stale unit in the header. Both
`_rebuild` and `_refresh_values` pass `pixel_area` into `stat_value`.

### `analysis/roi_store.py` — the CSV

`write_intensity_csv` gains `pixel_area` and `area_unit_label`
arguments and writes five derived columns per ROI after the stored
ones: `area`, `integrated`, `bg_integrated`, `per_area`,
`bg_per_area`, with the area column's header naming its unit
(`ROI 1_area_mm²`). Each ROI's block therefore grows from 13 columns to
18 — a visible change to an artefact that already exists downstream,
and the one part of this design worth vetoing if the extra width is
unwelcome.

The file is also opened `encoding="utf-8"` rather than the platform
default, since these headers are the first to carry non-ASCII (`µm²`,
`²`) and the default on Windows would mangle them.

## Error handling

Nothing here can raise on missing data: absent `mean`, `outline_mean`
or `count` yields NaN, which the plot already renders as a gap and the
table already renders as an empty cell. `pixel_area` never returns
zero, so no derivation can divide by it. An uncalibrated session is a
normal state, not an error: it reports px² throughout.

## Testing

Qt-free:

- `tests/test_scale_bar.py`: `pixel_area` for a known calibration and
  its 1.0 fallback; `area_unit` for both states.
- `tests/test_plot_series.py`: each of the five derivations against
  hand-computed values, calibrated and uncalibrated; NaN when `count`
  or `outline_mean` is missing; `derive_series` carrying the session's
  calibration into the values it returns.
- `tests/test_roi_store.py`: the CSV's new headers and one computed
  area cell.

Plus an offscreen smoke selecting each new stat on the demo experiment
and confirming the canvas draws and the y-label carries the unit.

## Out of scope

- Perimeter or shape descriptors beyond area.
- Areas corrected for a shape clipped at the image edge (the pixel
  count already reflects the clipping, which is the honest number).
- Per-wavelength or per-exposure normalisation.
