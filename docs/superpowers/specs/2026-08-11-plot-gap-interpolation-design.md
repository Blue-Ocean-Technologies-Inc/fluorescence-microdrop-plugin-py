# Plot gap interpolation (design)

Date: 2026-08-11
Branch: `feat/plot-gap-interpolation`

## Problem

The ROI intensity plot leaves white gaps wherever a point's value is
NaN — outliers dropped by the Hampel test, images whose stats are not
computed, or background-ref holes. matplotlib breaks the line at NaN,
so a cleaned series reads as a broken curve.

## Decision

A display-only "Bridge gaps" toggle, **on by default**, that linearly
interpolates across internal NaN runs in the drawn lines. The fits,
the CSV export, and the stats table keep the NaNs: an interpolated
value is invented data, and a fit must not earn goodness from it —
the same reasoning that keeps smoothing out of the fits.

Alternatives considered and rejected:

- Dashed bridge segments in a distinct style: extra per-gap artists
  and restyling logic; revisit only if plain bridging misleads.
- Filling the gaps in the analysis pipeline: rejected outright — the
  fits and export must see only measured values.

## Changes

- `roi_model.py` — `FigureSettings.interpolate_gaps = Bool(True)`.
- `plot_series.py` — new pure function `interpolated_series(series)`:
  each curve's **internal** NaN runs replaced by linear interpolation
  between the two nearest finite neighbours. Leading and trailing
  NaNs stay open — there is nothing on the far side to interpolate
  toward. Reuses the interpolation maths already in `_fill_gaps`.
- `plot_pane.py` —
  - `_refresh_intensity` applies `interpolated_series` to the
    **drawn** series only, after smoothing (a smoothed curve bridges
    between its smoothed neighbours). Intensity view only: the d²
    and fastest-change views draw fitted models, which have no gaps.
  - Cleanup tab: `_toggle("figure.interpolate_gaps", "Bridge gaps")`
    in the outlier row, always enabled (gaps exist even with the
    outlier test off), tooltip stating it is display-only.
  - The trait joins the redraw observe list.
- `roi_store.py` — `"interpolate_gaps"` added to `_FIGURE_FIELDS`;
  the tolerant loader defaults it in configs written before it
  existed.

## Testing

Unit tests for `interpolated_series` (pure function): internal gap
filled linearly, leading/trailing NaNs untouched, all-NaN curve
passes through, gapless curve unchanged. GUI verified manually by
the user.
