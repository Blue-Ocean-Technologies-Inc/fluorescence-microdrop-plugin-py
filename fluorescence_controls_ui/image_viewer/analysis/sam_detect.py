"""SAM droplet detection: osam session, point/grid segmentation, and
candidate conversion. Qt-free (numpy/cv2 in-and-out), importable with or
without the optional ``osam`` package — ``sam_available()`` reports which.

Ported from the standalone droplet_roi prototype (labelme-derived); see
docs/superpowers/specs/2026-08-07-automatic-roi-identification-design.md.
"""
import cv2
import numpy as np
from traits.api import Array, Bool, Float, HasTraits, Int, List, Property, Str

from logger.logger_service import get_logger

from .consts import (
    AI_DETECT_GRID_TARGET_POINTS, AI_DETECT_MAX_MASK_AREA_FRACTION,
    AI_DETECT_MIN_MASK_AREA_PX, AI_ENCODE_WORK_WIDTH_PX,
    AI_NORMALIZE_HIGH_PERCENTILE, AI_NORMALIZE_LOW_PERCENTILE,
)
from .roi_geometry import normalize

logger = get_logger(__name__)

try:
    import osam
except ImportError:          # optional dependency: Help menu installs it
    osam = None

#: (model_name, display_name) — PROTO sam.py MODEL_OPTIONS, labelme's
#: point-prompt AI-assist list, speed -> accuracy within each family.
AI_MODEL_OPTIONS = (
    ("efficientsam:10m", "EfficientSam (speed)"),
    ("efficientsam:latest", "EfficientSam (accuracy)"),
    ("sam:100m", "Sam (speed)"),
    ("sam:300m", "Sam (balanced)"),
    ("sam:latest", "Sam (accuracy)"),
    ("sam2:small", "Sam2 (speed)"),
    ("sam2:latest", "Sam2 (balanced)"),
    ("sam2:large", "Sam2 (accuracy)"),
)
DEFAULT_AI_MODEL = "efficientsam:latest"


def sam_available():
    """Whether the optional osam stack imported."""
    return osam is not None


def normalize_to_uint8(array, low_pct=AI_NORMALIZE_LOW_PERCENTILE,
                       high_pct=AI_NORMALIZE_HIGH_PERCENTILE):
    """Percentile-clip contrast stretch to uint8 (PROTO imaging.py)."""
    if array.dtype == np.uint8 and array.max() > 200:
        return array
    array = array.astype(np.float64)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return np.zeros(array.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [low_pct, high_pct])
    if high - low <= 0:
        return np.zeros(array.shape, dtype=np.uint8)
    normalized = (array - low) / (high - low) * 255
    return np.nan_to_num(np.clip(normalized, 0, 255),
                         nan=0.0).astype(np.uint8)


def to_rgb(gray_u8):
    """Stack grayscale to (H, W, 3) as the SAM encoder requires."""
    return np.stack([gray_u8] * 3, axis=-1)


class Detection(HasTraits):
    """One SAM mask, in the OSAM annotation contract used across
    labelme's _automation package: bbox is (xmin, ymin, xmax, ymax) in
    full-image coordinates, mask is a bool array covering exactly the
    inclusive bbox extent (ymax - ymin + 1, xmax - xmin + 1)."""

    #: xmin, ymin, xmax, ymax
    bbox = List(Float)
    #: local, bbox-sized
    mask = Array(dtype=bool)
    score = Float()


class Candidate(HasTraits):
    """A detection converted to plugin geometry: a fitted ellipse and a
    polygon outline, plus the vote-count/click provenance that decides
    whether it survives significance filtering."""

    #: flat x1, y1, x2, y2, ... in full-image coords
    polygon = List(Float)
    #: cx, cy, rx, ry, angle_deg
    ellipse = List(Float)
    #: how many grid points independently produced this mask in a
    #: Detect-all sweep. Click-added candidates keep 1 but are exempt
    #: from filtering.
    votes = Int(1)
    score = Float(0.0)
    #: the click that produced this candidate, in full-image coords.
    #: Re-detect replays this prompt on the current frame to track
    #: droplet drift.
    prompt = List(Float)
    discarded = Bool(False)
    #: "auto" (grid sweep) | "click" (user-asserted)
    source = Str("auto")

    #: Mean ellipse diameter in px -- the "size" the filter slider uses.
    size = Property(Float, observe="ellipse.items")

    def _get_size(self):
        if len(self.ellipse) < 5:
            return 0.0
        return self.ellipse[2] + self.ellipse[3]

    def geometry_for(self, kind):
        """(kind, geometry) in canonical plugin form, via
        ``roi_geometry.normalize``."""
        if kind == "polygon":
            return normalize("polygon", list(self.polygon))
        return normalize("ellipse", list(self.ellipse))

    def passes(self, min_votes, min_size):
        """Whether this candidate survives significance filtering.
        Click-sourced candidates are exempt from the vote threshold."""
        return ((self.source == "click" or self.votes >= min_votes)
                and self.size >= min_size)


def candidate_from_detection(detection, prompt=None, votes=1, source="auto"):
    """Convert a SAM mask to a fitted ellipse + polygon outline
    ``Candidate``."""
    mask = detection.mask
    if mask is None or not mask.any():
        return None

    xmin, ymin = detection.bbox[0], detection.bbox[1]
    # 1-px pad so masks touching the bbox border still close their contour.
    padded = np.pad(mask.astype(np.uint8), 1)
    contours, _ = cv2.findContours(
        padded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        return None
    contour = max(contours, key=lambda c: cv2.arcLength(c, closed=True))
    contour = contour.reshape(-1, 2).astype(np.float64) - 1.0  # undo pad

    if len(contour) >= 5:
        (ecx, ecy), (ew, eh), angle = cv2.fitEllipse(
            contour.astype(np.float32)
        )
        rx, ry = ew / 2.0, eh / 2.0
    else:
        ecx, ecy = contour.mean(axis=0)
        rx = ry = float(np.sqrt(np.count_nonzero(mask) / np.pi))
        angle = 0.0

    epsilon = 0.004 * max(np.ptp(contour, axis=0)) if len(contour) > 2 else 1.0
    approx = cv2.approxPolyDP(
        contour.astype(np.float32), epsilon=float(epsilon), closed=True
    ).reshape(-1, 2)

    polygon = (approx + [xmin, ymin]).tolist()
    return Candidate(
        polygon=[coordinate for point in polygon for coordinate in point],
        ellipse=[
            float(ecx + xmin),
            float(ecy + ymin),
            float(rx),
            float(ry),
            float(angle),
        ],
        score=detection.score,
        prompt=list(prompt) if prompt is not None else [],
        votes=votes,
        source=source,
    )


def suppress_with_votes(pairs, iou_threshold=0.5):
    """Greedy dedup by score (IoU >= threshold, or intersection-over-smaller
    >= 0.85 for nested masks -- mirrors labelme's suppress_detections_greedy).
    Input carries per-detection initial votes (grid points that supported it);
    votes of merged duplicates are summed into the kept detection -- that
    total is the candidate's significance."""
    kept = []  # [Detection, votes]
    for detection, votes in sorted(pairs, key=lambda pair: -pair[0].score):
        for entry in kept:
            if _is_redundant(detection, entry[0], iou_threshold):
                entry[1] += votes
                break
        else:
            kept.append([detection, votes])
    return [(detection, votes) for detection, votes in kept]


def _is_redundant(a, b, iou_threshold):
    intersection = _mask_intersection_area(a, b)
    if intersection == 0:
        return False
    area_a = int(np.count_nonzero(a.mask))
    area_b = int(np.count_nonzero(b.mask))
    iou = intersection / (area_a + area_b - intersection)
    containment = intersection / max(min(area_a, area_b), 1)
    return iou >= iou_threshold or containment >= 0.85


def _mask_intersection_area(a, b):
    ax0, ay0 = (int(round(v)) for v in a.bbox[:2])
    bx0, by0 = (int(round(v)) for v in b.bbox[:2])
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax0 + a.mask.shape[1], bx0 + b.mask.shape[1])
    y1 = min(ay0 + a.mask.shape[0], by0 + b.mask.shape[0])
    if x0 >= x1 or y0 >= y1:
        return 0
    sub_a = a.mask[y0 - ay0:y1 - ay0, x0 - ax0:x1 - ax0]
    sub_b = b.mask[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0]
    return int(np.count_nonzero(sub_a & sub_b))
