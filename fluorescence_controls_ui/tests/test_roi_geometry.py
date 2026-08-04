"""Unit tests for the canonical ROI geometry helpers."""
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_geometry import (
    box_polygon, capsule_polygon, centre_of, normalize,
)


def test_normalize_upgrades_a_legacy_circle():
    kind, geometry = normalize("circle", [10.0, 20.0, 5.0])
    assert kind == "ellipse"
    assert geometry == [10.0, 20.0, 5.0, 5.0, 0.0]


def test_normalize_upgrades_a_legacy_box():
    kind, geometry = normalize("box", [1.0, 2.0, 30.0, 40.0])
    assert kind == "box"
    assert geometry == [1.0, 2.0, 30.0, 40.0, 0.0]


def test_normalize_is_idempotent():
    once = normalize("circle", [10.0, 20.0, 5.0])
    assert normalize(*once) == once


def test_centre_of_box_is_its_middle():
    assert centre_of("box", [0.0, 0.0, 10.0, 20.0, 0.0]) == (5.0, 10.0)
    assert centre_of("ellipse", [3.0, 4.0, 1.0, 1.0, 0.0]) == (3.0, 4.0)


def test_box_polygon_rotates_clockwise_in_image_coordinates():
    # y grows downward, so +90 degrees carries +x onto +y.
    polygon = box_polygon([0.0, 0.0, 10.0, 0.0, 90.0])
    corners = {(round(x, 6), round(y, 6)) for x, y in polygon}
    assert (5.0, -5.0) in corners
    assert (5.0, 5.0) in corners


def test_capsule_polygon_area_matches_the_analytic_value():
    half_length, radius = 20.0, 6.0
    polygon = capsule_polygon([50.0, 50.0, half_length, radius, 0.0],
                              samples=256)
    x, y = polygon[:, 0], polygon[:, 1]
    # Shoelace formula over the closed outline.
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    expected = np.pi * radius ** 2 + 4.0 * radius * half_length
    assert abs(area - expected) / expected < 0.01


def test_capsule_polygon_rotation_moves_the_tip():
    flat = capsule_polygon([0.0, 0.0, 10.0, 2.0, 0.0], samples=64)
    turned = capsule_polygon([0.0, 0.0, 10.0, 2.0, 90.0], samples=64)
    assert flat[:, 0].max() > 11.0 and abs(flat[:, 1].max() - 2.0) < 0.01
    assert turned[:, 1].max() > 11.0 and abs(turned[:, 0].max() - 2.0) < 0.01
