# fluorescence_controls_ui/image_viewer/analysis/roi_canvas_layer.py
"""Owns the ROI items on the image scene and turns the canvas view's
forwarded mouse events into creation/edit/selection callbacks. Plain
wiring around Qt items, so it stays a plain class; it never touches the
analysis model. The canvas editor points these callbacks at the model's
canvas_* event traits and the controller reacts."""
import math

from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem,
)

from .consts import MIN_ROI_SIZE_PX
from .roi_handles import ROI_SELECTED_PEN
from .roi_items import (
    BoxRoiItem, CapsuleRoiItem, EllipseRoiItem, capsule_path,
)


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
