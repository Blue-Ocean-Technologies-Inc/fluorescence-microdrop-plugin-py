"""Canvas layer for the scale calibration: one rubber-banded line whose
length in image pixels is reported on release. Separate from the ROI
layer, which owns creation, editing and selection — a calibration line
is none of those, and is not kept once its length becomes a number."""

import math

from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsLineItem

from .scale_bar import MIN_SCALE_LINE_PX

#: Cosmetic (zoom-independent) pen; amber reads on both bright fields
#: and dark raws, and does not clash with the cyan ROI outlines.
SCALE_PEN = QPen(QColor(255, 193, 7), 0)


class ScaleCanvasLayer:
    """Owns the draft calibration line on the image scene."""

    def __init__(self, scene):
        self._scene = scene
        self._draft = None
        self._press_point = None
        self.mode = "pan"
        self.on_line_drawn = lambda length_px: None

    def set_mode(self, mode):
        if mode != "draw_scale":
            self.clear_draft()
        self.mode = mode

    def clear_draft(self):
        if self._draft is not None:
            self._scene.removeItem(self._draft)
        self._draft = None
        self._press_point = None

    def mouse_press(self, scene_point):
        if self.mode != "draw_scale":
            return False
        self._press_point = scene_point
        self._draft = QGraphicsLineItem()
        self._draft.setPen(SCALE_PEN)
        self._scene.addItem(self._draft)
        return True

    def mouse_move(self, scene_point):
        if self._draft is None:
            return False
        self._draft.setLine(
            self._press_point.x(),
            self._press_point.y(),
            scene_point.x(),
            scene_point.y(),
        )
        return True

    def mouse_release(self, scene_point):
        if self._draft is None:
            return False
        length_px = math.hypot(
            scene_point.x() - self._press_point.x(),
            scene_point.y() - self._press_point.y(),
        )
        self.clear_draft()
        if length_px >= MIN_SCALE_LINE_PX:
            self.on_line_drawn(length_px)
        return True
