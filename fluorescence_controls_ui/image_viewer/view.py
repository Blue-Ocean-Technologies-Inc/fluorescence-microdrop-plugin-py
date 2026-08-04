"""TraitsUI view for the image viewer pane: the toolbar bound to the model
and the image canvas editor (zoom/pan QGraphicsView rendering the model's
``array`` through the display window, reporting the hovered pixel back).
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QSizePolicy,
)
from traits.api import Enum, Float, HasTraits
from traitsui.api import (
    BasicEditorFactory, HGroup, HSplit, Item, Label, RangeEditor, UItem,
    VGroup, View,
)
from traitsui.qt.editor import Editor as QtEditor

from microdrop_style.icons.icons import (
    ICON_CAPSULE, ICON_CHEVRON_LEFT, ICON_CHEVRON_RIGHT, ICON_CIRCLE,
    ICON_CONTOUR, ICON_DELETE, ICON_DELETE_SWEEP, ICON_EDIT,
    ICON_FOLDER_OPEN, ICON_HOME, ICON_NEXT, ICON_PAUSE, ICON_PLAY,
    ICON_PREVIOUS, ICON_RECTANGLE, ICON_REFRESH, ICON_RESET_WRENCH,
    ICON_SAVE, ICON_SHOW_CHART,
)
from microdrop_utils.traitsui_qt_helpers import (
    HoverScrollEnumEditor, IconButtonEditor, IconToggleEditor,
)

from ..cameras.asi_thread import frame_to_qimage
from .analysis.roi_canvas_layer import RoiCanvasLayer
from .display import stretch_to_8bit
from .scale_bar import (
    DEFAULT_UNIT, UNITS, metres_per_pixel, nice_scale,
)
from .scale_layer import ScaleCanvasLayer

#: Inset of the scale bar from the viewport's bottom-left corner.
SCALE_BAR_MARGIN_PX = 12


class ScaleEntry(HasTraits):
    """Modal form asking what the drawn line measures. The dialogs
    wrapper covers message dialogs only, so a two-field form is a
    plain TraitsUI livemodal view."""

    value = Float(1.0)
    unit = Enum(DEFAULT_UNIT, UNITS)

    traits_view = View(
        Item("value", label="Length"),
        Item("unit", label="Units"),
        title="Set image scale", buttons=["OK", "Cancel"],
        kind="livemodal", width=260)


class _ImageView(QGraphicsView):
    """Zoom (wheel, anchored under the cursor) + pan (drag) image view that
    reports the hovered pixel to a callback. Shrinks/grows freely with the
    dock pane (a full-resolution scene would otherwise dictate a huge size
    hint) and keeps the image fitted on resize until the user zooms."""

    def __init__(self, scene, on_hover, roi_layer, scale_layer):
        super().__init__(scene)
        self._on_hover = on_hover
        self._roi_layer = roi_layer
        self._scale_layer = scale_layer
        self._metres_per_pixel = 0.0
        self._show_scale_bar = True
        self._auto_fit = True
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        # Keys only reach a focused widget, and contour drawing needs
        # Enter/Escape/Backspace once the canvas is clicked.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def wheelEvent(self, event):
        self._auto_fit = False
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self._scale_layer.mouse_press(point):
            event.accept()
            return
        if self._roi_layer.mouse_press(point):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self._on_hover(int(point.x()), int(point.y()))
        if self._scale_layer.mouse_move(point):
            event.accept()
            return
        if self._roi_layer.mouse_move(point):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self._scale_layer.mouse_release(point):
            event.accept()
            return
        if self._roi_layer.mouse_release(point):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self._roi_layer.mouse_double_click(point):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        # Contour drawing finishes on Enter and unwinds on Escape /
        # Backspace; everything else falls through to the view.
        if self._roi_layer.key_press(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit()

    def set_scale(self, metres_per_pixel_value, show_bar):
        self._metres_per_pixel = metres_per_pixel_value
        self._show_scale_bar = show_bar
        self.viewport().update()

    def drawForeground(self, painter, rect):
        """Paint the scale bar as a HUD: reset to viewport pixels, then
        ask nice_scale what a bar of about SCALE_BAR_TARGET_PX should
        read at the current zoom."""
        super().drawForeground(painter, rect)
        if not self._show_scale_bar or self._metres_per_pixel <= 0:
            return
        zoom = self.transform().m11()
        if zoom <= 0:
            return
        scale = nice_scale(self._metres_per_pixel / zoom)
        if scale is None:
            return
        bar_px, label = scale
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        viewport = self.viewport().rect()
        left = viewport.left() + SCALE_BAR_MARGIN_PX
        bottom = viewport.bottom() - SCALE_BAR_MARGIN_PX
        painter.fillRect(QRectF(left - 6, bottom - 26, bar_px + 12, 32),
                         QColor(0, 0, 0, 110))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(left, bottom, int(left + bar_px), bottom)
        painter.drawLine(left, bottom - 5, left, bottom)
        painter.drawLine(int(left + bar_px), bottom - 5,
                         int(left + bar_px), bottom)
        painter.drawText(QRectF(left, bottom - 24, bar_px, 18),
                         Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def fit(self):
        if self.scene() is not None and not self.scene().sceneRect().isEmpty():
            self._auto_fit = True
            self.resetTransform()
            self.fitInView(self.scene().sceneRect(),
                           Qt.AspectRatioMode.KeepAspectRatio)


class _ImageCanvasEditor(QtEditor):
    """Canvas bound to the model's ``array``: renders it through the display
    window, refits on every newly loaded image (and on ``fit_request``),
    redraws in place on window edits, and writes the hovered pixel's true
    value back to ``pixel_text``."""

    scrollable = True

    def init(self, parent):
        self._scene = QGraphicsScene()
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._roi_layer = RoiCanvasLayer(self._scene)
        analysis = self.object.roi_analysis
        self._roi_layer.on_roi_created = (
            lambda kind, geometry:
            analysis.trait_set(canvas_roi_created=(kind, geometry)))
        self._roi_layer.on_roi_edited = (
            lambda roi_id, geometry:
            analysis.trait_set(canvas_roi_edited=(roi_id, geometry)))
        self._roi_layer.on_roi_selected = (
            lambda roi_id: analysis.trait_set(selected_roi_id=roi_id))
        self._scale_layer = ScaleCanvasLayer(self._scene)
        self._scale_layer.on_line_drawn = self._on_scale_line_drawn
        self.control = _ImageView(self._scene, self._on_hover,
                                  self._roi_layer, self._scale_layer)
        self.object.observe(self._on_window_changed,
                            "auto_contrast, window_min, window_max")
        self.object.observe(self._on_fit_request, "fit_request")
        self.object.observe(
            self._on_roi_state_changed,
            "current_path, roi_analysis:session, "
            "roi_analysis:session:rois.items, "
            "roi_analysis:session:rois:items:geometry, "
            "roi_analysis:session:rois:items:overrides.items, "
            "roi_analysis:session:rois:items:name, "
            "roi_analysis:session:scale:metres_per_pixel, "
            "roi_analysis:session:scale:show_bar, "
            "roi_analysis:selected_roi_id")
        self.object.observe(self._on_interaction_mode_changed,
                            "roi_analysis:interaction_mode")

    def dispose(self):
        self.object.observe(self._on_window_changed,
                            "auto_contrast, window_min, window_max",
                            remove=True)
        self.object.observe(self._on_fit_request, "fit_request", remove=True)
        self.object.observe(
            self._on_roi_state_changed,
            "current_path, roi_analysis:session, "
            "roi_analysis:session:rois.items, "
            "roi_analysis:session:rois:items:geometry, "
            "roi_analysis:session:rois:items:overrides.items, "
            "roi_analysis:session:rois:items:name, "
            "roi_analysis:session:scale:metres_per_pixel, "
            "roi_analysis:session:scale:show_bar, "
            "roi_analysis:selected_roi_id",
            remove=True)
        self.object.observe(self._on_interaction_mode_changed,
                            "roi_analysis:interaction_mode", remove=True)
        super().dispose()

    def update_editor(self):
        # A new image arrived in `array`: redraw and refit.
        self._redraw()
        self.control.fit()
        self._sync_roi_layer()

    def _on_window_changed(self, event):
        self._redraw()   # window edit: keep the user's zoom

    def _on_fit_request(self, event):
        self.control.fit()

    def _on_roi_state_changed(self, event):
        self._sync_roi_layer()

    def _sync_roi_layer(self):
        model = self.object
        if not model.current_path or model.array is None:
            self._roi_layer.clear_items()
            return
        self._roi_layer.sync(
            model.roi_analysis.session.effective_for(model.current_path),
            model.roi_analysis.selected_roi_id)
        self._push_scale()

    def _push_scale(self):
        """One path for a session swap, a fresh calibration and the
        show/hide toggle."""
        scale = self.object.roi_analysis.session.scale
        self.control.set_scale(scale.metres_per_pixel, scale.show_bar)

    def _on_scale_line_drawn(self, length_px):
        """Ask what the line measures, store the calibration on the
        session, and remember it as the seed for the next experiment."""
        analysis = self.object.roi_analysis
        scale = analysis.session.scale
        entry = ScaleEntry(value=scale.value or 1.0, unit=scale.unit)
        calibration = None
        if entry.edit_traits().result:
            calibration = metres_per_pixel(length_px, entry.value,
                                           entry.unit)
        if calibration is not None:
            scale.trait_set(metres_per_pixel=calibration,
                            value=entry.value, unit=entry.unit)
            preferences = self.object.preferences
            preferences.fluorescence_last_scale_metres_per_px = calibration
            preferences.fluorescence_last_scale_unit = entry.unit
            self._push_scale()
        analysis.interaction_mode = "pan"

    def _on_interaction_mode_changed(self, event):
        mode = event.new
        self._roi_layer.set_mode(mode)
        self._scale_layer.set_mode(mode)
        self.control.setDragMode(
            self.control.DragMode.ScrollHandDrag if mode == "pan"
            else self.control.DragMode.NoDrag)

    def _redraw(self):
        array = self.value
        if array is None:
            self._pixmap_item.setPixmap(QPixmap())
            return
        display = stretch_to_8bit(
            array, self.object.auto_contrast,
            window=(self.object.window_min, self.object.window_max))
        self._pixmap_item.setPixmap(
            QPixmap.fromImage(frame_to_qimage(display)))
        self._scene.setSceneRect(self._pixmap_item.boundingRect())

    def _on_hover(self, x, y):
        array = self.value
        if array is None:
            return
        height, width = array.shape[:2]
        if 0 <= x < width and 0 <= y < height:
            self.object.pixel_text = f"({x}, {y}) = {array[y, x]}"
        else:
            self.object.pixel_text = ""


class ImageCanvasEditor(BasicEditorFactory):
    """Factory for the image canvas over the model's ``array`` trait."""

    klass = _ImageCanvasEditor


# Compact icon row above the image: browse/navigate/playback plus the
# position and folder-info readouts.
buttons_group = HGroup(
    UItem("directory_button", editor=IconButtonEditor(
        glyph=ICON_FOLDER_OPEN,
        tooltip="Choose the image folder (defaults to the experiment's "
                "raw captures)")),
    UItem("home_button", editor=IconButtonEditor(
        glyph=ICON_HOME,
        tooltip="Back to the current experiment's captures (newest image)")),
    UItem("fit_button", editor=IconButtonEditor(
        glyph=ICON_REFRESH, tooltip="Fit image to the pane")),
    UItem("previous_button", editor=IconButtonEditor(
        glyph=ICON_PREVIOUS, tooltip="Previous image")),
    UItem("playing", editor=IconToggleEditor(
        on_glyph=ICON_PAUSE, off_glyph=ICON_PLAY,
        tooltip="Cycle through the folder's images")),
    UItem("next_button", editor=IconButtonEditor(
        glyph=ICON_NEXT, tooltip="Next image")),
    UItem("position_text", style="readonly"),
    UItem("info_text", style="readonly"),
)


# Collapsible sections (fluorescence controls pane parity): an arrow glyph
# header toggles each bordered group's `show_*` trait.
def _collapse_header(trait, label):
    return HGroup(
        UItem(trait, editor=IconToggleEditor()),
        Label(label),
    )


# Experiment layer (collapsed by default): browse another experiment's
# captures without hunting for its folder — pick it and the viewer repoints
# there, then the image-group / image levels reload under it.
experiments_group = VGroup(
    Item("selected_experiment", label="Experiment",
         editor=HoverScrollEnumEditor(values_name="experiment_names"),
         tooltip="Browse another experiment's captures (repoints the viewer "
                 "at that experiment; use Home to return to the ongoing one)"),
    Item("experiment_number", label="Experiment Seek",
         editor=RangeEditor(low=1, high_name="object.max_experiment_number",
                            mode="slider"),
         tooltip="Drag through the experiments, oldest to newest"),
    visible_when="show_experiments",
    show_border=True,
)

# Image-group layer: captures land one folder per group, so navigation is
# two-level — pick the group, then the image within it.
bursts_group = VGroup(
    Item("selected_burst", label="Image Group",
         editor=HoverScrollEnumEditor(values_name="burst_names"),
         tooltip="Pick a capture image group (one folder per group; "
                 "'ungrouped' holds legacy flat captures)"),
    Item("burst_number", label="Image Group Seek",
         editor=RangeEditor(low=1, high_name="object.max_burst_number",
                            mode="slider"),
         tooltip="Drag through the image groups, oldest to newest"),
    visible_when="show_bursts",
    show_border=True,
)

images_group = VGroup(
    Item("selected_wavelength", label="Wavelength",
         editor=HoverScrollEnumEditor(values_name="wavelength_names"),
         tooltip="Show only captures of one LED wavelength "
                 "(detected from the filenames)"),
    Item("selected_image", label="Image",
         editor=HoverScrollEnumEditor(values_name="image_names"),
         tooltip="Pick an image from the selected image group"),
    Item("image_number", label="Seek",
         editor=RangeEditor(low=1, high_name="object.max_image_number",
                            mode="slider"),
         tooltip="Drag through the image group's images"),
    visible_when="show_images",
    show_border=True,
)

contrast_group = VGroup(
    Item("auto_contrast", label="Auto contrast",
         tooltip="Window the displayed intensities to the 0.1–99.9 "
                 "percentile range (raw 16-bit frames are nearly "
                 "black without it); uncheck to set the window "
                 "manually"),
    Item("window_min", label="Min", enabled_when="not auto_contrast",
         tooltip="Intensity displayed as black"),
    Item("window_max", label="Max", enabled_when="not auto_contrast",
         tooltip="Intensity displayed as white"),
    visible_when="show_contrast",
    show_border=True,
)

# ROI analysis: draw/edit tools, then the calculate -> plot -> export
# pipeline over the filtered images, as an always-visible vertical
# toolbar on the image's right edge. Instant/live per-ROI stats show in
# the plot pane's table; batch progress shares the status row under the
# image.
analysis_toolbar = VGroup(
    UItem("object.roi_analysis.draw_ellipse_button",
          editor=IconButtonEditor(
              glyph=ICON_CIRCLE,
              tooltip="Draw an elliptical ROI (click-drag from its "
                      "centre; the grip makes it an ellipse)")),
    UItem("object.roi_analysis.draw_box_button",
          editor=IconButtonEditor(
              glyph=ICON_RECTANGLE,
              tooltip="Draw a rectangular ROI (click-drag on the "
                      "image)")),
    UItem("object.roi_analysis.draw_capsule_button",
          editor=IconButtonEditor(
              glyph=ICON_CAPSULE,
              tooltip="Draw a capsule ROI (click-drag its axis, then "
                      "use the grip for its radius)")),
    UItem("object.roi_analysis.draw_polygon_button",
          editor=IconButtonEditor(
              glyph=ICON_CONTOUR,
              tooltip="Draw a contour ROI (click to place nodes; "
                      "close on the first node, double-click, or "
                      "Enter — Esc cancels, Backspace undoes)")),
    UItem("object.roi_analysis.edit_mode",
          editor=IconToggleEditor(
              on_glyph=ICON_EDIT, off_glyph=ICON_EDIT,
              tooltip="Edit ROIs: drag to move, bottom-right grip to "
                      "resize (Shift keeps an ellipse circular), "
                      "top-left grip to rotate (Shift snaps to 15°), "
                      "drag a node to reshape a contour, click to "
                      "select. Editing on a later image adds a drift "
                      "override from there on")),
    UItem("object.roi_analysis.delete_roi_button",
          editor=IconButtonEditor(
              glyph=ICON_DELETE,
              tooltip="Delete the selected ROI")),
    UItem("object.roi_analysis.clear_rois_button",
          editor=IconButtonEditor(
              glyph=ICON_DELETE_SWEEP,
              tooltip="Remove all ROIs")),
    UItem("object.roi_analysis.calculate_button",
          editor=IconButtonEditor(
              glyph=ICON_SHOW_CHART,
              tooltip="Calculate ROI intensities across the "
                      "filtered images and plot them")),
    UItem("object.roi_analysis.export_csv_button",
          editor=IconButtonEditor(
              glyph=ICON_SAVE,
              tooltip="Export the intensities to the experiment's "
                      "analysis folder (calculates first if "
                      "needed)")),
    UItem("object.roi_analysis.reset_cache_button",
          editor=IconButtonEditor(
              glyph=ICON_RESET_WRENCH,
              tooltip="Reset calculated intensities (optionally "
                      "also the drift overrides)")),
)

# Selector sidebar: the four collapsible sections stacked, hidden as one
# unit by the chevron toggle (device-viewer sidebar parity).
sidebar_group = VGroup(
    _collapse_header("show_experiments", "Experiments"),
    experiments_group,
    _collapse_header("show_bursts", "Image Groups"),
    bursts_group,
    _collapse_header("show_images", "Images"),
    images_group,
    _collapse_header("show_contrast", "Contrast"),
    contrast_group,
    visible_when="show_sidebar",
    scrollable=True,
)


ImageViewerView = View(
    HGroup(
        VGroup(UItem("show_sidebar", editor=IconToggleEditor(
            on_glyph=ICON_CHEVRON_LEFT, off_glyph=ICON_CHEVRON_RIGHT,
            tooltip="Hide or show the selector sidebar"))),
        HSplit(
            sidebar_group,
            VGroup(
                buttons_group,
                UItem("array", editor=ImageCanvasEditor(), springy=True,
                      resizable=True),
                HGroup(
                    UItem("pixel_text", style="readonly"),
                    UItem("object.roi_analysis.progress_text",
                          style="readonly"),
                ),
            ),
        ),
        analysis_toolbar,
    ),
    resizable=True,
)
