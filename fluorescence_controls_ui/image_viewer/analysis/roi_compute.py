"""Pure per-image ROI statistics (Qt-free and importable by spawned
worker processes): interior + outline-ring masks for circle/box ROIs and
the summary stats of the masked pixels. Ported from the standalone
fluorescence app's ROIManager (image_tools.py)."""
import os

import cv2
import numpy as np

from .consts import OUTLINE_PERIMETER_PX, OUTLINE_STATS_PREFIX
from .roi_geometry import normalize, outline_of

#: Stats computed for every mask, in column order.
STAT_NAMES = ("mean", "std", "median", "min", "max", "count")


def roi_masks(shape, kind, geometry, perimeter_px=OUTLINE_PERIMETER_PX):
    """(interior, outline) uint8 masks (255 inside) for one ROI on an
    image of ``shape`` (height, width); cv2 clips to the image bounds.
    Geometry is normalized first, so a pre-rotation config still
    computes the same pixels it always did."""
    interior = np.zeros(shape, dtype=np.uint8)
    outline = np.zeros(shape, dtype=np.uint8)
    kind, geometry = normalize(kind, geometry)
    if kind == "ellipse":
        centre_x, centre_y, radius_x, radius_y, angle = geometry
        centre = (int(round(centre_x)), int(round(centre_y)))
        if radius_x == radius_y and angle == 0.0:
            # cv2 does not rasterize the same disk both ways (~3% more
            # pixels through ellipse at r=30), so a plain circle keeps
            # the call every already-cached statistic was computed
            # with: reopening an experiment cannot shift its numbers,
            # nor leave one series half in each convention.
            radius = int(round(radius_x))
            cv2.circle(interior, centre, radius, 255, -1)
            cv2.circle(outline, centre, radius, 255, perimeter_px)
        else:
            axes = (int(round(radius_x)), int(round(radius_y)))
            cv2.ellipse(interior, centre, axes, angle, 0, 360, 255, -1)
            cv2.ellipse(outline, centre, axes, angle, 0, 360, 255,
                        perimeter_px)
    else:
        polygon = outline_of(kind, geometry)
        if len(polygon):
            points = np.round(polygon).astype(np.int32)
            cv2.fillPoly(interior, [points], 255)
            cv2.polylines(outline, [points], True, 255, perimeter_px)
    return interior, outline


def masked_stats(array, mask):
    """mean/std/median/min/max/count of ``array`` under ``mask`` — NaN
    stats with count 0 for an empty mask (ROI fully outside the image)."""
    pixels = array[mask == 255]
    if pixels.size == 0:
        stats = {name: float("nan") for name in STAT_NAMES}
        stats["count"] = 0.0
        return stats
    return {
        "mean": float(np.mean(pixels)),
        "std": float(np.std(pixels)),
        "median": float(np.median(pixels)),
        "min": float(np.min(pixels)),
        "max": float(np.max(pixels)),
        "count": float(np.count_nonzero(mask)),
    }


def compute_image_stats(image_path, effective_rois):
    """Stats for every ROI on one image — the process-pool work unit.

    ``effective_rois``: roi_id -> (kind, geometry tuple), the geometries
    in force for THIS image. Returns {"path", "mtime", "stats":
    {roi_id: {mean..., outline_mean...}}, "error"}; a load failure fills
    "error" and leaves "stats" empty (the caller counts it as failed)."""
    result = {"path": str(image_path), "mtime": 0.0, "stats": {},
              "error": None}
    try:
        result["mtime"] = os.path.getmtime(image_path)
        array = cv2.imread(str(image_path),
                           cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)
        if array is None:
            raise ValueError("unreadable image")
        for roi_id, (kind, geometry) in effective_rois.items():
            interior, outline = roi_masks(array.shape[:2], kind, geometry)
            stats = masked_stats(array, interior)
            for name, value in masked_stats(array, outline).items():
                stats[OUTLINE_STATS_PREFIX + name] = value
            result["stats"][roi_id] = stats
    except Exception as error:
        result["error"] = str(error)
        result["stats"] = {}
    return result
