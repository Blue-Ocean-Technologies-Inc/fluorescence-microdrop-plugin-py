"""Curve fitting for the ROI intensity series: pure math over
(elapsed, value) sequences — Qt-free, session-free. Each method yields
a FitResult carrying the equation text, R², a vectorized predictor,
and the analytic second derivative (for the curvature extremum
markers)."""
import math

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import expit
from traits.api import Any, Dict, Float, HasTraits, Str

#: Selectable fit models, in dropdown order ("none" = fitting off).
FIT_METHODS = ("none", "linear", "poly2", "poly3", "exponential",
               "sigmoid")

#: Human labels (fit dropdown + equations table).
FIT_LABELS = {"none": "No fit", "linear": "Linear",
              "poly2": "Quadratic", "poly3": "Cubic",
              "exponential": "Exponential", "sigmoid": "Sigmoid"}

#: Fewest finite points each model can be solved on.
_MIN_POINTS = {"linear": 2, "poly2": 3, "poly3": 4, "exponential": 4,
               "sigmoid": 5}


class FitResult(HasTraits):
    """One fitted model over one ROI's series."""

    method = Str()
    params = Dict()
    equation = Str()
    r_squared = Float()
    #: Vectorized t -> fitted y.
    predict = Any()
    #: Vectorized t -> analytic dy/dt.
    first_derivative = Any()
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
    d1_coeffs = np.polyder(coeffs, 1)
    if not len(d1_coeffs):
        d1_coeffs = np.array([0.0])
    d2_coeffs = np.polyder(coeffs, 2)
    if not len(d2_coeffs):          # degree 1: d² is identically zero
        d2_coeffs = np.array([0.0])
    return FitResult(
        params={f"c{power}": float(coeff) for power, coeff
                in zip(range(degree, -1, -1), coeffs)},
        equation=_poly_equation(coeffs),
        predict=lambda t, coeffs=coeffs: np.polyval(coeffs, t),
        first_derivative=lambda t, d1_coeffs=d1_coeffs: np.polyval(
            d1_coeffs, np.asarray(t, dtype=float)),
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
        first_derivative=lambda t: amplitude * rate * np.exp(
            rate * np.asarray(t, dtype=float)),
        second_derivative=lambda t: amplitude * rate * rate * np.exp(
            rate * np.asarray(t, dtype=float)))


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
        elif method == "sigmoid":
            result = _fit_sigmoid(elapsed, values)
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
