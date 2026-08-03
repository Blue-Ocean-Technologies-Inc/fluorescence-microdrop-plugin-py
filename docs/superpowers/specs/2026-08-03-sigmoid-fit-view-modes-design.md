# Sigmoid Fit + Plot View Modes — Design

Date: 2026-08-03
Branch: `feat/roi-intensity-analysis` (stacks on the curve-fitting work)
Status: approved (sigmoid method; fastest-change metric = max |dy/dt|;
sigmoid demo = 4th disk in the existing fit_demo_experiment)

## Problem

Fluorescence onset curves are sigmoidal, but there is no sigmoid model
in the fit dropdown. Users also want to see WHERE a curve changes
fastest — for a sigmoid, the inflection point — as a per-ROI summary
plot, plus the second-derivative curves that explain it. The plot pane
only ever shows the intensity view.

(ROI moving was also requested but already exists: the Edit toggle
makes ROIs drag-movable. No change.)

## Design

### `analysis/curve_fit.py` — sigmoid method + first derivative

- `FIT_METHODS` gains `"sigmoid"` (after `"exponential"`);
  `FIT_LABELS["sigmoid"] = "Sigmoid"`; `_MIN_POINTS["sigmoid"] = 5`.
- Model: `y = L / (1 + e^(-k·(t - t0))) + C`, evaluated with
  `scipy.special.expit(k·(t - t0))` so large |k·(t-t0)| never
  overflows. Fitted with `scipy.optimize.curve_fit`, `maxfev=10000`,
  data-driven guesses: `C0 = y_first`, `L0 = y_last - y_first` (the
  data span, sign-preserving, or ±ptp when ~0), `t0_0` = the t whose
  value is nearest `C0 + L0/2`, `k0 = 4 / t_span`. Non-finite params →
  `None`, same silent-failure contract as exponential.
- Equation text: `y = {L}/(1+e^(-{k}·(t-{t0}))) + {C}` (3 sig-figs,
  `_signed` join for C; a negative t0 renders as `(t+{|t0|})`).
- `FitResult` gains `first_derivative` (Any: vectorized analytic
  dy/dt), filled by EVERY method: polynomials via `polyder(coeffs, 1)`
  (empty-array guard like d²), exponential `A·k·e^(k·t)`, sigmoid
  `L·k·s(1-s)` with `s = expit(k·(t-t0))`; sigmoid d² is
  `L·k²·s(1-s)(1-2s)` — genuinely interior extrema (at
  `t0 ± ln(2+√3)/k`), unlike the monotonic-d² methods.
- New `fastest_change_time(fit, t_start, t_end) -> float | None`:
  arg-max of |first_derivative| on the same 512-point grid as
  `second_derivative_extrema`, with the same flat-suppression rule
  (ptp of |d1| ≤ 1e-12 of its magnitude → `None`): a linear fit has
  constant |dy/dt|, so it has no meaningful "time of fastest change"
  and gets no bar — consistent with how its d² markers already behave.

### FigureSettings + persistence

- `view_mode = Enum("intensity", "second_derivative",
  "fastest_change")` on `FigureSettings`; appended to `_FIGURE_FIELDS`
  in `roi_store.py` (older configs default to `"intensity"` via the
  tolerated-missing mechanism); the `roi_controller` plot-settings
  persistence observer gains the clause.

### Canvas rendering (`RoiPlotCanvas._refresh`)

`_refresh` branches on `view_mode`. The data lines in `self._lines`
belong to the intensity view only; the other two views clear them and
draw everything as (already per-refresh-cleared) `_fit_artists`.
Axis labels switch per mode; `relim`/autoscale and the coalesced
redraw stay shared.

- **intensity** — exactly today's rendering (data lines, dashed fit
  overlays, corner equations, d² markers, legend).
- **second_derivative** — requires an active fit; with
  `fit_method == "none"` draw a centered axes-fraction hint
  ("Select a fit method to view d²") and nothing else. Per ROI whose
  fit succeeds: solid line of `fit.second_derivative` over the ROI's
  finite-span 200-point dense grid in the ROI's color, labelled with
  the ROI name (legend obeys `show_legend`). The d² Max/Min
  checkboxes mark the arg-extrema ON the d² curve (point + optional
  dotted v-line and `(t, d²)` coords annotation; the h-line option
  draws through the d² value). Y label: "d² of fit". Manual x/y
  limits apply as in intensity.
- **fastest_change** — requires an active fit; same hint when none.
  Bar chart: one bar per ROI whose fit succeeds AND whose
  `fastest_change_time` is not None, in session ROI order; x tick
  labels = ROI names, bar height = t* (seconds since first frame),
  bar color = ROI style color, t* annotated above each bar (3
  sig-figs). ROIs with failed fits or flat |d1| simply have no bar
  (the equations popup explains failures). Y label: "Time of fastest
  change (s)". Manual **y** limits apply; x limits, legend,
  equations, and d² markers do not.

`_PLOT_STATE` gains `session:figure:view_mode`.

### Controls

"View" dropdown (ordered EnumEditor + labels dict format_func, the
verified pattern) placed at the head of controls row 1, labels:
Intensity / 2nd derivative / Fastest change. All existing fit/d²
checkboxes keep their meaning per the mode rules above; no
enabled_when changes (they simply have no effect in modes that ignore
them — the plot itself is the feedback).

### Demo generator (`examples/generate_fit_demo_experiment.py`)

- 4th disk `("sigmoid", (60, 170, 30),
  t -> 3000/(1 + e^(-0.08·(t - 95))) + 500)` — inflection/fastest
  change at t = 95 s; interior d² max ≈ 78.5 s and min ≈ 111.5 s
  (t0 ∓ ln(2+√3)/k), so markers land mid-plot.
- Preset figure switches `fit_method` to `"sigmoid"` (view_mode stays
  `"intensity"`; the user flips the View dropdown to test the others).
- `verify_and_report` adds `"sigmoid"` to the method sweep and prints
  each fit's `fastest_change_time` (or "flat |d1| -> no bar") so the
  bar chart can be checked against ground truth.

## Error handling

All new fit paths return `None` on any failure. Non-intensity views
never raise on empty series/failed fits — they draw fewer artists.
No new observers or lifecycle paths.

## Testing

- `tests/test_curve_fit.py` additions: sigmoid parameter recovery from
  synthetic data (loose tolerances), sigmoid equation shape,
  `first_derivative` correctness for one polynomial + exponential
  case, `fastest_change_time`: sigmoid → ≈ t0, linear → None,
  exponential decay → span start.
- `test_roi_store` round-trip extended with `view_mode`.
- Suite stays at baseline (194 + 2 pre-existing in controls_ui).
- Offscreen smoke: canvas refresh in each of the three modes with a
  fitted session draws without error.

## Out of scope

- Per-ROI fit methods; error bars/confidence on t*; exporting t* to
  CSV; marking t* back on the intensity view; generalized logistic
  (asymmetric) models; ROI-move changes (already works).
