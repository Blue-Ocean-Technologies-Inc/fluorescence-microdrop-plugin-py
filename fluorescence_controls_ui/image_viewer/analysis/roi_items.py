# fluorescence_controls_ui/image_viewer/analysis/roi_items.py
"""Qt graphics layer for ROI drawing/editing on the image canvas: the
circle/box item classes with a drag-resize corner grip, and the
RoiCanvasLayer that owns them on the image scene and turns the canvas's
forwarded mouse events into creation/edit callbacks. The layer never
touches the model — the canvas editor wires its callbacks to the
analysis model's canvas_* event traits and the controller reacts."""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
)

from .consts import MIN_ROI_SIZE_PX

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
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem().resize_to(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentItem().commit_geometry()
        event.accept()


class _RoiItemBase:
    """Shared behavior mixed into the two shape items: identity, label,
    grip, edit-mode flags, and commit-on-release."""

    #: True between mousePressEvent and mouseReleaseEvent on this item
    #: (a move drag): sync() skips this item while it's set, so it
    #: doesn't yank a rect the user is actively dragging.
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

    def set_editable(self, editable):
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, editable)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, editable)
        self._handle.setVisible(editable)

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


class CircleRoiItem(_RoiItemBase, QGraphicsEllipseItem):
    """Circle ROI: geometry [center_x, center_y, radius]."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsEllipseItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        center_x, center_y, radius = geometry
        self.setPos(0, 0)
        self.setRect(center_x - radius, center_y - radius,
                     2 * radius, 2 * radius)
        self._place_attachments()

    def geometry(self):
        center = self.rect().center() + self.pos()
        return [center.x(), center.y(), self.rect().width() / 2]

    def resize_to(self, scene_point):
        point = self.mapFromScene(scene_point)
        center = self.rect().center()
        radius = max(math.hypot(point.x() - center.x(),
                                point.y() - center.y()), MIN_ROI_SIZE_PX)
        self.setRect(center.x() - radius, center.y() - radius,
                     2 * radius, 2 * radius)
        self._place_attachments()

    def _place_attachments(self):
        rect = self.rect()
        offset = rect.width() / 2 * math.sqrt(0.5)
        self._handle.setPos(rect.center().x() + offset,
                            rect.center().y() + offset)
        self._label.setPos(rect.left(), rect.top() - 2)


class BoxRoiItem(_RoiItemBase, QGraphicsRectItem):
    """Box ROI: geometry [x, y, width, height] (top-left corner)."""

    def __init__(self, roi_id, name, geometry, on_edited):
        QGraphicsRectItem.__init__(self)
        self._setup(roi_id, name, on_edited)
        self.set_geometry(geometry)

    def set_geometry(self, geometry):
        x, y, width, height = geometry
        self.setPos(0, 0)
        self.setRect(x, y, width, height)
        self._place_attachments()

    def geometry(self):
        rect = self.rect()
        return [rect.x() + self.pos().x(), rect.y() + self.pos().y(),
                rect.width(), rect.height()]

    def resize_to(self, scene_point):
        point = self.mapFromScene(scene_point)
        rect = self.rect()
        rect.setRight(max(point.x(), rect.left() + MIN_ROI_SIZE_PX))
        rect.setBottom(max(point.y(), rect.top() + MIN_ROI_SIZE_PX))
        self.setRect(rect)
        self._place_attachments()

    def _place_attachments(self):
        rect = self.rect()
        self._handle.setPos(rect.right(), rect.bottom())
        self._label.setPos(rect.left(), rect.top() - 2)


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
            item_class = CircleRoiItem if kind == "circle" else BoxRoiItem
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
        if self.mode not in ("draw_circle", "draw_box"):
            return False
        self._press_point = scene_point
        self._draft_kind = ("circle" if self.mode == "draw_circle"
                            else "box")
        if self._draft_kind == "circle":
            self._draft = QGraphicsEllipseItem()
        else:
            self._draft = QGraphicsRectItem()
        self._draft.setPen(ROI_SELECTED_PEN)
        self._scene.addItem(self._draft)
        return True

    def mouse_move(self, scene_point):
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        if self._draft_kind == "circle":
            center_x, center_y, radius = geometry
            self._draft.setRect(center_x - radius, center_y - radius,
                                2 * radius, 2 * radius)
        else:
            self._draft.setRect(*geometry)
        return True

    def mouse_release(self, scene_point):
        if self._draft is None:
            return False
        geometry = self._drag_geometry(scene_point)
        self._scene.removeItem(self._draft)
        self._draft = None
        size = geometry[2] if self._draft_kind == "circle" else min(
            geometry[2], geometry[3])
        if size >= MIN_ROI_SIZE_PX:
            self.on_roi_created(self._draft_kind, geometry)
        return True

    def _drag_geometry(self, scene_point):
        """Geometry of the press->current drag: press point = circle
        center / box corner."""
        press = self._press_point
        if self._draft_kind == "circle":
            radius = math.hypot(scene_point.x() - press.x(),
                                scene_point.y() - press.y())
            return [press.x(), press.y(), radius]
        x = min(press.x(), scene_point.x())
        y = min(press.y(), scene_point.y())
        return [x, y, abs(scene_point.x() - press.x()),
                abs(scene_point.y() - press.y())]

    def _selection_changed(self):
        for roi_id, item in self._items.items():
            if item.isSelected():
                self.on_roi_selected(roi_id)
                return
        self.on_roi_selected("")
