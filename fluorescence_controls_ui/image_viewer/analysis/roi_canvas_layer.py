# fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py
"""Owns the ROI items on the image scene and turns the canvas view's
forwarded mouse events into creation/edit/selection callbacks. Plain
wiring around Qt items, so it stays a plain class; it never touches the
analysis model. The canvas editor points these callbacks at the model's
canvas_* event traits and the controller reacts."""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem,
)

from .consts import (
    MIN_POLYGON_POINTS, MIN_ROI_SIZE_PX, POLYGON_CLOSE_DISTANCE_PX,
)
from .roi_compute import ring_contours
from .roi_handles import ROI_SELECTED_PEN
from .roi_items import (
    BallReferenceItem, BoxRoiItem, CapsuleRoiItem, EllipseRoiItem,
    PolygonRoiItem, capsule_path,
)


#: Canvas item per ROI kind, and the kind each draw mode creates.
ITEM_CLASSES = {"ellipse": EllipseRoiItem, "box": BoxRoiItem,
                "capsule": CapsuleRoiItem, "polygon": PolygonRoiItem}
DRAW_KINDS = {"draw_ellipse": "ellipse", "draw_box": "box",
              "draw_capsule": "capsule", "draw_polygon": "polygon"}

#: The ring is filled as well as outlined: two thin dashed circles in
#: the ROI's own colour read as stray lines, especially once a wide
#: ring is clipped by the image edge, while a tinted band reads as the
#: area it is.
RING_ALPHA = 200
RING_FILL_ALPHA = 60
RING_DASH = Qt.PenStyle.DashLine

#: A freshly dragged capsule starts with its radius at this
#: fraction of the drawn axis — slim enough to read as a capsule,
#: thick enough to grab the radius grip.
CAPSULE_DRAFT_RADIUS_FRACTION = 0.25

#: Stacking: the image pixmap sits at z 0, so a ring below that is
#: invisible — it has to sit above the image and below the shapes.
RING_Z = 0.5
ROI_Z = 1.0

#: Item id of the rolling-ball guide. Not an ROI id: it is never in
#: the session, so it cannot collide with one.
BALL_REFERENCE_ID = "__rolling_ball_reference__"


class RoiCanvasLayer:
    """Owns the ROI items on the image scene (stateless wiring around Qt
    items, so it stays a plain class). The canvas view forwards mouse
    events here when the interaction mode isn't pan; creation/edit/
    selection are reported through the three callbacks."""

    def __init__(self, scene):
        self._scene = scene
        self._items = {}          # roi_id -> item
        self._draft = None        # item being rubber-band drawn
        self._draft_kind = ""
        self._draft_points = []   # contour vertices placed so far
        self._press_point = None
        self._ring_items = []
        self._ring = (0, 0, False)   # gap, thickness, visible
        self.mode = "pan"
        self.on_roi_created = lambda kind, geometry: None
        self.on_roi_edited = lambda roi_id, geometry: None
        self.on_roi_selected = lambda roi_id: None
        self.on_draw_cancelled = lambda: None
        self.on_ball_radius_changed = lambda radius: None
        self._ball_item = None
        self._ball_centre = None
        self._scene.selectionChanged.connect(self._selection_changed)

    def set_mode(self, mode):
        self._discard_contour()   # switching tools abandons a trace
        self.mode = mode
        for item in self._items.values():
            item.set_editable(mode == "edit")
        if self._ball_item is not None:
            # A guide is a tool, not data: it stays draggable outside
            # edit mode, but not while a draw tool is armed, where a
            # click on it would swallow the first corner of a shape.
            self._ball_item.set_editable(mode not in DRAW_KINDS)

    def set_ball_reference(self, visible, radius_px):
        """Show the rolling ball at its true size, or take it away.

        It keeps wherever it was dragged to: the point of moving it is
        to hold it against one feature and then another, and a guide
        that jumped back to the middle on every radius change would
        undo that with each nudge of the spinner."""
        if not visible or radius_px <= 0:
            if self._ball_item is not None:
                self._scene.removeItem(self._ball_item)
                self._ball_item = None
            return
        bounds = self._scene.sceneRect()
        if self._ball_centre is None:
            if bounds.isEmpty():
                return
            self._ball_centre = (bounds.center().x(),
                                 bounds.center().y())
        centre_x, centre_y = self._ball_centre
        geometry = [centre_x, centre_y, float(radius_px),
                    float(radius_px), 0.0]
        if self._ball_item is None:
            self._ball_item = BallReferenceItem(
                BALL_REFERENCE_ID, "Rolling Ball Ref", geometry,
                self._on_ball_edited)
            self._ball_item.setZValue(ROI_Z)
            self._scene.addItem(self._ball_item)
            self._ball_item.set_editable(self.mode not in DRAW_KINDS)
        elif not self._ball_item.is_dragging():
            self._ball_item.set_geometry(geometry)

    def _on_ball_edited(self, roi_id, geometry):
        """The guide was dragged: its centre is where it now sits, and
        its radius is the ball radius the user just chose by eye."""
        centre_x, centre_y, radius_x, _radius_y, _angle = geometry
        self._ball_centre = (centre_x, centre_y)
        self.on_ball_radius_changed(radius_x)

    def set_ring(self, gap_px, thickness_px, visible):
        """The background annulus to draw around each ROI, from the
        session that also measures with it."""
        self._ring = (int(gap_px), int(thickness_px), bool(visible))

    def _clear_rings(self):
        for item in self._ring_items:
            self._scene.removeItem(item)
        self._ring_items = []

    def _draw_rings(self, effective):
        """One dashed outline per ROI, traced from the very mask the
        background is averaged over — drawn on sync, not on every
        repaint, and never interactive."""
        self._clear_rings()
        gap_px, thickness_px, visible = self._ring
        bounds = self._scene.sceneRect()
        if not visible or bounds.isEmpty():
            return
        shape = (int(bounds.height()), int(bounds.width()))
        for roi_id, name, kind, geometry in effective:
            item = self._items.get(roi_id)
            if item is None:
                continue
            path = QPainterPath()
            for contour in ring_contours(shape, kind, geometry,
                                         gap_px, thickness_px):
                path.moveTo(contour[0][0], contour[0][1])
                for x, y in contour[1:]:
                    path.lineTo(x, y)
                path.closeSubpath()
            if path.isEmpty():
                continue
            # Odd-even so the hole in the annulus stays a hole.
            path.setFillRule(Qt.FillRule.OddEvenFill)
            colour = QColor(item.pen().color())
            fill = QColor(colour)
            colour.setAlpha(RING_ALPHA)
            fill.setAlpha(RING_FILL_ALPHA)
            ring_item = QGraphicsPathItem(path)
            ring_item.setPen(QPen(colour, 0, RING_DASH))
            ring_item.setBrush(QBrush(fill))
            ring_item.setZValue(RING_Z)
            ring_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._scene.addItem(ring_item)
            self._ring_items.append(ring_item)

    def sync(self, effective, selected_roi_id):
        """Match the items to ``effective`` ([(roi_id, name, kind,
        geometry), ...] for the SHOWN image) — create, update, drop."""
        wanted = {roi_id: (name, kind, geometry)
                  for roi_id, name, kind, geometry in effective}
        for roi_id in list(self._items):
            if roi_id not in wanted:
                self._scene.removeItem(self._items.pop(roi_id))
        for roi_id, (name, kind, geometry) in wanted.items():
            item = self._items.get(roi_id)
            item_class = ITEM_CLASSES[kind]
            if item is not None and not isinstance(item, item_class):
                self._scene.removeItem(self._items.pop(roi_id))
                item = None
            if item is None:
                item = item_class(roi_id, name, geometry,
                                  self.on_roi_edited)
                item.set_editable(self.mode == "edit")
                item.setZValue(ROI_Z)
                self._scene.addItem(item)
                self._items[roi_id] = item
            elif not item.is_dragging():
                # Skip only while actually mid-drag; a selected-but-idle
                # item must still pick up geometry/name changes (e.g. an
                # image switch), or a later nudge would commit its stale
                # rect as a new drift override.
                item.set_geometry(geometry)
                item.set_name(name)
            item.set_selected_style(roi_id == selected_roi_id)
        self._draw_rings(effective)

    def clear_items(self):
        self._discard_contour()
        self._clear_rings()
        self.set_ball_reference(False, 0)
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items = {}

    # ------------------------------------------------------------------ #
    # Mouse events forwarded by the canvas view (scene coordinates).      #
    # Return True when handled (the view then skips its own handling).    #
    # ------------------------------------------------------------------ #
    def mouse_press(self, scene_point):
        if self.mode == "draw_polygon":
            return self._press_contour(scene_point)
        if self.mode not in DRAW_KINDS:
            return False
        self._press_point = scene_point
        self._draft_kind = DRAW_KINDS[self.mode]
        self._draft = {"ellipse": QGraphicsEllipseItem,
                       "box": QGraphicsRectItem,
                       "capsule": QGraphicsPathItem}[self._draft_kind]()
        self._draft.setPen(ROI_SELECTED_PEN)
        self._scene.addItem(self._draft)
        return True

    def mouse_move(self, scene_point):
        if self.mode == "draw_polygon":
            if not self._draft_points:
                return False
            self._draft.setPath(self._contour_path(scene_point))
            return True
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        if self._draft_kind == "ellipse":
            centre_x, centre_y, radius_x, radius_y, _angle = geometry
            self._draft.setRect(centre_x - radius_x, centre_y - radius_y,
                                2 * radius_x, 2 * radius_y)
        elif self._draft_kind == "box":
            self._draft.setRect(*geometry[:4])
        else:
            self._draft.setPath(capsule_path(geometry))
            self._draft.setTransformOriginPoint(geometry[0], geometry[1])
            self._draft.setRotation(geometry[4])
        return True

    def mouse_release(self, scene_point):
        if self.mode == "draw_polygon":
            # Swallow it so a click that placed a node cannot also pan.
            return bool(self._draft_points)
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        self._scene.removeItem(self._draft)
        self._draft = None
        if self._draft_kind == "box":
            size = min(geometry[2], geometry[3])
        elif self._draft_kind == "capsule":
            size = geometry[3]
        else:
            size = geometry[2]
        if size >= MIN_ROI_SIZE_PX:
            self.on_roi_created(self._draft_kind, geometry)
        return True

    def _drag_geometry(self, scene_point):
        """Geometry of the press->current drag. Ellipse: press is the
        centre. Box: press is a corner. Capsule: press and release are
        the two cap centres, and the radius starts at a quarter of that
        axis for the grip to tune."""
        press = self._press_point
        span_x = scene_point.x() - press.x()
        span_y = scene_point.y() - press.y()
        if self._draft_kind == "ellipse":
            radius = math.hypot(span_x, span_y)
            return [press.x(), press.y(), radius, radius, 0.0]
        if self._draft_kind == "box":
            # Trailing 0.0 is the corner radius: a box is drawn square
            # and rounded afterwards with its own grip.
            return [min(press.x(), scene_point.x()),
                    min(press.y(), scene_point.y()),
                    abs(span_x), abs(span_y), 0.0, 0.0]
        length = math.hypot(span_x, span_y)
        return [press.x() + span_x / 2, press.y() + span_y / 2,
                length / 2,
                max(length * CAPSULE_DRAFT_RADIUS_FRACTION,
                    MIN_ROI_SIZE_PX),
                math.degrees(math.atan2(span_y, span_x))]

    # ------------------------------------------------------------------ #
    # Contour drawing: clicks place vertices, and the loop closes on the  #
    # first node, a double-click or Enter.                                #
    # ------------------------------------------------------------------ #
    def _press_contour(self, scene_point):
        """Place a vertex, or close the contour when the click lands
        back on its first one."""
        if self._draft_points:
            first = self._draft_points[0]
            reach = math.hypot(scene_point.x() - first.x(),
                               scene_point.y() - first.y())
            if reach <= POLYGON_CLOSE_DISTANCE_PX:
                self._close_contour()
                return True
        else:
            self._draft_kind = "polygon"
            self._draft = QGraphicsPathItem()
            self._draft.setPen(ROI_SELECTED_PEN)
            self._scene.addItem(self._draft)
        self._draft_points.append(scene_point)
        self._draft.setPath(self._contour_path(scene_point))
        return True

    def _contour_path(self, cursor_point):
        """The placed vertices, rubber-banded to the cursor."""
        path = QPainterPath(self._draft_points[0])
        for point in self._draft_points[1:]:
            path.lineTo(point)
        path.lineTo(cursor_point)
        return path

    def _close_contour(self):
        """Finish the draft into an ROI, if it has enough vertices."""
        points = self._draft_points
        self._discard_contour()
        if len(points) < MIN_POLYGON_POINTS:
            return
        self.on_roi_created("polygon", [value for point in points
                                        for value in (point.x(),
                                                      point.y())])

    def _discard_contour(self):
        if self._draft_kind == "polygon" and self._draft is not None:
            self._scene.removeItem(self._draft)
            self._draft = None
        self._draft_points = []

    def mouse_double_click(self, scene_point):
        """Close the contour on the vertices already placed."""
        if self.mode != "draw_polygon" or not self._draft_points:
            return False
        self._close_contour()
        return True

    def key_press(self, key):
        """While tracing a contour: Enter closes it, Escape discards it,
        Backspace takes back the last vertex. Otherwise Escape puts an
        armed draw tool away — so a half-drawn contour costs two
        Escapes, the first for the trace and the second for the tool."""
        if self.mode == "draw_polygon" and self._draft_points:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._close_contour()
            elif key == Qt.Key.Key_Escape:
                self._discard_contour()
            elif key == Qt.Key.Key_Backspace:
                self._draft_points.pop()
                if self._draft_points:
                    self._draft.setPath(
                        self._contour_path(self._draft_points[-1]))
                else:
                    self._discard_contour()
            else:
                return False
            return True
        if key == Qt.Key.Key_Escape and self.mode in DRAW_KINDS:
            self.on_draw_cancelled()
            return True
        return False

    def _selection_changed(self):
        for roi_id, item in self._items.items():
            if item.isSelected():
                self.on_roi_selected(roi_id)
                return
        self.on_roi_selected("")
