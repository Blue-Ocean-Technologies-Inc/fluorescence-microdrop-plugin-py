"""ROI mask/stats math against synthetic arrays."""
import math

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats, masked_stats, ring_contours, roi_masks,
)


def test_box_interior_stats_on_uniform_patch():
    array = np.zeros((40, 40), dtype=np.uint16)
    array[10:20, 10:20] = 1000
    interior, _outline = roi_masks((40, 40), "box",
                                   [10.0, 10.0, 9.0, 9.0])
    stats = masked_stats(array, interior)
    assert stats["mean"] == 1000.0
    assert stats["std"] == 0.0
    assert stats["min"] == stats["max"] == 1000.0
    assert stats["count"] == 100.0   # cv2.rectangle corners are inclusive


def test_circle_mask_is_filled_disk():
    interior, ring = roi_masks((100, 100), "circle",
                               [50.0, 50.0, 10.0])
    area = np.count_nonzero(interior)
    assert abs(area - math.pi * 10 ** 2) / area < 0.15
    assert np.count_nonzero(ring) > 0


# cv2 fills the boundary ring as well as the interior, so a rasterized
# area runs roughly 1/radius high against the analytic one. These use
# shapes big enough for that bias to sit inside the tolerance.
def test_ellipse_mask_area_matches_pi_rx_ry():
    interior, _outline = roi_masks((300, 300), "ellipse",
                                   (150.0, 150.0, 60.0, 30.0, 0.0))
    expected = math.pi * 60.0 * 30.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05


def test_rotated_ellipse_swaps_its_extent():
    flat, _ = roi_masks((200, 200), "ellipse",
                        (100.0, 100.0, 40.0, 10.0, 0.0))
    turned, _ = roi_masks((200, 200), "ellipse",
                          (100.0, 100.0, 40.0, 10.0, 90.0))
    rows_flat, columns_flat = np.nonzero(flat)
    rows_turned, columns_turned = np.nonzero(turned)
    assert np.ptp(columns_flat) > np.ptp(rows_flat)
    assert np.ptp(rows_turned) > np.ptp(columns_turned)
    assert abs(np.count_nonzero(flat) - np.count_nonzero(turned)) < 40


def test_rotated_box_covers_its_diagonal_corners():
    interior, _outline = roi_masks((200, 200), "box",
                                   (80.0, 90.0, 40.0, 20.0, 45.0))
    # Centre stays inside; the axis-aligned corner leaves the shape.
    assert interior[100, 100] == 255
    assert interior[90, 80] == 0


def test_capsule_mask_area_matches_the_analytic_value():
    interior, _outline = roi_masks((300, 300), "capsule",
                                   (150.0, 150.0, 60.0, 20.0, 0.0))
    expected = math.pi * 20.0 ** 2 + 4.0 * 20.0 * 60.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05


def test_capsule_ring_hugs_its_bounding_box():
    _interior, ring = roi_masks((200, 200), "capsule",
                                (100.0, 100.0, 30.0, 8.0, 0.0),
                                gap_px=2, thickness_px=4)
    rows, columns = np.nonzero(ring)
    # The ring reaches gap + thickness beyond the capsule's extent.
    assert columns.max() <= 100 + 38 + 6 + 1
    assert rows.max() <= 100 + 8 + 6 + 1


def test_unrotated_equal_radii_reuse_the_legacy_circle_mask():
    # Pixel-identical, so intensities cached before ellipses existed
    # stay comparable with anything computed after.
    legacy = np.zeros((200, 200), dtype=np.uint8)
    cv2.circle(legacy, (100, 100), 30, 255, -1)
    interior, _outline = roi_masks((200, 200), "ellipse",
                                   (100.0, 100.0, 30.0, 30.0, 0.0))
    assert np.array_equal(interior, legacy)


def test_legacy_circle_geometry_still_masks():
    interior, _outline = roi_masks((100, 100), "circle",
                                   (50.0, 50.0, 30.0))
    expected = math.pi * 30.0 ** 2
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05


def test_roi_outside_image_yields_nan_stats():
    array = np.zeros((20, 20), dtype=np.uint16)
    interior, _outline = roi_masks((20, 20), "circle",
                                   [500.0, 500.0, 5.0])
    stats = masked_stats(array, interior)
    assert stats["count"] == 0.0
    assert math.isnan(stats["mean"])


def test_compute_image_stats_reads_16bit_png(tmp_path):
    array = np.full((30, 30), 500, dtype=np.uint16)
    array[5:15, 5:15] = 2000
    path = tmp_path / "img_2026_07_20-17_46_24_raw.png"
    cv2.imwrite(str(path), array)
    result = compute_image_stats(str(path), {
        "roi1": ("box", (5.0, 5.0, 9.0, 9.0))})
    assert result["error"] is None
    assert result["stats"]["roi1"]["mean"] == 2000.0
    assert "outline_mean" in result["stats"]["roi1"]
    assert result["mtime"] > 0


def test_compute_image_stats_reports_unreadable_file(tmp_path):
    path = tmp_path / "broken_raw.png"
    path.write_bytes(b"not a png")
    result = compute_image_stats(str(path), {
        "roi1": ("circle", (5.0, 5.0, 2.0))})
    assert result["error"] is not None
    assert result["stats"] == {}


def test_contour_mask_area_matches_the_triangle():
    interior, outline = roi_masks((200, 200), "polygon",
                                  (20.0, 20.0, 120.0, 20.0, 20.0, 100.0))
    expected = 0.5 * 100.0 * 80.0
    assert abs(np.count_nonzero(interior) - expected) / expected < 0.05
    assert 0 < np.count_nonzero(outline) < np.count_nonzero(interior)


def test_contour_below_minimum_vertices_masks_nothing():
    array = np.full((50, 50), 7, dtype=np.uint16)
    interior, _outline = roi_masks((50, 50), "polygon",
                                   (10.0, 10.0, 20.0, 20.0))
    stats = masked_stats(array, interior)
    assert np.count_nonzero(interior) == 0
    assert stats["count"] == 0.0 and math.isnan(stats["mean"])


def test_ring_never_touches_the_interior():
    interior, ring = roi_masks((200, 200), "ellipse",
                               (100.0, 100.0, 30.0, 30.0, 0.0))
    assert np.count_nonzero((interior == 255) & (ring == 255)) == 0


def test_ring_area_matches_the_annulus():
    gap, thickness = 2, 4
    _interior, ring = roi_masks((300, 300), "ellipse",
                                (150.0, 150.0, 40.0, 40.0, 0.0),
                                gap, thickness)
    inner, outer = 40.0 + gap, 40.0 + gap + thickness
    expected = math.pi * (outer ** 2 - inner ** 2)
    assert abs(np.count_nonzero(ring) - expected) / expected < 0.10


def test_gap_pushes_the_ring_outwards():
    centre = (150.0, 150.0, 40.0, 40.0, 0.0)
    _interior, tight = roi_masks((300, 300), "ellipse", centre, 0, 3)
    _interior, spaced = roi_masks((300, 300), "ellipse", centre, 6, 3)
    rows, columns = np.nonzero(tight)
    tight_inner = np.min(np.hypot(columns - 150.0, rows - 150.0))
    rows, columns = np.nonzero(spaced)
    spaced_inner = np.min(np.hypot(columns - 150.0, rows - 150.0))
    assert abs(tight_inner - 40.0) < 2.0
    assert abs(spaced_inner - 46.0) < 2.0


def test_background_correction_recovers_the_true_signal():
    # The regression this cycle exists for: the old boundary-stroke
    # ring read 1569 where the answer is 2900.
    image = np.full((200, 200), 100, dtype=np.uint16)
    cv2.circle(image, (100, 100), 30, 3000, -1)
    interior, ring = roi_masks((200, 200), "ellipse",
                               (100.0, 100.0, 30.0, 30.0, 0.0))
    corrected = (masked_stats(image, interior)["mean"]
                 - masked_stats(image, ring)["mean"])
    assert abs(corrected - 2900.0) < 30.0


def test_ring_excludes_a_neighbouring_roi(tmp_path):
    array = np.full((200, 200), 100, dtype=np.uint16)
    cv2.circle(array, (100, 100), 20, 3000, -1)
    cv2.circle(array, (135, 100), 20, 3000, -1)   # neighbour, close by
    path = tmp_path / "img_2026_07_20-17_46_24_raw.png"
    cv2.imwrite(str(path), array)
    result = compute_image_stats(str(path), {
        "a": ("ellipse", (100.0, 100.0, 20.0, 20.0, 0.0)),
        "b": ("ellipse", (135.0, 100.0, 20.0, 20.0, 0.0))})
    # Without the exclusion the neighbour's 3000 would drag this up.
    assert result["stats"]["a"]["outline_mean"] < 200.0


def test_ring_contours_trace_the_annulus():
    contours = ring_contours((300, 300), "ellipse",
                             (150.0, 150.0, 40.0, 40.0, 0.0), 2, 4)
    assert len(contours) == 2          # an outer and an inner boundary
    extents = sorted(np.max(np.hypot(points[:, 0] - 150.0,
                                     points[:, 1] - 150.0))
                     for points in contours)
    assert abs(extents[0] - 42.0) < 2.0    # inner edge: radius + gap
    assert abs(extents[1] - 46.0) < 2.0    # outer: + thickness
