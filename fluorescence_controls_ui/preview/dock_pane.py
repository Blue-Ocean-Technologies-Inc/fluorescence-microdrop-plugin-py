"""Fluorescence camera preview dock pane.

A lean pyface DockPane hosting a native QtMultimedia live view: camera
dropdown (UVC devices via QMediaDevices), start/stop toggle, and a
QVideoWidget. No OpenCV dependency — frame capture/processing (the
standalone app's ASI + perspective-correction pipeline) is a later phase;
this pane is view-only.
"""
from traits.api import Any
from pyface.tasks.dock_pane import DockPane
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget,
)

from microdrop_style.fonts.fontnames import ICON_FONT_FAMILY
from microdrop_style.icons.icons import ICON_PLAY, ICON_STOP, ICON_REFRESH
from logger.logger_service import get_logger

from .consts import (
    PREVIEW_DOCK_PANE_ID, PREVIEW_DOCK_PANE_NAME,
    START_PREVIEW_TOOLTIP, STOP_PREVIEW_TOOLTIP, REFRESH_CAMERAS_TOOLTIP,
)

logger = get_logger(__name__)


class FluorescencePreviewDockPane(DockPane):
    """Live camera view for the fluorescence imaging setup."""

    id = PREVIEW_DOCK_PANE_ID
    name = PREVIEW_DOCK_PANE_NAME

    _camera = Any()
    _session = Any()
    _video_widget = Any()
    _camera_combo = Any()
    _toggle_button = Any()
    _status_label = Any()
    _media_devices = Any()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #
    def create_contents(self, parent):
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        controls_row = QHBoxLayout()
        self._camera_combo = QComboBox(container)
        self._camera_combo.setToolTip("Camera source")
        controls_row.addWidget(self._camera_combo, stretch=1)

        refresh = self._make_button(container, ICON_REFRESH,
                                    REFRESH_CAMERAS_TOOLTIP,
                                    self._refresh_cameras)
        controls_row.addWidget(refresh)

        self._toggle_button = self._make_button(
            container, ICON_PLAY, START_PREVIEW_TOOLTIP, self._toggle_preview)
        self._toggle_button.setCheckable(True)
        controls_row.addWidget(self._toggle_button)
        layout.addLayout(controls_row)

        self._video_widget = QVideoWidget(container)
        layout.addWidget(self._video_widget, stretch=1)

        self._status_label = QLabel("", container)
        layout.addWidget(self._status_label)

        # Follow hot-plug events; keep a reference or the signal dies with
        # the temporary.
        self._media_devices = QMediaDevices(container)
        self._media_devices.videoInputsChanged.connect(self._refresh_cameras)
        self._refresh_cameras()
        return container

    @staticmethod
    def _make_button(parent, glyph, tooltip, on_click):
        button = QToolButton(parent)
        button.setText(glyph)
        button.setFont(QFont(ICON_FONT_FAMILY))
        button.setToolTip(tooltip)
        button.clicked.connect(on_click)
        return button

    # ------------------------------------------------------------------ #
    # Camera control                                                      #
    # ------------------------------------------------------------------ #
    def _refresh_cameras(self):
        """Populate the dropdown with connected cameras (descriptions shown;
        the QCameraDevice rides as item data — only Qt types are safe as
        QVariant)."""
        selected = self._camera_combo.currentText()
        self._camera_combo.clear()
        for device in QMediaDevices.videoInputs():
            self._camera_combo.addItem(device.description(), device)
        if selected:
            index = self._camera_combo.findText(selected)
            if index >= 0:
                self._camera_combo.setCurrentIndex(index)
        has_cameras = self._camera_combo.count() > 0
        self._toggle_button.setEnabled(has_cameras)
        if not has_cameras:
            self._set_status("No cameras found")
        elif not (self._camera and self._camera.isActive()):
            self._set_status("")

    def _toggle_preview(self, checked):
        if checked:
            self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self):
        device = self._camera_combo.currentData()
        if device is None:
            self._toggle_button.setChecked(False)
            self._set_status("No camera selected")
            return
        self._stop_preview()
        self._camera = QCamera(device)
        self._camera.errorOccurred.connect(self._on_camera_error)
        self._session = QMediaCaptureSession()
        self._session.setCamera(self._camera)
        self._session.setVideoOutput(self._video_widget)
        self._camera.start()
        self._toggle_button.setChecked(True)
        self._toggle_button.setText(ICON_STOP)
        self._toggle_button.setToolTip(STOP_PREVIEW_TOOLTIP)
        self._set_status(f"Live: {device.description()}")
        logger.info(f"Camera preview started: {device.description()}")

    def _stop_preview(self):
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
            self._session = None
            logger.info("Camera preview stopped")
        self._toggle_button.setChecked(False)
        self._toggle_button.setText(ICON_PLAY)
        self._toggle_button.setToolTip(START_PREVIEW_TOOLTIP)
        self._set_status("")

    def _on_camera_error(self, error, message):
        logger.error(f"Camera error: {message}")
        self._set_status(f"Camera error: {message}")
        self._stop_preview()

    def _set_status(self, text):
        if self._status_label is not None:
            self._status_label.setText(text)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def destroy(self):
        self._stop_preview()
        super().destroy()
