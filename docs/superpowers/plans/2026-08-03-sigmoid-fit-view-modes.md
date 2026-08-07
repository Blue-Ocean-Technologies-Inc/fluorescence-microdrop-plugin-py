# Sigmoid Fit + Plot View Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sigmoid (logistic) fit method and a plot-pane View dropdown with three modes — intensity (today's plot), second-derivative curves, and a per-ROI "time of fastest change" bar chart.

**Architecture:** The Qt-free math core (`curve_fit.py`) gains the sigmoid model, an analytic `first_derivative` on every `FitResult`, and a `fastest_change_time` helper. `FigureSettings` gains a persisted `view_mode`; `RoiPlotCanvas._refresh` branches on it, keeping the coalesced-redraw/relim/limits tail shared. Demo generator gains a sigmoid disk with printed ground truth.

**Tech Stack:** numpy, scipy (`optimize.curve_fit`, `special.expit`), matplotlib, Traits/TraitsUI.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-sigmoid-fit-view-modes-design.md`.
- Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py`, branch `feat/roi-intensity-analysis`.
- f-strings everywhere; module-level imports; constants in `consts.py`; no aliasing; conventional commits.
- EnumEditor pattern: `values=<ordered list>, format_func=<labels dict>.get` (never dict `values=`, never `"value:label"` strings).
- Run tests: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && pytest fluorescence_controls_ui/tests/<file> -q"`.
- Never launch the GUI; user tests manually. Never push.

---

### Task 1: Sigmoid fit + first derivative + fastest_change_time (math core)

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/curve_fit.py`
- Test: `fluorescence_controls_ui/tests/test_curve_fit.py`

**Interfaces:**
- Produces: `FIT_METHODS` includes `"sigmoid"`; `FitResult.first_derivative` (vectorized t→dy/dt) on every method; `fastest_change_time(fit, t_start, t_end) -> float | None`.

- [ ] **Step 1: Write failing tests** (append to `test_curve_fit.py`; match its existing import style):

```python
def test_sigmoid_recovers_known_params():
    t = np.arange(0.0, 200.0, 10.0)
    y = 3000.0 / (1.0 + np.exp(-0.08 * (t - 95.0))) + 500.0
    fit = fit_series(t, y, "sigmoid")
    assert fit is not None
    assert fit.r_squared > 0.999
    assert abs(fit.params["rate"] - 0.08) < 0.008
    assert abs(fit.params["midpoint"] - 95.0) < 2.0
    assert abs(fit.params["amplitude"] - 3000.0) < 150.0
    assert fit.equation.startswith("y = ")
    assert "e^(-" in fit.equation


def test_sigmoid_canonicalizes_negative_rate():
    # A falling sigmoid must still report a positive rate (the
    # (L, k, C) -> (-L, -k, L+C) identity).
    t = np.arange(0.0, 200.0, 10.0)
    y = 3000.0 / (1.0 + np.exp(0.08 * (t - 95.0))) + 500.0
    fit = fit_series(t, y, "sigmoid")
    assert fit is not None
    assert fit.params["rate"] > 0
    assert fit.r_squared > 0.999


def test_first_derivative_linear_is_slope():
    t = np.arange(0.0, 100.0, 10.0)
    fit = fit_series(t, 5.0 * t + 600.0, "linear")
    assert np.allclose(fit.first_derivative([0.0, 50.0]), 5.0)


def test_first_derivative_exponential():
    t = np.arange(0.0, 200.0, 10.0)
    fit = fit_series(t, 3000.0 * np.exp(-0.05 * t) + 500.0,
                     "exponential")
    # dy/dt at 0 is A*k = -150
    assert abs(float(fit.first_derivative(0.0)) + 150.0) < 5.0


def test_fastest_change_sigmoid_at_inflection():
    t = np.arange(0.0, 200.0, 10.0)
    y = 3000.0 / (1.0 + np.exp(-0.08 * (t - 95.0))) + 500.0
    fit = fit_series(t, y, "sigmoid")
    assert abs(fastest_change_time(fit, 0.0, 190.0) - 95.0) < 1.0


def test_fastest_change_linear_is_suppressed():
    t = np.arange(0.0, 100.0, 10.0)
    fit = fit_series(t, 5.0 * t + 600.0, "linear")
    assert fastest_change_time(fit, 0.0, 90.0) is None


def test_fastest_change_exponential_decay_at_start():
    t = np.arange(0.0, 200.0, 10.0)
    fit = fit_series(t, 3000.0 * np.exp(-0.05 * t) + 500.0,
                     "exponential")
    assert abs(fastest_change_time(fit, 0.0, 190.0)) < 1.0
```

Add `fastest_change_time` to the test module's `curve_fit` import.

- [ ] **Step 2: Run to verify failure** — expect ImportError on `fastest_change_time` / sigmoid rejects.

- [ ] **Step 3: Implement in `curve_fit.py`:**

Imports: add `from scipy.special import expit`.

```python
FIT_METHODS = ("none", "linear", "poly2", "poly3", "exponential",
               "sigmoid")
FIT_LABELS = {"none": "No fit", "linear": "Linear",
              "poly2": "Quadratic", "poly3": "Cubic",
              "exponential": "Exponential", "sigmoid": "Sigmoid"}
_MIN_POINTS = {"linear": 2, "poly2": 3, "poly3": 4, "exponential": 4,
               "sigmoid": 5}
```

`FitResult` gains `#: Vectorized t -> analytic dy/dt.` / `first_derivative = Any()`.

`_fit_polynomial` also builds `d1_coeffs = np.polyder(coeffs, 1)` (same empty-array guard as d2) and sets `first_derivative=lambda t, d1_coeffs=d1_coeffs: np.polyval(d1_coeffs, np.asarray(t, dtype=float))`.

`_fit_exponential` sets `first_derivative=lambda t: amplitude * rate * np.exp(rate * np.asarray(t, dtype=float))`.

New sigmoid (mirror `_fit_exponential`'s shape):

```python
def _sigmoid(t, amplitude, rate, midpoint, offset):
    return amplitude * expit(
        rate * (np.asarray(t, dtype=float) - midpoint)) + offset


def _fit_sigmoid(elapsed, values):
    t_span = float(elapsed[-1] - elapsed[0]) or 1.0
    offset0 = float(values[0])
    amplitude0 = float(values[-1] - values[0])
    if abs(amplitude0) < 1e-12:
        amplitude0 = float(np.ptp(values)) or 1.0
    half = offset0 + amplitude0 / 2.0
    midpoint0 = float(elapsed[int(np.argmin(np.abs(values - half)))])
    params, _ = curve_fit(_sigmoid, elapsed, values,
                          p0=(amplitude0, 4.0 / t_span, midpoint0,
                              offset0),
                          maxfev=10000)
    amplitude, rate, midpoint, offset = (float(value)
                                         for value in params)
    if not all(math.isfinite(value)
               for value in (amplitude, rate, midpoint, offset)):
        return None
    if rate < 0:      # canonical k>0: L·s(kx)+C == -L·s(-kx)+(L+C)
        amplitude, rate, offset = -amplitude, -rate, offset + amplitude

    def sig(t):
        return expit(rate * (np.asarray(t, dtype=float) - midpoint))

    return FitResult(
        params={"amplitude": amplitude, "rate": rate,
                "midpoint": midpoint, "offset": offset},
        equation=(f"y = {amplitude:.3g}/(1+e^(-{rate:.3g}"
                  f"·(t{_signed(-midpoint)}))){_signed(offset)}"),
        predict=lambda t: _sigmoid(t, amplitude, rate, midpoint,
                                   offset),
        first_derivative=lambda t: amplitude * rate * sig(t)
        * (1.0 - sig(t)),
        second_derivative=lambda t: amplitude * rate * rate * sig(t)
        * (1.0 - sig(t)) * (1.0 - 2.0 * sig(t)))
```

`fit_series` dispatch: `elif method == "sigmoid": result = _fit_sigmoid(elapsed, values)` before the polynomial else-branch.

New helper (mirrors `second_derivative_extrema`'s grid/flat rules):

```python
def fastest_change_time(fit, t_start, t_end):
    """The t in [t_start, t_end] where |dy/dt| of the fitted curve
    peaks — for a sigmoid, its inflection point. None when the speed
    is flat (linear fits): no meaningful "fastest" moment exists, so
    callers draw nothing rather than an arbitrary bar."""
    grid = np.linspace(float(t_start), float(t_end), 512)
    speed = np.abs(np.asarray(fit.first_derivative(grid), dtype=float))
    if speed.shape != grid.shape:   # scalar-returning closure
        speed = np.full_like(grid, float(speed))
    if not np.all(np.isfinite(speed)):
        return None
    if float(np.ptp(speed)) <= 1e-12 * max(1.0, float(np.max(speed))):
        return None
    return float(grid[int(np.argmax(speed))])
```

- [ ] **Step 4: Run the curve-fit test file** — all pass (old + new).

- [ ] **Step 5: Commit** — `feat(analysis): sigmoid fit, first derivative, fastest-change time`

### Task 2: Persist view_mode

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/consts.py`
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_model.py` (FigureSettings)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_store.py` (`_FIGURE_FIELDS`)
- Modify: `fluorescence_controls_ui/image_viewer/analysis/roi_controller.py` (`_on_plot_settings_changed` observe string)
- Test: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Produces: `VIEW_MODES = ("intensity", "second_derivative", "fastest_change")` and `VIEW_MODE_LABELS = {"intensity": "Intensity", "second_derivative": "2nd derivative", "fastest_change": "Fastest change"}` in `analysis/consts.py`; `FigureSettings.view_mode` Enum over `VIEW_MODES`.

- [ ] **Step 1: Failing test** — in `test_roi_store.py`, extend the existing figure round-trip test (`test_figure_fit_settings_round_trip`) to set `view_mode="fastest_change"` before save and assert it after load.
- [ ] **Step 2: Run — fails** (unknown trait).
- [ ] **Step 3: Implement** — consts:

```python
#: Plot pane view modes: the intensity chart, the fits' second-
#: derivative curves, or the per-ROI time-of-fastest-change bars.
VIEW_MODES = ("intensity", "second_derivative", "fastest_change")
VIEW_MODE_LABELS = {"intensity": "Intensity",
                    "second_derivative": "2nd derivative",
                    "fastest_change": "Fastest change"}
```

`roi_model.py`: import `VIEW_MODES` from `.consts`; on `FigureSettings` add `#: Which chart the plot pane renders.` / `view_mode = Enum(*VIEW_MODES)`. `roi_store.py`: append `"view_mode"` to `_FIGURE_FIELDS`. `roi_controller.py`: add `"analysis_model:session:figure:view_mode, "` clause to the `_on_plot_settings_changed` observe string (same format as the fit clauses there).
- [ ] **Step 4: Run test_roi_store — passes.**
- [ ] **Step 5: Commit** — `feat(analysis): persist plot view_mode figure setting`

### Task 3: Render view modes + View dropdown

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/analysis/plot_pane.py`

**Interfaces:**
- Consumes: Task 1 `fastest_change_time`, Task 2 `VIEW_MODES`/`VIEW_MODE_LABELS` + `figure.view_mode`.

- [ ] **Step 1: Controls + observer.** Import `VIEW_MODES, VIEW_MODE_LABELS` from `.consts` and `fastest_change_time` from `.curve_fit`; also `from matplotlib.ticker import AutoLocator, ScalarFormatter`. Row 1 of `_plot_controls_view` gets, as its FIRST item:

```python
Item("figure.view_mode", label="View",
     editor=EnumEditor(values=list(VIEW_MODES),
                       format_func=VIEW_MODE_LABELS.get)),
```

`_PLOT_STATE` gains `"session:figure:view_mode, "`.

- [ ] **Step 2: Refactor `_refresh` to branch.** Keep the head (pending flag, detach/visibility guards, `derive_series`) and the tail (`relim`, `autoscale_view`, manual limits, `draw_idle`) shared. Between them:

```python
figure_settings = self._model.session.figure
for artist in self._fit_artists:
    artist.remove()
self._fit_artists = []
# A previous fastest-change render left categorical ticks behind.
self._axes.xaxis.set_major_locator(AutoLocator())
self._axes.xaxis.set_major_formatter(ScalarFormatter())
self._axes.set_xlabel("Elapsed time (s)")
if figure_settings.view_mode == "intensity":
    self._refresh_intensity(series, figure_settings)
else:
    for roi_id in list(self._lines):
        self._lines.pop(roi_id).remove()
    if figure_settings.view_mode == "second_derivative":
        self._draw_second_derivative(series, figure_settings)
    else:
        self._draw_fastest_change(series, figure_settings)
```

`_refresh_intensity(series, figure_settings)` = the existing body verbatim (ylabel from `PLOT_STAT_LABELS`, line add/update/drop, `_draw_fits` when fitting, legend via `_apply_legend`). Manual-limit tail change: apply `x_min/x_max` only when `figure_settings.view_mode != "fastest_change"`.

Shared helpers:

```python
def _apply_legend(self, wanted):
    if wanted:
        self._axes.legend(loc="best", fontsize="small")
    elif self._axes.get_legend() is not None:
        self._axes.get_legend().remove()


def _draw_hint(self, message):
    self._fit_artists.append(self._axes.text(
        0.5, 0.5, message, transform=self._axes.transAxes,
        ha="center", va="center", color="gray"))
```

(Existing legend code inside the old `_refresh` moves into `_refresh_intensity` as `self._apply_legend(bool(self._lines) and figure_settings.show_legend)`.)

- [ ] **Step 3: d² view.** Marker drawing is shared with the intensity view: split the inner per-key body of `_draw_extrema` into `_draw_extremum_marker(t_star, y_star, roi, figure_settings)` (point + optional axvline/axhline/coords — code identical to today's loop body) and call it from `_draw_extrema`. Then:

```python
def _draw_second_derivative(self, series, figure_settings):
    """One curve per ROI: the fitted model's d²y/dt² over the ROI's
    time span; the d² max/min checkboxes mark its extrema here."""
    self._axes.set_ylabel("d² of fit")
    if figure_settings.fit_method == "none":
        self._apply_legend(False)
        self._draw_hint("Select a fit method to view d²")
        return
    drew = False
    for roi_id, (name, elapsed, values) in series.items():
        roi = self._model.session.roi_by_id(roi_id)
        if roi is None:
            continue
        fit = fit_series(elapsed, values, figure_settings.fit_method)
        if fit is None:
            continue
        finite_t = np.asarray(elapsed, dtype=float)[
            np.isfinite(np.asarray(values, dtype=float))]
        dense = np.linspace(finite_t.min(), finite_t.max(), 200)
        d2 = np.asarray(fit.second_derivative(dense), dtype=float)
        if d2.shape != dense.shape:
            d2 = np.full_like(dense, float(d2))
        (curve,) = self._axes.plot(dense, d2, color=roi.style.color,
                                   label=name)
        self._fit_artists.append(curve)
        drew = True
        wanted = [key for key, enabled in
                  (("max", figure_settings.show_second_derivative_max),
                   ("min", figure_settings.show_second_derivative_min))
                  if enabled]
        if wanted:
            extrema = second_derivative_extrema(
                fit, finite_t.min(), finite_t.max())
            for key in wanted:
                if key not in extrema:
                    continue
                t_star = extrema[key][0]
                self._draw_extremum_marker(
                    t_star, float(fit.second_derivative(t_star)),
                    roi, figure_settings)
    self._apply_legend(drew and figure_settings.show_legend)
```

- [ ] **Step 4: fastest-change view.**

```python
def _draw_fastest_change(self, series, figure_settings):
    """Bar per ROI: seconds until the fitted curve changes fastest
    (max |dy/dt| — a sigmoid's inflection point). ROIs whose fit
    fails or whose speed is flat (linear) get no bar."""
    self._axes.set_ylabel("Time of fastest change (s)")
    self._axes.set_xlabel("ROI")
    self._apply_legend(False)
    if figure_settings.fit_method == "none":
        self._draw_hint("Select a fit method to view fastest change")
        return
    labels, times, colors = [], [], []
    for roi_id, (name, elapsed, values) in series.items():
        roi = self._model.session.roi_by_id(roi_id)
        if roi is None:
            continue
        fit = fit_series(elapsed, values, figure_settings.fit_method)
        if fit is None:
            continue
        finite_t = np.asarray(elapsed, dtype=float)[
            np.isfinite(np.asarray(values, dtype=float))]
        t_star = fastest_change_time(fit, finite_t.min(),
                                     finite_t.max())
        if t_star is None:
            continue
        labels.append(name)
        times.append(t_star)
        colors.append(roi.style.color)
    if not labels:
        self._draw_hint("No fastest-change times "
                        "(fits failed or rate is constant)")
        return
    positions = list(range(len(labels)))
    self._fit_artists.extend(
        self._axes.bar(positions, times, color=colors))
    self._axes.set_xticks(positions, labels)
    for x, t_star in zip(positions, times):
        self._fit_artists.append(self._axes.annotate(
            f"{t_star:.3g}", (x, t_star), textcoords="offset points",
            xytext=(0, 4), ha="center", fontsize="x-small"))
```

- [ ] **Step 5: Offscreen smoke** (scratchpad script, not committed): build an `AnalysisSession` against the demo experiment, set each view_mode in turn, force `_refresh`, assert no exception and that `_fit_artists` is non-empty for d²/bars.
- [ ] **Step 6: Run controls_ui suite** — baseline (existing tests untouched).
- [ ] **Step 7: Commit** — `feat(analysis): plot view modes (d2 curves, fastest-change bars)`

### Task 4: Sigmoid demo disk + ground-truth printout

**Files:**
- Modify: `examples/generate_fit_demo_experiment.py`

**Interfaces:**
- Consumes: Task 1 `fastest_change_time`.

- [ ] **Step 1:** Add to `DEMO_ROIS` (after "linear"):

```python
    ("sigmoid", (60.0, 170.0, 30.0),
     lambda t: 3000.0 / (1.0 + math.exp(-0.08 * (t - 95.0))) + 500.0,
     "y = 3000/(1+e^(-0.08·(t-95))) + 500"),
```

`build_session`: `figure_settings.fit_method = "sigmoid"` (replaces "exponential"). `verify_and_report`: import `fastest_change_time`; method sweep tuple becomes `("linear", "poly2", "poly3", "exponential", "sigmoid")`; after the extrema suffix append:

```python
            t_fastest = fastest_change_time(
                fit, min(elapsed), max(elapsed))
            line += (f"  fastest@{t_fastest:.3g}s"
                     if t_fastest is not None
                     else "  (constant rate -> no bar)")
```

Update the module docstring's ROI list to include the sigmoid disk (inflection at t=95; d² max/min ≈ 78/112 s, interior).

- [ ] **Step 2: Regenerate** the demo (`python examples/generate_fit_demo_experiment.py` via pixi) and check the printout: sigmoid ROI recovers the equation with R²≈1, fastest@95, d² extrema ≈ 78.5/111.5; linear ROI shows "(constant rate -> no bar)" under linear.
- [ ] **Step 3: Commit** — `feat(examples): sigmoid demo disk with fastest-change ground truth`

### Task 5: Verify + review

- [ ] Run all three plugin test dirs; expect baseline (pre-existing failures only: test_chain_model, test_image_viewer navigation, 2× test_command_setter).
- [ ] Dispatch background feature-dev:code-reviewer (sonnet) over the diff range with the spec; address anything actionable.
- [ ] Report to user (no push).
