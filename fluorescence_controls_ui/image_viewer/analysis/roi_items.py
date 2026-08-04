# fluorescence_controls_ui/image_viewer/analysis/roi_items.py
"""Qt graphics layer for ROI drawing/editing on the image canvas: the
ellipse/box/capsule item classes with their resize and rotate grips,
and the RoiCanvasLayer that owns them on the image scene and turns the
canvas's forwarded mouse events into creation/edit callbacks. Each item
carries its angle as a Qt item rotation about its centre, which keeps
every grip and resize computation in unrotated local coordinates. The
layer never touches the model — the canvas editor wires its callbacks
to the analysis model's canvas_* event traits and the controller
reacts."""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from .consts import MIN_ROI_SIZE_PX, ROTATE_SNAP_DEGREES
from .roi_geometry import centre_of, normalize

#: Cosmetic (zoom-independent 1px) pens; cyan reads on dark raws.
ROI_PEN = QPen(QColor(0, 229, 255), 0)
ROI_SELECTED_PEN = QPen(QColor(255, 214, 0), 0)
HANDLE_BRUSH = QBrush(QColor(255, 214, 0))
HANDLE_SIZE_PX = 9.0


class _ResizeHandle(QGraphicsRectItem):
    """Drag grip riding the parent ROI's edge; dragging resizes it."""

    def __init__(self, parent):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX,
                         parent)
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(
            self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event):
        # A handle drag resizes the parent without going through its
        # mouse events, so guard sync() from here too.
        self.parentItem()._dragging = True
        event.accept()

    def mouseMoveEvent(self, event):
        uniform = bool(event.modifiers()
                       & Qt.KeyboardModifier.ShiftModifier)
        self.parentItem().resize_to(event.scenePos(), uniform)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem().commit_geometry()
        self.parentItem()._dragging = False
        event.accept()


class _RotateHandle(QGraphicsEllipseItem):
    """Round grip riding the parent ROI's top-left; dragging spins it
    about its centre. Shares the resize grip's protocol: mark the
    parent dragging so sync() leaves it alone, commit on release."""

    def __init__(self, parent):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX,
                         parent)
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self._grab_offset = 0.0

    def mousePressEvent(self, event):
        parent = self.parentItem()
        parent._dragging = True
        # Remember where on the circle it was grabbed, so the shape
        # does not jump to the cursor on the first move.
        self._grab_offset = (parent.angle_to(event.scenePos())
                             - parent.rotation())
        event.accept()

    def mouseMoveEvent(self, event):
        parent = self.parentItem()
        angle = parent.angle_to(event.scenePos()) - self._grab_offset
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            angle = (round(angle / ROTATE_SNAP_DEGREES)
                     * ROTATE_SNAP_DEGREES)
        parent.set_angle(angle)
        event.accept()

    def mouseReleaseEvent(self, event):
        parent = self.parentItem()
        parent.commit_geometry()
        parent._dragging = False
        event.accept()


class _RoiItemBase:
    """Shared behavior mixed into the two shape items: identity, label,
    grip, edit-mode flags, and commit-on-release."""

    #: True while the user drags this item (a move) or its resize
    #: handle: sync() skips this item while it's set, so it doesn't
    #: yank a rect the user is actively dragging.
    _dragging = False

    def _setup(self, roi_id, name, on_edited):
        self.roi_id = roi_id
        self._on_edited = on_edited
        self.setPen(ROI_PEN)
        self._label = QGraphicsSimpleTextItem(name, self)
        self._label.setBrush(QBrush(ROI_PEN.color()))
        self._label.setFlag(
            self._label.GraphicsItemFlag.ItemIgnoresTransformations)
        self._handle = _ResizeHandle(self)
        self._rotate_handle = _RotateHandle(self)

    def set_editable(self, editable):
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, editable)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, editable)
        self._handle.setVisible(editable)
        self._rotate_handle.setVisible(editable)

    def angle_to(self, scene_point):
        """Degrees clockwise from the shape's centre to a scene point."""
        centre = self.mapToScene(self.transformOriginPoint())
        return math.degrees(math.atan2(scene_point.y() - centre.y(),
                                       scene_point.x() - centre.x()))

    def set_angle(self, degrees):
        self.setRotation(degrees)

    def resize_to(self, scene_point, uniform=False):
        # mapFromScene undoes the item's rotation, so every shape sizes
        # itself in the unrotated frame it was authored in.
        self._apply_size(self.mapFromScene(scene_point), uniform)
        self._place_attachments()

    def _place_grips(self, centre_x, centre_y, half_width, half_height):
        """Resize grip at the local bottom-right, rotate grip at the
        top-left, label clear of both. All three ignore inherited
        transformations, so they stay upright while their positions
        still ride the rotation."""
        self._handle.setPos(centre_x + half_width,
                            centre_y + half_height)
        self._rotate_handle.setPos(centre_x - half_width,
                                   centre_y - half_height)
        self._label.setPos(centre_x - half_width + HANDLE_SIZE_PX,
                           centre_y - half_height - 2)

    def set_name(self, name):
        self._label.setText(name)

    def set_selected_style(self, selected):
        self.setPen(ROI_SELECTED_PEN if selected else ROI_PEN)
        self._label.setBrush(QBrush(self.pen().color()))

    def is_dragging(self):
        return self._dragging

    def commit_geometry(self):
        self._on_edited(self.roi_id, self.geometry())

    def mousePressEvent(self, event):
        # Starts a possible move drag: guard sync() until release.
        super().mousePressEvent(event)
        if self.flags() & self.GraphicsItemFlag.ItemIsMovable:
            self._dragging = True

    def mouseReleaseEvent(self, event):
        # Ends a move drag: report the moved geometry, then let sync()
        # touch this item again.
        super().mouseReleaseEvent(event)
        if self.flags() & self.GraphicsItemFlag.ItemIsMovable:
            self.commit_geometry()
        self._dragging = False


def capsule_path(geometry):
    """The stadium QPainterPath for a canonical capsule geometry, in
    unrotated local coordinates (the item transform adds the angle)."""
    _, values = normalize("capsule", geometry)
    centre_x, centre_y, half_length, radius, _angle = values
    rectangle = QRectF(centre_x - half_length - radius,
                       centre_y - radius,
                       2 * (half_length + radius), 2 * radius)
    path = QPainterPath()
    path.addRoundedRect(rectangle, radius, radius)
    return path


class EllipseRoiItem(_RoiItemBase, QGraphicsEllipseItem):
    """Ellipse ROI: geometry [cx, cy, rx, ry, angle]; a circle is
    simply rx == ry."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsEllipseItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("ellipse", geometry)
        centre_x, centre_y, radius_x, radius_y, angle = values
        self.setPos(0, 0)
        self.setRect(centre_x - radius_x, centre_y - radius_y,
                     2 * radius_x, 2 * radius_y)
        self.setTransformOriginPoint(centre_x, centre_y)
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        centre = rect.center() + self.pos()
        return [centre.x(), centre.y(), rect.width() / 2,
                rect.height() / 2, self.rotation()]

    def _apply_size(self, point, uniform):
        centre = self.rect().center()
        radius_x = max(abs(point.x() - centre.x()), MIN_ROI_SIZE_PX)
        radius_y = max(abs(point.y() - centre.y()), MIN_ROI_SIZE_PX)
        if uniform:
            radius_x = radius_y = max(radius_x, radius_y)
        self.setRect(centre.x() - radius_x, centre.y() - radius_y,
                     2 * radius_x, 2 * radius_y)

    def _place_attachments(self):
        rect = self.rect()
        self._place_grips(rect.center().x(), rect.center().y(),
                          rect.width() / 2, rect.height() / 2)


class BoxRoiItem(_RoiItemBase, QGraphicsRectItem):
    """Box ROI: geometry [x, y, width, height, angle] with (x, y) the
    unrotated top-left corner; it rotates about its centre."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsRectItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("box", geometry)
        x, y, width, height, angle = values
        self.setPos(0, 0)
        self.setRect(x, y, width, height)
        self.setTransformOriginPoint(*centre_of("box", values))
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        return [rect.x() + self.pos().x(), rect.y() + self.pos().y(),
                rect.width(), rect.height(), self.rotation()]

    def _apply_size(self, point, uniform):
        # Centre-anchored, unlike the pre-rotation top-left anchoring:
        # a moving centre would drag the rotation pivot mid-drag.
        centre = self.rect().center()
        half_width = max(abs(point.x() - centre.x()), MIN_ROI_SIZE_PX)
        half_height = max(abs(point.y() - centre.y()), MIN_ROI_SIZE_PX)
        self.setRect(centre.x() - half_width, centre.y() - half_height,
                     2 * half_width, 2 * half_height)

    def _place_attachments(self):
        rect = self.rect()
        self._place_grips(rect.center().x(), rect.center().y(),
                          rect.width() / 2, rect.height() / 2)


class CapsuleRoiItem(_RoiItemBase, QGraphicsPathItem):
    """Capsule (spherocylinder) ROI: geometry
    [cx, cy, half_length, radius, angle]."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsPathItem.__init__(self)
        self._centre_x = 0.0
        self._centre_y = 0.0
        self._half_length = MIN_ROI_SIZE_PX
        self._radius = MIN_ROI_SIZE_PX
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        _, values = normalize("capsule", geometry)
        (self._centre_x, self._centre_y, self._half_length,
         self._radius, angle) = values
        self.setPos(0, 0)
        self.setPath(capsule_path(values))
        self.setTransformOriginPoint(self._centre_x, self._centre_y)
        self.setRotation(angle)
        self._place_attachments()

    def geometry(self):
        return [self._centre_x + self.pos().x(),
                self._centre_y + self.pos().y(),
                self._half_length, self._radius, self.rotation()]

    def _apply_size(self, point, uniform):
        # The grip rides the bounding corner, so its x distance covers
        # the cap radius as well as the straight half-length.
        self._radius = max(abs(point.y() - self._centre_y),
                           MIN_ROI_SIZE_PX)
        self._half_length = max(
            abs(point.x() - self._centre_x) - self._radius,
            MIN_ROI_SIZE_PX)
        self.setPath(capsule_path(
            [self._centre_x, self._centre_y, self._half_length,
             self._radius, 0.0]))

    def _place_attachments(self):
        self._place_grips(self._centre_x, self._centre_y,
                          self._half_length + self._radius,
                          self._radius)


#: Canvas item per ROI kind, and the kind each draw mode creates.
ITEM_CLASSES = {"ellipse": EllipseRoiItem, "box": BoxRoiItem,
                "capsule": CapsuleRoiItem}
DRAW_KINDS = {"draw_ellipse": "ellipse", "draw_box": "box",
              "draw_capsule": "capsule"}


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
        self._press_point = None
        self.mode = "pan"
        self.on_roi_created = lambda kind, geometry: None
        self.on_roi_edited = lambda roi_id, geometry: None
        self.on_roi_selected = lambda roi_id: None
        self._scene.selectionChanged.connect(self._selection_changed)

    def set_mode(self, mode):
        self.mode = mode
        for item in self._items.values():
            item.set_editable(mode == "edit")

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

    def clear_items(self):
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items = {}

    # ------------------------------------------------------------------ #
    # Mouse events forwarded by the canvas view (scene coordinates).      #
    # Return True when handled (the view then skips its own handling).    #
    # ------------------------------------------------------------------ #
    def mouse_press(self, scene_point):
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
            return [min(press.x(), scene_point.x()),
                    min(press.y(), scene_point.y()),
                    abs(span_x), abs(span_y), 0.0]
        length = math.hypot(span_x, span_y)
        return [press.x() + span_x / 2, press.y() + span_y / 2,
                length / 2, max(length / 4, MIN_ROI_SIZE_PX),
                math.degrees(math.atan2(span_y, span_x))]

    def _selection_changed(self):
        for roi_id, item in self._items.items():
            if item.isSelected():
                self.on_roi_selected(roi_id)
                return
        self.on_roi_selected("")
