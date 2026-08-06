"""Pure per-image ROI statistics (Qt-free and importable by spawned
worker processes): each ROI's interior mask, the background annulus
outside it, and the summary stats of the masked pixels. Ported from the
standalone fluorescence app's ROIManager (image_tools.py); the ring is
this app's own, built by dilation so it never overlaps the shape."""
import os

import cv2
import numpy as np

from .consts import (
    OUTLINE_STATS_PREFIX, RING_GAP_PX, RING_THICKNESS_PX,
)
from .roi_geometry import normalize, outline_of

#: Stats computed for every mask, in column order.
STAT_NAMES = ("mean", "std", "median", "min", "max", "count")


def interior_mask(shape, kind, geometry):
    """The uint8 mask (255 inside) of one ROI on an image of ``shape``
    (height, width); cv2 clips to the image bounds. Geometry is
    normalized first, so a pre-rotation config still computes the same
    pixels it always did."""
    interior = np.zeros(shape, dtype=np.uint8)
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
            cv2.circle(interior, centre, int(round(radius_x)), 255, -1)
        else:
            axes = (int(round(radius_x)), int(round(radius_y)))
            cv2.ellipse(interior, centre, axes, angle, 0, 360, 255, -1)
    else:
        polygon = outline_of(kind, geometry)
        if len(polygon):
            cv2.fillPoly(interior, [np.round(polygon).astype(np.int32)],
                         255)
    return interior


def _disk(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                     (2 * radius + 1, 2 * radius + 1))


def ring_mask(interior, gap_px=RING_GAP_PX,
              thickness_px=RING_THICKNESS_PX):
    """The annulus outside ``interior``: the shape dilated by
    gap + thickness, less the shape dilated by gap. With gap 0 the
    inner edge is the shape's own boundary, so the ring can never
    contain interior pixels. Dilation is exactly 'expand by N', which
    is why this works for a traced contour as readily as an ellipse."""
    gap_px = max(int(gap_px), 0)
    thickness_px = max(int(thickness_px), 1)
    ring = np.zeros_like(interior)
    rows, columns = np.nonzero(interior)
    if not len(rows):
        return ring
    # Dilate on a crop, so cost tracks the ROI rather than the frame.
    pad = gap_px + thickness_px + 1
    top = max(int(rows.min()) - pad, 0)
    bottom = min(int(rows.max()) + pad + 1, interior.shape[0])
    left = max(int(columns.min()) - pad, 0)
    right = min(int(columns.max()) + pad + 1, interior.shape[1])
    patch = interior[top:bottom, left:right]
    outer = cv2.dilate(patch, _disk(gap_px + thickness_px))
    inner = cv2.dilate(patch, _disk(gap_px)) if gap_px else patch
    ring[top:bottom, left:right] = cv2.subtract(outer, inner)
    return ring


def roi_masks(shape, kind, geometry, gap_px=RING_GAP_PX,
              thickness_px=RING_THICKNESS_PX):
    """(interior, ring) uint8 masks for one ROI: the shape itself and
    the background annulus outside it."""
    interior = interior_mask(shape, kind, geometry)
    return interior, ring_mask(interior, gap_px, thickness_px)


def ring_contours(shape, kind, geometry, gap_px=RING_GAP_PX,
                  thickness_px=RING_THICKNESS_PX):
    """The annulus's boundaries as (N, 2) image-pixel arrays — the
    canvas draws these, taken from the very mask that is averaged, so
    the two cannot disagree."""
    _interior, ring = roi_masks(shape, kind, geometry, gap_px,
                                thickness_px)
    found, _hierarchy = cv2.findContours(ring, cv2.RETR_LIST,
                                         cv2.CHAIN_APPROX_SIMPLE)
    return [points.reshape(-1, 2).astype(float) for points in found
            if len(points) >= 3]


def _shrink_factor(radius_px):
    """How far to shrink the image before rolling the ball over it.

    ImageJ's own ladder, and for its reason: the estimate can only
    follow the background as finely as the ball is wide, so shrinking
    below that costs nothing and saves the work. It backs off for small
    radii, where the shrink would start to be the coarser of the two."""
    if radius_px <= 10:
        return 1
    if radius_px <= 30:
        return 2
    return 4 if radius_px <= 100 else 8


def rolling_ball_background(array, radius_px):
    """The uneven background under ``array``, by grey-scale opening with
    a disk — the rolling-ball estimate ImageJ popularised.

    Measured against a known background, estimating it on a shrunken
    image and interpolating back up is both ~13x faster and closer than
    working at full scale: the interpolation gives a smooth surface
    where the full-scale opening follows the flat facets of the disk.

    Only the ESTIMATE is shrunk. It is subtracted from every original
    pixel, so an ROI still averages exactly the pixels it covers."""
    radius_px = max(int(radius_px), 1)
    factor = _shrink_factor(radius_px)
    working = array
    if factor > 1:
        working = cv2.resize(array, None, fx=1.0 / factor,
                             fy=1.0 / factor,
                             interpolation=cv2.INTER_AREA)
    kernel = _disk(max(radius_px // factor, 1))
    background = cv2.morphologyEx(working, cv2.MORPH_OPEN, kernel)
    if factor > 1:
        background = cv2.resize(background,
                                (array.shape[1], array.shape[0]),
                                interpolation=cv2.INTER_LINEAR)
    return background


def subtract_rolling_ball(array, radius_px):
    """``array`` less its rolling-ball background, clipped at zero and
    kept in the image's own dtype — the numbers stay counts, so a
    16-bit frame is still measured as one."""
    background = rolling_ball_background(array, radius_px)
    # cv2.subtract saturates instead of wrapping, which matters: an
    # unsigned pixel below its background would otherwise come back
    # near the top of the range.
    return cv2.subtract(array, background)


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


def compute_image_stats(image_path, effective_rois,
                        gap_px=RING_GAP_PX,
                        thickness_px=RING_THICKNESS_PX,
                        ball_radius_px=0):
    """Stats for every ROI on one image — the process-pool work unit.

    ``effective_rois``: roi_id -> (kind, geometry tuple), the geometries
    in force for THIS image. Returns {"path", "mtime", "stats":
    {roi_id: {mean..., outline_mean...}}, "error"}; a load failure fills
    "error" and leaves "stats" empty (the caller counts it as failed).
    Every ROI's background ring excludes every other ROI's interior: a
    droplet sitting close by is not background, however near it is.

    ``ball_radius_px`` above 0 flattens the frame with the rolling-ball
    estimate BEFORE any ROI is measured, so every stat downstream — the
    ring included — is read off the corrected image."""
    result = {"path": str(image_path), "mtime": 0.0, "stats": {},
              "error": None}
    try:
        result["mtime"] = os.path.getmtime(image_path)
        array = cv2.imread(str(image_path),
                           cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)
        if array is None:
            raise ValueError("unreadable image")
        if ball_radius_px:
            array = subtract_rolling_ball(array, ball_radius_px)
        interiors, rings = {}, {}
        for roi_id, (kind, geometry) in effective_rois.items():
            interiors[roi_id], rings[roi_id] = roi_masks(
                array.shape[:2], kind, geometry, gap_px, thickness_px)
        union = np.zeros(array.shape[:2], dtype=np.uint8)
        for interior in interiors.values():
            cv2.bitwise_or(union, interior, union)
        for roi_id, ring in rings.items():
            others = cv2.subtract(union, interiors[roi_id])
            ring[others == 255] = 0
            stats = masked_stats(array, interiors[roi_id])
            for name, value in masked_stats(array, ring).items():
                stats[OUTLINE_STATS_PREFIX + name] = value
            result["stats"][roi_id] = stats
    except Exception as error:
        result["error"] = str(error)
        result["stats"] = {}
    return result
