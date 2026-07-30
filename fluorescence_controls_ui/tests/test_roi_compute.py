"""ROI mask/stats math against synthetic arrays."""
import math

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats, masked_stats, roi_masks,
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
    interior, outline = roi_masks((100, 100), "circle",
                                  [50.0, 50.0, 10.0])
    area = np.count_nonzero(interior)
    assert abs(area - math.pi * 10 ** 2) / area < 0.15
    assert 0 < np.count_nonzero(outline) < area


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
