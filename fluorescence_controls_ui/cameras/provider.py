"""ASI camera-source provider for the device viewer.

Contributed to the ``device_viewer.camera_sources`` extension point: ASI
cameras appear in the device viewer's own camera dropdown, primarily for
CAPTURE — the device viewer renders frames only while the fluorescence
controls pane's "Device View Stream" checkbox is on (rendering
full-resolution sensor frames under the electrodes costs GUI smoothness),
and captures land in the fluorescence image viewer pane regardless.

Exposure/gain and the stream checkbox live in the fluorescence controls
pane only: they are mirrored into the shared ``asi_camera_settings``
singleton and the running feed observes every change.
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from logger.logger_service import get_logger

from .asi_thread import (
    ASIVideoThread, debayered_to_rgb, frame_to_qimage, raw_to_qimage,
    to_display_8bit,
)
from .camera_settings import asi_camera_settings
from .zwoasi import default_asi_sdk_dir, list_asi_cameras

logger = get_logger(__name__)


class AsiCameraFeed(QObject):
    """One live ASI capture: keeps the latest raw sensor frame for
    ``raw_frame()`` captures, previews as QImages while the device-viewer
    stream is on, settings from the shared ASI camera settings (applied
    live while running)."""

    frame = Signal(QImage)
    #: Preview state: the consumer shows its video layer only while True
    #: (emitted on start and whenever the pane's stream checkbox changes).
    streaming = Signal(bool)
    error = Signal(str)

    def __init__(self, sdk_dir, camera_id):
        super().__init__()
        self._last_raw = None
        self._thread = ASIVideoThread(
            sdk_dir, camera_id,
            exposure=asi_camera_settings.exposure,
            gain=asi_camera_settings.gain)
        self._thread.change_pixmap_signal.connect(self._on_thread_frame)
        self._thread.error_signal.connect(self.error)
        asi_camera_settings.observe(self._on_settings_changed, "exposure")
        asi_camera_settings.observe(self._on_settings_changed, "gain")
        asi_camera_settings.observe(self._on_stream_setting_changed,
                                    "device_viewer_stream")

    def _on_thread_frame(self, raw):
        # Queued onto the GUI thread: keep the raw sensor frame for captures.
        # The display conversion is heavy on full-resolution 16-bit frames,
        # so it runs only while the device-viewer stream checkbox is on.
        self._last_raw = raw
        if asi_camera_settings.device_viewer_stream:
            self.frame.emit(
                frame_to_qimage(debayered_to_rgb(to_display_8bit(raw))))

    def _on_stream_setting_changed(self, event):
        self.streaming.emit(event.new)

    def raw_frame(self):
        """The latest unprocessed sensor frame (16-bit) as a lossless
        QImage — saved next to display captures by the device viewer."""
        if self._last_raw is None:
            return None
        return raw_to_qimage(self._last_raw)

    def _on_settings_changed(self, event):
        self._thread.set_camera_settings(
            exposure=asi_camera_settings.exposure,
            gain=asi_camera_settings.gain)

    def start(self):
        # The consumer connects before start(): report the current preview
        # state up front so its video layer matches the pane's checkbox.
        self.streaming.emit(asi_camera_settings.device_viewer_stream)
        self._thread.start()

    def stop(self):
        asi_camera_settings.observe(self._on_settings_changed, "exposure",
                                    remove=True)
        asi_camera_settings.observe(self._on_settings_changed, "gain",
                                    remove=True)
        asi_camera_settings.observe(self._on_stream_setting_changed,
                                    "device_viewer_stream", remove=True)
        self._thread.stop()
        self._thread.wait(3000)


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
