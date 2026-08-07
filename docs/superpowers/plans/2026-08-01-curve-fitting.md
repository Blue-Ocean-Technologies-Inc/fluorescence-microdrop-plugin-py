# ROI Plot Curve Fitting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fit the plotted ROI intensity curves (linear/quadratic/cubic/
exponential), overlay the fits, show equations in a popup table and/or a
corner box, mark second-derivative extrema, and make the legend optional.

**Architecture:** A Qt-free `curve_fit.py` math core; eight new persisted
`FigureSettings` traits; the canvas clears/redraws fit artists per
coalesced refresh; controls extend the existing per-session TraitsUI
subpanel; the popup is a non-modal read-only TabularEditor. Spec:
`docs/superpowers/specs/2026-08-01-curve-fitting-design.md`.

**Tech Stack:** numpy.polyfit, scipy.optimize.curve_fit, TraitsUI
TabularEditor (read-only), matplotlib artists.

## Global Constraints

- Branch `feat/roi-intensity-analysis`; submodule `feat/roi-analysis-icons`
  for icon constants. Conventional commits, no `--no-verify`, f-strings,
  constants in `consts.py`-style owners.
- Suite baseline: `fluorescence_controls_ui/tests` = 185 passed + 2
  pre-existing failures (`test_chain_model` param-set,
  `test_image_viewer` navigation). `fluorescence_controller`'s 2
  `test_command_setter` failures also pre-exist.
- Test command: `cd microdrop-py && pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && QT_QPA_PLATFORM=offscreen python -m pytest fluorescence_controls_ui/tests -q"`.
- Outer-repo `pyproject.toml`/`pixi.lock` stay UNCOMMITTED (existing
  opencv gate); plugin-repo changes are committed.
- Plugin pep621 `dependencies = []` stays empty by repo convention (host
  env provides deps); conda run deps live in
  `[tool.pixi.package.run-dependencies]` (mpremote precedent).

---

### Task 1: scipy dependency + icon constants

**Files:**
- Modify: outer `microdrop-py/pyproject.toml` + `pixi.lock` (via
  `pixi add scipy` — NEVER hand-edit the lock; leave uncommitted)
- Modify: plugin `pyproject.toml` (`[tool.pixi.package.run-dependencies]`)
- Modify: submodule `src/microdrop_style/icons/icons.py`

**Interfaces:**
- Produces: importable `scipy.optimize.curve_fit` in the pixi env;
  `ICON_FUNCTION = "function"` for the equations-popup button.

- [ ] **Step 1:** `cd microdrop-py && pixi add scipy`; verify
  `pixi run python -c "from scipy.optimize import curve_fit; print('ok')"`.
- [ ] **Step 2:** In plugin `pyproject.toml` under
  `[tool.pixi.package.run-dependencies]` add `scipy = "*"` (below
  `mpremote`). Committed with Task 2.
- [ ] **Step 3:** In submodule `icons.py` append
  `ICON_FUNCTION       = "function"     # fit equations table` after the
  chevron constants; commit there:
  `git commit -m "feat(style): add function icon for fit equations"`.

---

### Task 2: `curve_fit.py` + unit tests

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/curve_fit.py`
- Create: `fluorescence_controls_ui/tests/test_curve_fit.py`
- Modify: plugin `pyproject.toml` (from Task 1 Step 2, same commit)

**Interfaces:**
- Produces: `FIT_METHODS`, `FIT_LABELS`, `FitResult` (traits: `method`,
  `params`, `equation`, `r_squared`, `predict`, `second_derivative`),
  `fit_series(elapsed, values, method) -> FitResult | None`,
  `second_derivative_extrema(fit, t_start, t_end) -> dict`.
  Consumed by Tasks 3 (FIT_METHODS), 4 (fit_series, extrema), 5 (labels,
  fit_series).

- [ ] **Step 1: Write `curve_fit.py`:**

```python
"""Curve fitting for the ROI intensity series: pure math over
(elapsed, value) sequences — Qt-free, session-free. Each method yields
a FitResult carrying the equation text, R², a vectorized predictor,
and the analytic second derivative (for the curvature extremum
markers)."""
import math

import numpy as np
from scipy.optimize import curve_fit
from traits.api import Any, Dict, Float, HasTraits, Str

#: Selectable fit models, in dropdown order ("none" = fitting off).
FIT_METHODS = ("none", "linear", "poly2", "poly3", "exponential")

#: Human labels (fit dropdown + equations table).
FIT_LABELS = {"none": "No fit", "linear": "Linear",
              "poly2": "Quadratic", "poly3": "Cubic",
              "exponential": "Exponential"}

#: Fewest finite points each model can be solved on.
_MIN_POINTS = {"linear": 2, "poly2": 3, "poly3": 4, "exponential": 4}


class FitResult(HasTraits):
    """One fitted model over one ROI's series."""

    method = Str()
    params = Dict()
    equation = Str()
    r_squared = Float()
    #: Vectorized t -> fitted y.
    predict = Any()
    #: Vectorized t -> analytic d²y/dt².
    second_derivative = Any()


def _signed(value):
    """Equation-term join: ' + 3.21' / ' - 3.21' (3 sig-figs)."""
    return f" + {value:.3g}" if value >= 0 else f" - {abs(value):.3g}"


def _poly_equation(coeffs):
    parts = []
    for power, coeff in zip(range(len(coeffs) - 1, -1, -1), coeffs):
        variable = ("" if power == 0
                    else "·t" if power == 1 else f"·t^{power}")
        parts.append(f"{coeff:.3g}{variable}" if not parts
                     else f"{_signed(coeff)}{variable}")
    return "y = " + "".join(parts)


def _r_squared(values, fitted):
    residual = values - fitted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((values - np.mean(values)) ** 2))
    if ss_tot == 0.0:
        return 1.0 if ss_res < 1e-12 else 0.0
    return 1.0 - ss_res / ss_tot


def _fit_polynomial(elapsed, values, degree):
    coeffs = np.polyfit(elapsed, values, degree)
    d2_coeffs = np.polyder(coeffs, 2)
    if not len(d2_coeffs):          # degree 1: d² is identically zero
        d2_coeffs = np.array([0.0])
    return FitResult(
        params={f"c{power}": float(coeff) for power, coeff
                in zip(range(degree, -1, -1), coeffs)},
        equation=_poly_equation(coeffs),
        predict=lambda t, coeffs=coeffs: np.polyval(coeffs, t),
        second_derivative=lambda t, d2_coeffs=d2_coeffs: np.polyval(
            d2_coeffs, np.asarray(t, dtype=float)))


def _exponential(t, amplitude, rate, offset):
    return amplitude * np.exp(rate * np.asarray(t, dtype=float)) + offset


def _fit_exponential(elapsed, values):
    t_span = float(elapsed[-1] - elapsed[0]) or 1.0
    offset0 = float(values[-1])
    amplitude0 = float(values[0] - offset0)
    if abs(amplitude0) < 1e-12:
        amplitude0 = float(np.ptp(values)) or 1.0
    params, _ = curve_fit(_exponential, elapsed, values,
                          p0=(amplitude0, -1.0 / t_span, offset0),
                          maxfev=10000)
    amplitude, rate, offset = (float(value) for value in params)
    if not all(math.isfinite(value)
               for value in (amplitude, rate, offset)):
        return None
    return FitResult(
        params={"amplitude": amplitude, "rate": rate, "offset": offset},
        equation=f"y = {amplitude:.3g}·e^({rate:.3g}·t){_signed(offset)}",
        predict=lambda t: _exponential(t, amplitude, rate, offset),
        second_derivative=lambda t: amplitude * rate * rate * np.exp(
            rate * np.asarray(t, dtype=float)))


def fit_series(elapsed, values, method):
    """Fit one series. None when fitting is off, too few finite points
    remain after NaN filtering, or the optimizer fails — callers render
    that as "fit failed", never a traceback."""
    if method not in _MIN_POINTS:
        return None
    elapsed = np.asarray(elapsed, dtype=float)
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(elapsed) & np.isfinite(values)
    elapsed, values = elapsed[finite], values[finite]
    if len(elapsed) < _MIN_POINTS[method]:
        return None
    try:
        if method == "exponential":
            result = _fit_exponential(elapsed, values)
        else:
            result = _fit_polynomial(
                elapsed, values,
                {"linear": 1, "poly2": 2, "poly3": 3}[method])
    except Exception:
        return None
    if result is None:
        return None
    result.method = method
    result.r_squared = _r_squared(values, result.predict(elapsed))
    return result


def second_derivative_extrema(fit, t_start, t_end):
    """{"max": (t, y_on_curve), "min": (t, y_on_curve)} over
    [t_start, t_end] — the y is the FITTED CURVE's value there, so the
    marker sits on the curve. {} when d² is flat (linear/quadratic):
    no meaningful extremum, draw nothing rather than mislead."""
    grid = np.linspace(float(t_start), float(t_end), 512)
    d2 = np.asarray(fit.second_derivative(grid), dtype=float)
    if d2.shape != grid.shape:      # scalar-returning closure
        d2 = np.full_like(grid, float(d2))
    if not np.all(np.isfinite(d2)):
        return {}
    if float(np.ptp(d2)) <= 1e-12 * max(1.0, float(np.max(np.abs(d2)))):
        return {}
    t_max = float(grid[int(np.argmax(d2))])
    t_min = float(grid[int(np.argmin(d2))])
    return {"max": (t_max, float(fit.predict(t_max))),
            "min": (t_min, float(fit.predict(t_min)))}
```

- [ ] **Step 2: Write `test_curve_fit.py`** — synthetic-data tests:
  linear recovers slope/intercept (`abs(params["c1"] - 3.0) < 1e-6`,
  r² ≈ 1, equation starts `"y = 3·t"`); quadratic + cubic recover
  coefficients; exponential recovers (A=100, k=-0.3, C=10) within 5% on
  `t = linspace(0, 20, 40)`; NaN pairs filtered (same result with NaNs
  injected); too-few-points → None; method "none" → None; linear fit →
  `second_derivative_extrema` returns `{}`; cubic `y = t³` → d² max at
  span end / min at span start with y on the curve; flat-data linear fit
  → r² == 1.0.
- [ ] **Step 3:** Run `pytest fluorescence_controls_ui/tests/test_curve_fit.py -v`
  → all pass.
- [ ] **Step 4: Commit** (curve_fit.py, test file, plugin pyproject):
  `feat(analysis): curve-fitting core with second-derivative extrema`.

---

### Task 3: FigureSettings traits + persistence

**Files:**
- Modify: `analysis/roi_model.py` (FigureSettings + import)
- Modify: `analysis/roi_store.py` (`_FIGURE_FIELDS`)
- Modify: `analysis/roi_controller.py` (`_on_plot_settings_changed`
  observe string)
- Modify: `fluorescence_controls_ui/tests/test_roi_store.py`

**Interfaces:**
- Produces: the eight FigureSettings traits below, persisted; consumed
  by Tasks 4/5 via `session.figure`.

- [ ] **Step 1:** `roi_model.py`: add `from .curve_fit import FIT_METHODS`
  and extend FigureSettings:

```python
    fit_method = Enum(*FIT_METHODS)
    show_legend = Bool(True)
    #: Corner box with each ROI's fitted equation.
    show_fit_equations = Bool(False)
    #: Mark where the fitted curve's second derivative peaks/troughs.
    show_second_derivative_max = Bool(False)
    show_second_derivative_min = Bool(False)
    #: Marker dressing for the enabled extrema.
    second_derivative_vline = Bool(True)
    second_derivative_hline = Bool(False)
    second_derivative_coords = Bool(True)
```

- [ ] **Step 2:** `roi_store.py`: extend `_FIGURE_FIELDS` with the eight
  names (same order as above).
- [ ] **Step 3:** `roi_controller.py`: add the eight
  `analysis_model:session:figure:<name>` clauses to the
  `_on_plot_settings_changed` observe string.
- [ ] **Step 4:** `test_roi_store.py`: add

```python
def test_figure_fit_settings_round_trip(tmp_path):
    session = AnalysisSession()
    session.figure.fit_method = "exponential"
    session.figure.show_legend = False
    save_session(tmp_path, session)
    loaded = load_session(tmp_path)
    assert loaded.figure.fit_method == "exponential"
    assert loaded.figure.show_legend is False
```

  (match the file's existing save/load call signatures).
- [ ] **Step 5:** Suite at baseline (+1 new passing test). Commit:
  `feat(analysis): persist fit, legend and derivative-marker settings`.

---

### Task 4: Canvas fit rendering + optional legend

**Files:**
- Modify: `analysis/plot_pane.py` (imports, `_PLOT_STATE`,
  `RoiPlotCanvas`)

**Interfaces:**
- Consumes: Task 2's `fit_series`/`second_derivative_extrema`, Task 3's
  figure traits.

- [ ] **Step 1:** Imports: `import numpy as np`; `from .curve_fit import
  fit_series, second_derivative_extrema`. `_PLOT_STATE` gains
  `figure:fit_method, figure:show_legend, figure:show_fit_equations,
  figure:show_second_derivative_max, figure:show_second_derivative_min,
  figure:second_derivative_vline, figure:second_derivative_hline,
  figure:second_derivative_coords`.
- [ ] **Step 2:** `RoiPlotCanvas.__init__`: add `self._fit_artists = []`.
  In `_refresh`, after the per-ROI style loop and before the legend
  block:

```python
        for artist in self._fit_artists:
            artist.remove()
        self._fit_artists = []
        figure_settings = self._model.session.figure
        if figure_settings.fit_method != "none":
            self._draw_fits(series, figure_settings)
```

  and replace the legend block with:

```python
        if self._lines and figure_settings.show_legend:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
```

  (drop the now-duplicate `figure_settings = ...` line lower down.)
- [ ] **Step 3:** Add the two drawing methods to `RoiPlotCanvas`:

```python
    def _draw_fits(self, series, figure_settings):
        equation_lines = []
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
            (overlay,) = self._axes.plot(
                dense, fit.predict(dense), linestyle="--", alpha=0.8,
                color=roi.style.color, label="_nolegend_")
            self._fit_artists.append(overlay)
            equation_lines.append(
                (roi.style.color,
                 f"{name}: {fit.equation} (R²={fit.r_squared:.3f})"))
            self._draw_extrema(fit, finite_t.min(), finite_t.max(),
                               roi, figure_settings)
        if figure_settings.show_fit_equations:
            for index, (color, text) in enumerate(equation_lines):
                self._fit_artists.append(self._axes.text(
                    0.02, 0.97 - 0.06 * index, text,
                    transform=self._axes.transAxes, va="top",
                    fontsize="x-small", color=color))

    def _draw_extrema(self, fit, t_start, t_end, roi, figure_settings):
        wanted = [key for key, enabled in
                  (("max", figure_settings.show_second_derivative_max),
                   ("min", figure_settings.show_second_derivative_min))
                  if enabled]
        if not wanted:
            return
        extrema = second_derivative_extrema(fit, t_start, t_end)
        for key in wanted:
            if key not in extrema:
                continue
            t_star, y_star = extrema[key]
            (point,) = self._axes.plot(
                [t_star], [y_star], marker="o", linestyle="",
                color=roi.style.color, markeredgecolor="black",
                label="_nolegend_")
            self._fit_artists.append(point)
            if figure_settings.second_derivative_vline:
                self._fit_artists.append(self._axes.axvline(
                    t_star, color=roi.style.color, linestyle=":",
                    alpha=0.6))
            if figure_settings.second_derivative_hline:
                self._fit_artists.append(self._axes.axhline(
                    y_star, color=roi.style.color, linestyle=":",
                    alpha=0.6))
            if figure_settings.second_derivative_coords:
                self._fit_artists.append(self._axes.annotate(
                    f"({t_star:.3g}, {y_star:.3g})", (t_star, y_star),
                    textcoords="offset points", xytext=(6, 6),
                    fontsize="x-small", color=roi.style.color))
```

  Note `_draw_fits` runs only for series that survived `fit_series`'s
  ≥2-finite-point floor, so `finite_t` is never empty.
- [ ] **Step 4:** Offscreen smoke: canvas with a session whose figure
  has `fit_method="linear"`, `show_legend=False` builds and `_refresh`es
  without traceback (empty series → no artists; legend absent).
- [ ] **Step 5:** Suite at baseline. Commit:
  `feat(analysis): draw fits, equations and derivative markers`.

---

### Task 5: Controls rows + equations popup

**Files:**
- Create: `fluorescence_controls_ui/image_viewer/analysis/fit_equations.py`
- Modify: `analysis/roi_model.py` (button), `analysis/plot_pane.py`
  (controls view + pane wiring)

**Interfaces:**
- Consumes: `FIT_METHODS`/`FIT_LABELS`/`fit_series` (Task 2),
  `derive_series`, `ICON_FUNCTION` (Task 1).
- Produces: `fit_equations_button = Button()` on RoiAnalysisModel;
  `fit_equation_rows(session, filtered_paths)`; `FitEquationsTable`.

- [ ] **Step 1:** `roi_model.py`: after `save_plot_button`:

```python
    #: Open the non-modal table of fitted equations per ROI.
    fit_equations_button = Button()
```

- [ ] **Step 2:** Create `fit_equations.py`:

```python
"""Fit-equations popup: a read-only table of each ROI's fitted
equation for the session's current fit method over the filtered
images. Rows are recomputed when the popup is opened or its button
re-clicked — not live."""
from traits.api import HasTraits, List, Str
from traitsui.api import Item, TabularEditor, View
from traitsui.tabular_adapter import TabularAdapter

from .curve_fit import FIT_LABELS, fit_series
from .plot_series import derive_series


class FitEquationRow(HasTraits):
    """One ROI's fit outcome."""

    roi_name = Str()
    method_label = Str()
    equation = Str()
    r_squared_text = Str()


class _FitEquationAdapter(TabularAdapter):
    columns = [("ROI", "roi_name"), ("Method", "method_label"),
               ("Equation", "equation"), ("R²", "r_squared_text")]
    can_edit = False


class FitEquationsTable(HasTraits):
    """View-model for the popup; rows are replaced wholesale."""

    rows = List(FitEquationRow)

    traits_view = View(
        Item("rows", show_label=False,
             editor=TabularEditor(adapter=_FitEquationAdapter(),
                                  editable=False)),
        title="Fit equations", width=560, height=280, resizable=True)


def fit_equation_rows(session, filtered_paths):
    """Rows for the session's current fit method over the filtered
    images ("fit failed" covers both non-convergence and too few
    points — fit_series does not distinguish)."""
    method = session.figure.fit_method
    rows = []
    for roi_id, (name, elapsed, values) in derive_series(
            session, filtered_paths).items():
        fit = fit_series(elapsed, values, method)
        rows.append(FitEquationRow(
            roi_name=name,
            method_label=FIT_LABELS[method],
            equation=(fit.equation if fit is not None
                      else "no fit selected" if method == "none"
                      else "fit failed"),
            r_squared_text=(f"{fit.r_squared:.4f}"
                            if fit is not None else "")))
    return rows
```

- [ ] **Step 3:** `plot_pane.py` controls view — append rows 3 and 4 to
  the VGroup (imports: `FIT_LABELS, FIT_METHODS` from `.curve_fit`,
  `ICON_FUNCTION` alongside `ICON_SAVE`, plus
  `from .fit_equations import FitEquationsTable, fit_equation_rows`):

```python
        HGroup(
            Item("figure.fit_method", label="Fit",
                 editor=EnumEditor(values=list(FIT_METHODS),
                                   format_func=FIT_LABELS.get)),
            Item("figure.show_legend", label="Legend"),
            Item("figure.show_fit_equations", label="Equations on figure",
                 enabled_when="figure.fit_method != 'none'"),
            UItem("model.fit_equations_button", editor=IconButtonEditor(
                glyph=ICON_FUNCTION,
                tooltip="Show the fitted equation for every ROI in a "
                        "table")),
        ),
        HGroup(
            Item("figure.show_second_derivative_max", label="d² max",
                 enabled_when="figure.fit_method != 'none'"),
            Item("figure.show_second_derivative_min", label="d² min",
                 enabled_when="figure.fit_method != 'none'"),
            Item("figure.second_derivative_vline", label="V-line",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
            Item("figure.second_derivative_hline", label="H-line",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
            Item("figure.second_derivative_coords", label="Coords",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
        ),
```

- [ ] **Step 4:** Pane wiring: `_equations_ui = Any()` trait; in
  `create_contents` observe `"fit_equations_button"`; handler + destroy:

```python
    def _on_fit_equations(self, event):
        rows = fit_equation_rows(roi_analysis_model.session,
                                 roi_analysis_model.filtered_paths)
        if (self._equations_ui is not None
                and self._equations_ui.control is not None):
            self._equations_ui.info.object.rows = rows
            self._equations_ui.control.raise_()
            self._equations_ui.control.activateWindow()
            return
        self._equations_ui = FitEquationsTable(rows=rows).edit_traits(
            kind="live")
```

  In `destroy()` (inside the `self.control is not None` guard): remove
  the `fit_equations_button` observer; and
  `if self._equations_ui is not None and self._equations_ui.control is
  not None: self._equations_ui.dispose()`.
- [ ] **Step 5:** Offscreen smoke: controls subpanel builds with the new
  rows; `enabled_when` flips when `figure.fit_method` changes;
  `fit_equation_rows` on an empty session returns `[]`; a
  `FitEquationsTable(rows=[...])` `edit_traits(kind="live")` builds and
  disposes.
- [ ] **Step 6:** Suite at baseline. Commit:
  `feat(analysis): fit controls, legend toggle and equations popup`.

---

### Task 6: Final verification + review

- [ ] **Step 1:** Full suite (all three test dirs) — only the 4 known
  pre-existing failures.
- [ ] **Step 2:** Import smoke: `curve_fit`, `fit_equations`,
  `plot_pane`, `dock_pane`.
- [ ] **Step 3:** Fresh-eyes review of the diff against the spec +
  conventions; fix findings; commit.
- [ ] **Step 4:** Report with the manual GUI checklist (fit dropdown,
  overlay + equations box, popup table reuse-on-reclick, d² markers with
  each dressing toggle, legend toggle, persistence across experiment
  switch and restart, Save plot… includes fit artists).
