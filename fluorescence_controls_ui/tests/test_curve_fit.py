"""Unit tests for the Qt-free curve-fitting core."""
import math

import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.curve_fit import (
    fastest_change_time, fit_series, second_derivative_extrema,
)


def test_linear_fit_recovers_slope_and_intercept():
    t = np.linspace(0.0, 10.0, 20)
    fit = fit_series(t, 3.0 * t + 5.0, "linear")
    assert abs(fit.params["c1"] - 3.0) < 1e-6
    assert abs(fit.params["c0"] - 5.0) < 1e-6
    assert fit.r_squared > 0.999999
    assert fit.equation.startswith("y = 3·t")


def test_quadratic_and_cubic_recover_coefficients():
    t = np.linspace(-5.0, 5.0, 30)
    quadratic = fit_series(t, 2.0 * t ** 2 - 3.0 * t + 1.0, "poly2")
    assert abs(quadratic.params["c2"] - 2.0) < 1e-6
    assert abs(quadratic.params["c1"] + 3.0) < 1e-6
    assert abs(quadratic.params["c0"] - 1.0) < 1e-6
    cubic = fit_series(t, 0.5 * t ** 3 + t, "poly3")
    assert abs(cubic.params["c3"] - 0.5) < 1e-6
    assert abs(cubic.params["c1"] - 1.0) < 1e-6


def test_exponential_fit_recovers_decay():
    t = np.linspace(0.0, 20.0, 40)
    fit = fit_series(t, 100.0 * np.exp(-0.3 * t) + 10.0, "exponential")
    assert abs(fit.params["amplitude"] - 100.0) / 100.0 < 0.05
    assert abs(fit.params["rate"] + 0.3) / 0.3 < 0.05
    assert abs(fit.params["offset"] - 10.0) / 10.0 < 0.05
    assert fit.r_squared > 0.999
    assert "e^(" in fit.equation


def test_nan_pairs_are_filtered():
    t = np.linspace(0.0, 10.0, 20)
    values = 3.0 * t + 5.0
    values[3] = math.nan
    values[15] = math.nan
    fit = fit_series(t, values, "linear")
    assert abs(fit.params["c1"] - 3.0) < 1e-6


def test_too_few_points_and_none_method_return_none():
    assert fit_series([0.0, 1.0], [1.0, 2.0], "exponential") is None
    assert fit_series([0.0], [1.0], "linear") is None
    assert fit_series([0.0, 1.0, 2.0], [1.0, 2.0, 3.0], "none") is None


def test_flat_second_derivative_yields_no_extrema():
    t = np.linspace(0.0, 10.0, 20)
    fit = fit_series(t, 3.0 * t + 5.0, "linear")
    assert second_derivative_extrema(fit, 0.0, 10.0) == {}


def test_cubic_second_derivative_extrema_at_span_edges():
    t = np.linspace(-2.0, 2.0, 40)
    fit = fit_series(t, t ** 3, "poly3")
    extrema = second_derivative_extrema(fit, -2.0, 2.0)
    t_max, y_max = extrema["max"]
    t_min, y_min = extrema["min"]
    assert abs(t_max - 2.0) < 1e-6      # d2 = 6t: max at right edge
    assert abs(t_min + 2.0) < 1e-6      # ...min at left edge
    assert abs(y_max - 8.0) < 1e-3      # y on the fitted curve (t^3)
    assert abs(y_min + 8.0) < 1e-3


def test_flat_data_linear_fit_has_r_squared_one():
    t = np.linspace(0.0, 10.0, 10)
    fit = fit_series(t, np.full_like(t, 7.0), "linear")
    assert fit.r_squared == 1.0


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
