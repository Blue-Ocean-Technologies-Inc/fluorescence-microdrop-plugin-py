"""ASI camera-source provider for the device viewer's video layer.

Contributed to the ``device_viewer.camera_sources`` extension point: ASI
cameras appear in the device viewer's own camera dropdown and render
through the same video item as UVC cameras — inheriting the perspective
alignment under the electrode layer. The feed wraps ASIVideoThread and
exposes live exposure/gain controls.
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

from logger.logger_service import get_logger

from .asi_thread import ASIVideoThread, frame_to_qimage
from .consts import (
    ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX, ASI_EXPOSURE_DEFAULT,
    ASI_GAIN_MIN, ASI_GAIN_MAX, ASI_GAIN_DEFAULT,
)
from .zwoasi import default_asi_sdk_dir, list_asi_cameras

logger = get_logger(__name__)


class AsiCameraFeed(QObject):
    """One live ASI capture: frames out as QImages, plus settings controls.

    The device viewer connects ``frame``/``error`` (queued across the grabber
    thread) and calls ``start``/``stop``; ``create_controls`` supplies the
    exposure/gain row shown while this feed's source is selected.
    """

    frame = Signal(QImage)
    error = Signal(str)

    def __init__(self, sdk_dir, camera_id):
        super().__init__()
        self._thread = ASIVideoThread(
            sdk_dir, camera_id,
            exposure=ASI_EXPOSURE_DEFAULT, gain=ASI_GAIN_DEFAULT)
        self._thread.change_pixmap_signal.connect(
            lambda img: self.frame.emit(frame_to_qimage(img)))
        self._thread.error_signal.connect(self.error)

    def start(self):
        self._thread.start()

    def stop(self):
        self._thread.stop()
        self._thread.wait(3000)

    def create_controls(self, parent) -> QWidget:
        controls = QWidget(parent)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("ASI:", controls))
        exposure = QSpinBox(controls)
        exposure.setRange(ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX)
        exposure.setValue(self._thread.exposure)
        exposure.setSuffix(" µs")
        exposure.setToolTip("ASI exposure time")
        exposure.valueChanged.connect(
            lambda value: self._thread.set_camera_settings(exposure=value))
        row.addWidget(exposure, stretch=1)

        gain = QSpinBox(controls)
        gain.setRange(ASI_GAIN_MIN, ASI_GAIN_MAX)
        gain.setValue(self._thread.gain)
        gain.setPrefix("gain ")
        gain.setToolTip("ASI gain")
        gain.valueChanged.connect(
            lambda value: self._thread.set_camera_settings(gain=value))
        row.addWidget(gain, stretch=1)
        return controls


class AsiCameraSourceProvider:
    """Enumerates ASI cameras and opens feeds for the device viewer."""

    def _sdk_dir(self):
        """The configured SDK directory (preference), falling back to the
        bundled copy. Read lazily so a preference change applies on the
        device viewer's next camera-list refresh."""
        try:
            from apptools.preferences.api import get_default_preferences
            from ..preferences import FluorescencePreferences
            preferences = FluorescencePreferences(
                preferences=get_default_preferences())
            return preferences.fluorescence_asi_sdk_dir or default_asi_sdk_dir()
        except Exception:
            return default_asi_sdk_dir()

    def list_sources(self) -> list:
        return [(f"ASI: {name}", camera_id)
                for camera_id, name in list_asi_cameras(self._sdk_dir())]

    def open(self, camera_id) -> AsiCameraFeed:
        return AsiCameraFeed(self._sdk_dir(), camera_id)
