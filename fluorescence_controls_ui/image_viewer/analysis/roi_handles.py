# fluorescence_controls_ui/image_viewer/analysis/roi_handles.py
"""Drag grips shared by the ROI canvas items. Each marks its parent as
dragging on press so the layer's sync() leaves that shape alone, edits
it on move, and commits exactly one edit on release."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem

from .consts import ROTATE_SNAP_DEGREES

#: Cosmetic (zoom-independent 1px) pens; cyan reads on dark raws.
ROI_PEN = QPen(QColor(0, 229, 255), 0)
ROI_SELECTED_PEN = QPen(QColor(255, 214, 0), 0)
HANDLE_BRUSH = QBrush(QColor(255, 214, 0))
HANDLE_SIZE_PX = 9.0


class ResizeHandle(QGraphicsRectItem):
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


class NodeHandle(QGraphicsRectItem):
    """Grip on one contour vertex; dragging reshapes that vertex."""

    def __init__(self, parent, index):
        half = HANDLE_SIZE_PX / 2
        super().__init__(-half, -half, HANDLE_SIZE_PX, HANDLE_SIZE_PX,
                         parent)
        self._index = index
        self.setBrush(HANDLE_BRUSH)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event):
        self.parentItem()._dragging = True
        event.accept()

    def mouseMoveEvent(self, event):
        self.parentItem().move_node(self._index, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        parent = self.parentItem()
        parent.commit_geometry()
        parent._dragging = False
        event.accept()


class RotateHandle(QGraphicsEllipseItem):
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
