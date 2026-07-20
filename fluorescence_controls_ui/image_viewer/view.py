"""TraitsUI view for the image viewer pane: the toolbar bound to the model
and the image canvas editor (zoom/pan QGraphicsView rendering the model's
``array`` through the display window, reporting the hovered pixel back).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QSizePolicy,
)
from traitsui.api import (
    BasicEditorFactory, HGroup, Item, RangeEditor, UItem, VGroup, View,
)
from traitsui.qt.editor import Editor as QtEditor

from microdrop_style.icons.icons import (
    ICON_FOLDER_OPEN, ICON_HOME, ICON_NEXT, ICON_PAUSE, ICON_PLAY,
    ICON_PREVIOUS, ICON_REFRESH,
)
from microdrop_utils.traitsui_qt_helpers import (
    HoverScrollEnumEditor, IconButtonEditor, IconToggleEditor,
)

from ..cameras.asi_thread import frame_to_qimage
from .display import stretch_to_8bit


class _ImageView(QGraphicsView):
    """Zoom (wheel, anchored under the cursor) + pan (drag) image view that
    reports the hovered pixel to a callback. Shrinks/grows freely with the
    dock pane (a full-resolution scene would otherwise dictate a huge size
    hint) and keeps the image fitted on resize until the user zooms."""

    def __init__(self, scene, on_hover):
        super().__init__(scene)
        self._on_hover = on_hover
        self._auto_fit = True
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def wheelEvent(self, event):
        self._auto_fit = False
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self._on_hover(int(point.x()), int(point.y()))
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit()

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
        self.control = _ImageView(self._scene, self._on_hover)
        self.object.observe(self._on_window_changed,
                            "auto_contrast, window_min, window_max")
        self.object.observe(self._on_fit_request, "fit_request")

    def dispose(self):
        self.object.observe(self._on_window_changed,
                            "auto_contrast, window_min, window_max",
                            remove=True)
        self.object.observe(self._on_fit_request, "fit_request", remove=True)
        super().dispose()

    def update_editor(self):
        # A new image arrived in `array`: redraw and refit.
        self._redraw()
        self.control.fit()

    def _on_window_changed(self, event):
        self._redraw()   # window edit: keep the user's zoom

    def _on_fit_request(self, event):
        self.control.fit()

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


# Compact icon row; everything else stacks vertically below it so the pane
# stays narrow.
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


ImageViewerView = View(
    VGroup(
        buttons_group,
        # Burst layer: captures land one folder per burst, so navigation
        # is two-level — pick the burst, then the image within it.
        Item("selected_burst", label="Burst",
             editor=HoverScrollEnumEditor(values_name="burst_names"),
             tooltip="Pick a capture burst (one folder per burst; "
                     "'ungrouped' holds legacy flat captures)"),
        Item("burst_number", label="Burst Seek",
             editor=RangeEditor(low=1, high_name="object.max_burst_number",
                                mode="slider"),
             tooltip="Drag through the bursts, oldest to newest"),
        Item("selected_wavelength", label="Wavelength",
             editor=HoverScrollEnumEditor(values_name="wavelength_names"),
             tooltip="Show only captures of one LED wavelength "
                     "(detected from the filenames)"),
        Item("selected_image", label="Image",
             editor=HoverScrollEnumEditor(values_name="image_names"),
             tooltip="Pick an image from the selected burst"),
        Item("image_number", label="Seek",
             editor=RangeEditor(low=1, high_name="object.max_image_number",
                                mode="slider"),
             tooltip="Drag through the burst's images"),

        Item("auto_contrast", label="Auto contrast",
             tooltip="Window the displayed intensities to the 0.1–99.9 "
                     "percentile range (raw 16-bit frames are nearly "
                     "black without it); uncheck to set the window "
                     "manually"),
        Item("window_min", label="Min", enabled_when="not auto_contrast", tooltip="Intensity displayed as black"),
        Item("window_max", label="Max", enabled_when="not auto_contrast", tooltip="Intensity displayed as white"),
        UItem("array", editor=ImageCanvasEditor(), springy=True, resizable=True),
        UItem("pixel_text", style="readonly"),
    ),
    resizable=True,
)
