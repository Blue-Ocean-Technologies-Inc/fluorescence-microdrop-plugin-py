# ROI Plot Curve Fitting — Design

Date: 2026-08-01
Branch: `feat/roi-intensity-analysis` (stacks on the pane-layout refactor)
Status: approved (methods = all; global fit method; corner equation box;
plus second-derivative extremum markers)

## Problem

The intensity-vs-time curves have no quantitative model: users need
fitted equations (photobleaching decay rates, trends) they can read,
overlay, and export in publication figures. The legend is also
always-on, and there is no way to annotate where a fitted curve's
curvature peaks.

## Design

### `analysis/curve_fit.py` — Qt-free fitting core (numpy + scipy)

- `FIT_METHODS = ("none", "linear", "poly2", "poly3", "exponential")`
  and `FIT_LABELS = {"none": "No fit", "linear": "Linear",
  "poly2": "Quadratic", "poly3": "Cubic", "exponential": "Exponential"}`.
- `FitResult(HasTraits)`: `method` (Str), `params` (Dict),
  `equation` (Str, e.g. `y = 152·e^(-0.031·t) + 88.4`, 3 sig-figs,
  plain `t^2`/`t^3`/`e^(k·t)` notation so the same string renders in
  both the popup table and on-figure text), `r_squared` (Float),
  `predict` (Any: vectorized t→y), `second_derivative` (Any:
  vectorized analytic d²y/dt²).
- `fit_series(elapsed, values, method) -> FitResult | None`:
  - Filters non-finite pairs first; requires 2/3/4/4 points for
    linear/poly2/poly3/exponential; returns `None` below that.
  - linear/poly2/poly3: `numpy.polyfit`; `predict` via `polyval`,
    `second_derivative` via double `polyder`.
  - exponential `y = A·e^(k·t) + C` via `scipy.optimize.curve_fit`
    with data-driven guesses (`C0 = y_last`, `A0 = y_first - C0` or the
    data span when that is ~0, `k0 = -1/t_span`), `maxfev=10000`.
  - ANY fit failure (non-convergence, singular matrix, overflow)
    returns `None` — callers render "fit failed", never a traceback.
  - `r_squared = 1 - ss_res/ss_tot`; when `ss_tot == 0` (flat data)
    it is 1.0 if the residuals are ~0 else 0.0.
- `second_derivative_extrema(fit, t_start, t_end) ->
  {"max": (t, y), "min": (t, y)} | {}`: evaluates the analytic d² on a
  512-point grid over the data span and takes arg-extrema; `y` is the
  FITTED CURVE's value there (the marker sits on the curve). A flat d²
  (linear/quadratic — |ptp| below 1e-12 of its magnitude) returns `{}`
  so no misleading marker is drawn. Cubic/exponential have monotonic
  d², so their extrema legitimately sit at the span edges.

### FigureSettings + persistence

New traits (defaults in parentheses), appended to `_FIGURE_FIELDS` in
`roi_store.py` so they round-trip `roi_config.json`; older configs load
with defaults via the existing tolerated-missing mechanism:
`fit_method` (Enum over FIT_METHODS, "none"), `show_legend` (True),
`show_fit_equations` (False), `show_second_derivative_max` (False),
`show_second_derivative_min` (False), `second_derivative_vline` (True),
`second_derivative_hline` (False), `second_derivative_coords` (True).
`roi_controller`'s plot-settings persistence observer gains the same
eight names. `roi_model` imports `FIT_METHODS` from `curve_fit` (no
cycle: `curve_fit` imports only numpy/scipy/traits).

### Canvas rendering (`RoiPlotCanvas._refresh`)

Fit artists (overlay lines, equation texts, extremum markers/lines/
annotations) are kept in one list, removed and redrawn on every
already-coalesced refresh:
- Active fit: per visible ROI series, dashed overlay of `predict` over
  a 200-point dense span in the ROI's color (alpha 0.8,
  `label="_nolegend_"`); failed/short series silently get no overlay.
- `show_fit_equations`: stacked per-ROI text artists in the top-left
  axes corner (axes-fraction coords, ROI-colored,
  `"{name}: {equation} (R²={r:.3f})"`).
- Second-derivative markers per enabled extremum: a point on the curve
  at (t*, y*) in the ROI color with black edge; optional dotted
  axvline / axhline through it; optional `(t*, y*)` annotation offset
  beside it (3 sig-figs).
- Legend renders only when `show_legend` (and there are lines).
- `_PLOT_STATE` gains the eight new `figure:` clauses.

### Controls + equations popup

- `_plot_controls_view` row 3: fit-method dropdown (ordered EnumEditor
  + FIT_LABELS format_func), Legend checkbox, "Equations on figure"
  checkbox, Equations… icon button. Row 4 (enabled_when a fit is
  active): d² Max / d² Min checkboxes and the V-line / H-line / Coords
  style toggles (enabled_when max-or-min is on).
- `fit_equations_button = Button()` on `RoiAnalysisModel`.
- New `analysis/fit_equations.py`: `fit_equation_rows(session,
  filtered_paths)` (derive_series + fit_series per ROI → row objects:
  ROI name, method label, equation or "fit failed"/"not enough
  points", R² text) plus a read-only TabularEditor view-model/dialog.
  Non-modal (`kind="live"`); the pane keeps the ui ref, refreshes the
  rows and raises the window when the button is clicked again while
  open; disposes it in `destroy()` if still open. Rows are computed on
  click (not live-updating) — reopening refreshes.

### Dependency

scipy: `pixi add scipy` in the outer `microdrop-py` env (joins the
uncommitted `opencv-python-headless` gate) and added to the plugin's
own dependency metadata (committed with this work).

## Error handling

All fit paths return `None` instead of raising; the canvas skips, the
popup labels the row. No new observers outside the established
detach/destroy lifecycle. The popup ui ref is guarded against an
already-closed window (control is None → rebuild).

## Testing

- New `tests/test_curve_fit.py` (pure math): recovers known
  linear/quadratic/exponential params from synthetic data (loose
  tolerances), NaN filtering, short-series → None, non-convergent →
  None, flat-d² → `{}`, cubic d² extrema at span edges, equation
  formatting shape.
- `test_roi_store` round-trip extended to cover one new figure field
  (`fit_method`).
- Suite stays at baseline (185 + 2 pre-existing in controls_ui).
- Offscreen smokes: controls rows bind/en-disable; popup builds; canvas
  refresh with an active fit draws overlay artists.

## Out of scope

- Per-ROI fit methods; confidence intervals/parameter errors; fit
  parameters in the CSV export; live-updating popup rows.
