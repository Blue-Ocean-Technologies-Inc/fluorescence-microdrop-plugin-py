"""Fluorescence camera preview dock pane.

Live view for two camera families:

* UVC cameras — native QtMultimedia (QCamera -> QMediaCaptureSession ->
  QVideoWidget), enumerated via QMediaDevices with hot-plug refresh.
* ZWO ASI cameras — the vendored SDK (path set in Fluorescence
  preferences); frames are grabbed by ASIVideoThread and painted onto a
  QLabel, with live exposure/gain spinners.

Sources ride in a plain Python list parallel to the dropdown (only Qt types
are safe as QVariant item data).
"""
from traits.api import Any, List
from pyface.tasks.dock_pane import DockPane
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSpinBox, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from microdrop_style.fonts.fontnames import ICON_FONT_FAMILY
from microdrop_style.icons.icons import ICON_PLAY, ICON_STOP, ICON_REFRESH
from logger.logger_service import get_logger

from ..cameras.asi_thread import ASIVideoThread, frame_to_qimage
from ..cameras.zwoasi import list_asi_cameras
from .consts import (
    PREVIEW_DOCK_PANE_ID, PREVIEW_DOCK_PANE_NAME,
    START_PREVIEW_TOOLTIP, STOP_PREVIEW_TOOLTIP, REFRESH_CAMERAS_TOOLTIP,
    ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX, ASI_EXPOSURE_DEFAULT,
    ASI_GAIN_MIN, ASI_GAIN_MAX, ASI_GAIN_DEFAULT,
)

logger = get_logger(__name__)


class FluorescencePreviewDockPane(DockPane):
    """Live camera view for the fluorescence imaging setup."""

    id = PREVIEW_DOCK_PANE_ID
    name = PREVIEW_DOCK_PANE_NAME

    _camera = Any()
    _session = Any()
    _asi_thread = Any()
    _display_stack = Any()
    _video_widget = Any()
    _frame_label = Any()
    _camera_combo = Any()
    _toggle_button = Any()
    _exposure_spin = Any()
    _gain_spin = Any()
    _status_label = Any()
    _media_devices = Any()
    #: Parallel to the dropdown rows: ("uvc", QCameraDevice) or
    #: ("asi", camera_id, name).
    _sources = List()

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
        self._camera_combo.currentIndexChanged.connect(self._on_source_changed)
        controls_row.addWidget(self._camera_combo, stretch=1)

        self._exposure_spin = QSpinBox(container)
        self._exposure_spin.setRange(ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX)
        self._exposure_spin.setValue(ASI_EXPOSURE_DEFAULT)
        self._exposure_spin.setSuffix(" µs")
        self._exposure_spin.setToolTip("ASI exposure time")
        self._exposure_spin.valueChanged.connect(self._on_asi_settings_changed)
        controls_row.addWidget(self._exposure_spin)

        self._gain_spin = QSpinBox(container)
        self._gain_spin.setRange(ASI_GAIN_MIN, ASI_GAIN_MAX)
        self._gain_spin.setValue(ASI_GAIN_DEFAULT)
        self._gain_spin.setPrefix("gain ")
        self._gain_spin.setToolTip("ASI gain")
        self._gain_spin.valueChanged.connect(self._on_asi_settings_changed)
        controls_row.addWidget(self._gain_spin)

        refresh = self._make_button(container, ICON_REFRESH,
                                    REFRESH_CAMERAS_TOOLTIP,
                                    self._refresh_cameras)
        controls_row.addWidget(refresh)

        self._toggle_button = self._make_button(
            container, ICON_PLAY, START_PREVIEW_TOOLTIP, self._toggle_preview)
        self._toggle_button.setCheckable(True)
        controls_row.addWidget(self._toggle_button)
        layout.addLayout(controls_row)

        # UVC renders through QtMultimedia; ASI frames paint onto a label.
        self._display_stack = QStackedWidget(container)
        self._video_widget = QVideoWidget(self._display_stack)
        self._display_stack.addWidget(self._video_widget)
        self._frame_label = QLabel(self._display_stack)
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_label.setMinimumSize(1, 1)
        self._display_stack.addWidget(self._frame_label)
        layout.addWidget(self._display_stack, stretch=1)

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
    # Source enumeration                                                   #
    # ------------------------------------------------------------------ #
    def _asi_sdk_dir(self):
        """The configured ASI SDK directory (defaults to the bundled copy)."""
        from ..cameras.zwoasi import default_asi_sdk_dir
        from ..preferences import FluorescencePreferences
        try:
            preferences = FluorescencePreferences(
                preferences=self.task.window.application.preferences_helper.preferences)
            return preferences.fluorescence_asi_sdk_dir
        except Exception:
            return default_asi_sdk_dir()

    def _refresh_cameras(self):
        selected = self._camera_combo.currentText()
        self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        self._sources = []
        for device in QMediaDevices.videoInputs():
            self._sources.append(("uvc", device))
            self._camera_combo.addItem(device.description())
        for camera_id, camera_name in list_asi_cameras(self._asi_sdk_dir()):
            self._sources.append(("asi", camera_id, camera_name))
            self._camera_combo.addItem(f"ASI: {camera_name}")
        if selected:
            index = self._camera_combo.findText(selected)
            if index >= 0:
                self._camera_combo.setCurrentIndex(index)
        self._camera_combo.blockSignals(False)

        has_cameras = self._camera_combo.count() > 0
        self._toggle_button.setEnabled(has_cameras)
        self._on_source_changed()
        if not has_cameras:
            self._set_status("No cameras found")
        elif not self._is_live():
            self._set_status("")

    def _current_source(self):
        index = self._camera_combo.currentIndex()
        if 0 <= index < len(self._sources):
            return self._sources[index]
        return None

    def _on_source_changed(self, *_):
        """Exposure/gain apply to ASI sources only."""
        source = self._current_source()
        is_asi = bool(source) and source[0] == "asi"
        self._exposure_spin.setVisible(is_asi)
        self._gain_spin.setVisible(is_asi)

    def _is_live(self):
        return (self._camera is not None and self._camera.isActive()) or \
               (self._asi_thread is not None and self._asi_thread.isRunning())

    # ------------------------------------------------------------------ #
    # Start / stop                                                         #
    # ------------------------------------------------------------------ #
    def _toggle_preview(self, checked):
        if checked:
            self._start_preview()
        else:
            self._stop_preview()

    def _start_preview(self):
        source = self._current_source()
        if source is None:
            self._toggle_button.setChecked(False)
            self._set_status("No camera selected")
            return
        self._stop_preview()
        if source[0] == "uvc":
            self._start_uvc(source[1])
        else:
            self._start_asi(source[1], source[2])

    def _start_uvc(self, device):
        self._display_stack.setCurrentWidget(self._video_widget)
        self._camera = QCamera(device)
        self._camera.errorOccurred.connect(self._on_camera_error)
        self._session = QMediaCaptureSession()
        self._session.setCamera(self._camera)
        self._session.setVideoOutput(self._video_widget)
        self._camera.start()
        self._mark_started(device.description())

    def _start_asi(self, camera_id, camera_name):
        self._display_stack.setCurrentWidget(self._frame_label)
        self._asi_thread = ASIVideoThread(
            self._asi_sdk_dir(), camera_id,
            exposure=self._exposure_spin.value(),
            gain=self._gain_spin.value())
        self._asi_thread.change_pixmap_signal.connect(self._on_asi_frame)
        self._asi_thread.error_signal.connect(self._on_asi_error)
        self._asi_thread.start()
        self._mark_started(f"ASI: {camera_name}")

    def _mark_started(self, label):
        self._toggle_button.setChecked(True)
        self._toggle_button.setText(ICON_STOP)
        self._toggle_button.setToolTip(STOP_PREVIEW_TOOLTIP)
        self._set_status(f"Live: {label}")
        logger.info(f"Camera preview started: {label}")

    def _stop_preview(self):
        if self._camera is not None:
            self._camera.stop()
            self._camera = None
            self._session = None
            logger.info("Camera preview stopped")
        if self._asi_thread is not None:
            self._asi_thread.stop()
            self._asi_thread.wait(3000)
            self._asi_thread = None
            logger.info("ASI preview stopped")
        self._toggle_button.setChecked(False)
        self._toggle_button.setText(ICON_PLAY)
        self._toggle_button.setToolTip(START_PREVIEW_TOOLTIP)
        self._set_status("")

    # ------------------------------------------------------------------ #
    # Frame / error handling                                               #
    # ------------------------------------------------------------------ #
    def _on_asi_frame(self, img):
        pixmap = QPixmap.fromImage(frame_to_qimage(img))
        self._frame_label.setPixmap(pixmap.scaled(
            self._frame_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _on_asi_settings_changed(self, *_):
        if self._asi_thread is not None:
            self._asi_thread.set_camera_settings(
                exposure=self._exposure_spin.value(),
                gain=self._gain_spin.value())

    def _on_asi_error(self, message):
        logger.error(f"ASI preview error: {message}")
        self._set_status(message)
        self._stop_preview()

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
