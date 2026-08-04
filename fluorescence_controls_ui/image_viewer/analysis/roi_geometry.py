"""Canonical ROI geometry: what each kind's flat float list means, how
the older shorter lists migrate onto it, and the polygons cv2 and Qt
draw from it. Qt-free (numpy only) so the worker processes that compute
statistics can import it."""
import numpy as np

from .consts import MIN_POLYGON_POINTS

#: Values in every canonical geometry list:
#:   ellipse [cx, cy, rx, ry, angle]
#:   box     [x, y, width, height, angle]  (x, y = top-left corner)
#:   capsule [cx, cy, half_length, radius, angle]
#: half_length reaches the cap CENTRE, so a capsule spans
#: 2 * (half_length + radius). Angles are degrees clockwise, the
#: convention cv2.ellipse and QGraphicsItem.setRotation share in y-down
#: image coordinates.
#: A contour is the exception, and has no fixed length or angle:
#:   polygon [x1, y1, x2, y2, ...]  (rotation already in the vertices)
GEOMETRY_LENGTH = 5

#: Pre-rotation kind that could only ever be a circle.
_LEGACY_KINDS = {"circle": "ellipse"}


def normalize(kind, geometry):
    """(kind, geometry) in canonical form: "circle" becomes "ellipse"
    with equal radii, a 4-value box gains its angle, and canonical
    input passes through unchanged. Never raises — a corrupt entry
    degrades to a placeable shape instead of a traceback."""
    kind = _LEGACY_KINDS.get(kind, kind)
    values = [float(value) for value in geometry]
    if kind == "polygon":
        # A contour is a vertex list, so it has no fixed length to pad
        # to and no angle: rotating one rewrites its coordinates.
        return kind, values[:len(values) - len(values) % 2]
    if kind == "ellipse" and len(values) == 3:
        values = [values[0], values[1], values[2], values[2], 0.0]
    values = (values + [0.0] * GEOMETRY_LENGTH)[:GEOMETRY_LENGTH]
    return kind, values


def centre_of(kind, geometry):
    """The (x, y) the shape rotates about — its middle, which the box
    stores only implicitly (it is anchored at its top-left corner)."""
    kind, values = normalize(kind, geometry)
    if kind == "polygon":
        points = np.asarray(values, dtype=float).reshape(-1, 2)
        return float(points[:, 0].mean()), float(points[:, 1].mean())
    if kind == "box":
        return values[0] + values[2] / 2.0, values[1] + values[3] / 2.0
    return values[0], values[1]


def _rotated(points, centre, angle_degrees):
    """``points`` (N, 2) turned clockwise about ``centre``."""
    radians = np.radians(float(angle_degrees))
    cosine, sine = np.cos(radians), np.sin(radians)
    matrix = np.array([[cosine, -sine], [sine, cosine]])
    centre = np.asarray(centre, dtype=float)
    return (np.asarray(points, dtype=float) - centre) @ matrix.T + centre


def box_polygon(geometry):
    """The box's four rotated corners, clockwise from its top-left."""
    _, values = normalize("box", geometry)
    x, y, width, height, angle = values
    corners = [(x, y), (x + width, y),
               (x + width, y + height), (x, y + height)]
    return _rotated(corners, centre_of("box", values), angle)


def capsule_polygon(geometry, samples=32):
    """The stadium outline: both semicircular caps sampled with
    ``samples`` points each and joined by the flanks, in one winding."""
    _, values = normalize("capsule", geometry)
    centre_x, centre_y, half_length, radius, angle = values
    sweep = np.linspace(-np.pi / 2.0, np.pi / 2.0, samples)
    right = np.column_stack([half_length + radius * np.cos(sweep),
                             radius * np.sin(sweep)])
    left = np.column_stack([-half_length - radius * np.cos(sweep),
                            -radius * np.sin(sweep)])
    points = np.vstack([right, left]) + (centre_x, centre_y)
    return _rotated(points, (centre_x, centre_y), angle)


def outline_of(kind, geometry):
    """The polygon cv2 fills and strokes for a box, capsule or
    contour, (N, 2) in image pixels. Empty for a contour with too few
    vertices — callers draw nothing rather than raising."""
    kind, values = normalize(kind, geometry)
    if kind == "box":
        return box_polygon(values)
    if kind == "capsule":
        return capsule_polygon(values)
    points = np.asarray(values, dtype=float).reshape(-1, 2)
    if len(points) < MIN_POLYGON_POINTS:
        return np.empty((0, 2), dtype=float)
    return points
