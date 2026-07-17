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
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage, QPainter

from logger.logger_service import get_logger

from .asi_thread import (
    ASIVideoThread, THREAD_APPLIED_SETTINGS, debayered_to_rgb,
    display_adjust_lut, frame_to_qimage, raw_to_qimage, to_display_8bit,
)
from .camera_settings import (
    ADVANCED_CAMERA_TRAITS, AUTO_SETTING_TRAITS, asi_camera_settings,
)
from .consts import DEVICE_VIEWER_STREAM_MAX_FPS, DEVICE_VIEWER_STREAM_MAX_WIDTH
from .zwoasi import default_asi_sdk_dir, list_asi_cameras

logger = get_logger(__name__)

#: The most-recently-opened running feed (module-level registry): the
#: burst capture service reads the active camera's raw frames through
#: this, without the device viewer having to hand it a reference.
_ACTIVE_FEED = None


def current_feed():
    """The active `AsiCameraFeed`, or None while no camera is running."""
    return _ACTIVE_FEED


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
        #: Bumped on every raw frame (before `_last_raw` is stored), so a
        #: capture can wait for a frame strictly newer than one it saw.
        self.frame_seq = 0
        self._last_preview_time = 0.0
        # Display-adjustment LUT cache (rebuilt when the trio changes).
        self._display_lut = None
        self._display_lut_key = None
        self._thread = ASIVideoThread(
            sdk_dir, camera_id,
            exposure=asi_camera_settings.exposure,
            gain=asi_camera_settings.gain,
            advanced={name: getattr(asi_camera_settings, name)
                      for name in ADVANCED_CAMERA_TRAITS
                      if name in THREAD_APPLIED_SETTINGS})
        self._thread.set_auto_settings(**{
            name: getattr(asi_camera_settings, name)
            for name in AUTO_SETTING_TRAITS})
        self._thread.change_pixmap_signal.connect(self._on_thread_frame)
        self._thread.camera_caps_signal.connect(self._on_camera_caps)
        self._thread.temperature_signal.connect(self._on_camera_temperature)
        self._thread.auto_values_signal.connect(self._on_auto_values)
        self._thread.error_signal.connect(self.error)
        asi_camera_settings.observe(self._on_settings_changed, "exposure")
        asi_camera_settings.observe(self._on_settings_changed, "gain")
        asi_camera_settings.observe(self._on_stream_setting_changed,
                                    "device_viewer_stream")
        asi_camera_settings.observe(self._on_advanced_setting_changed,
                                    ",".join(ADVANCED_CAMERA_TRAITS))
        asi_camera_settings.observe(self._on_auto_setting_changed,
                                    ",".join(AUTO_SETTING_TRAITS))
        # Register as the active feed for the burst capture service
        # (current_feed()) — the most recently opened feed wins.
        global _ACTIVE_FEED
        _ACTIVE_FEED = self

    def _on_thread_frame(self, raw):
        # Queued onto the GUI thread: keep the raw sensor frame for captures.
        # The display conversion is heavy on full-resolution 16-bit frames,
        # so it runs only while the device-viewer stream checkbox is on —
        # rate-capped and downscaled to preview size (captures keep the
        # full-rate, full-resolution raw frames).
        self.frame_seq += 1
        self._last_raw = raw
        if not asi_camera_settings.device_viewer_stream:
            return
        now = time.monotonic()
        if now - self._last_preview_time < 1.0 / DEVICE_VIEWER_STREAM_MAX_FPS:
            return
        self._last_preview_time = now
        # Stride-subsample to roughly the viewport's size BEFORE converting
        # (the frame is already debayered/mono here, so striding is safe).
        preview = raw
        stride = max(1, raw.shape[1] // DEVICE_VIEWER_STREAM_MAX_WIDTH)
        if stride > 1:
            preview = raw[::stride, ::stride]
        image = frame_to_qimage(debayered_to_rgb(
            self._apply_display_adjustments(to_display_8bit(preview))))
        if asi_camera_settings.add_timestamp:
            image = self._stamp_timestamp(image)
        self.frame.emit(image)

    def _apply_display_adjustments(self, img):
        """Preview-only gamma/contrast/brightness (the pane's display
        trio), via a cached LUT. Raw captures are never touched."""
        key = (asi_camera_settings.display_gamma,
               asi_camera_settings.display_contrast,
               asi_camera_settings.display_brightness)
        if key == (1.0, 1.0, 1.0):
            return img
        if key != self._display_lut_key:
            self._display_lut = display_adjust_lut(*key)
            self._display_lut_key = key
        return self._display_lut[img]

    def _on_stream_setting_changed(self, event):
        self.streaming.emit(event.new)

    def raw_frame(self):
        """The latest unprocessed sensor frame (16-bit) as a lossless
        QImage — saved next to display captures by the device viewer."""
        if self._last_raw is None:
            return None
        return raw_to_qimage(self._last_raw)

    def wait_for_frame_after(self, seq: int, timeout: float) -> bool:
        """Block (worker thread) until a frame newer than ``seq`` lands."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.frame_seq > seq and self._last_raw is not None:
                return True
            time.sleep(0.02)
        return False

    def _on_settings_changed(self, event):
        self._thread.set_camera_settings(
            exposure=asi_camera_settings.exposure,
            gain=asi_camera_settings.gain)

    @staticmethod
    def _stamp_timestamp(image):
        """Draw the current time onto a preview frame (display-only; the
        raw captures are never stamped)."""
        image = image.convertToFormat(QImage.Format_RGB888)
        text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        painter = QPainter(image)
        font = painter.font()
        font.setPointSize(max(10, image.height() // 60))
        painter.setFont(font)
        # Shadowed for readability on any background.
        painter.setPen(QColor("black"))
        painter.drawText(11, font.pointSize() * 2 + 1, text)
        painter.setPen(QColor("white"))
        painter.drawText(10, font.pointSize() * 2, text)
        painter.end()
        return image

    def _on_advanced_setting_changed(self, event):
        # The display_* trio and add_timestamp never reach the camera —
        # the preview conversion reads them live from the settings.
        if event.name in THREAD_APPLIED_SETTINGS:
            self._thread.set_advanced_settings(**{event.name: event.new})

    def _on_auto_setting_changed(self, event):
        self._thread.set_auto_settings(**{event.name: event.new})

    def _on_camera_temperature(self, degrees_c):
        asi_camera_settings.camera_temperature = degrees_c

    def _on_auto_values(self, exposure_us, gain):
        # Queued onto the GUI thread: the capture thread's operating
        # values while auto runs. Traits only notify on real changes, so
        # the per-frame report is cheap.
        asi_camera_settings.trait_set(auto_current_exposure=exposure_us,
                                      auto_current_gain=gain)

    def _on_camera_caps(self, caps):
        # Queued onto the GUI thread: the advanced pane narrows its
        # dropdowns to these (kept after stop — the camera rarely changes).
        asi_camera_settings.trait_set(**caps)

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
        asi_camera_settings.observe(self._on_advanced_setting_changed,
                                    ",".join(ADVANCED_CAMERA_TRAITS),
                                    remove=True)
        asi_camera_settings.observe(self._on_auto_setting_changed,
                                    ",".join(AUTO_SETTING_TRAITS),
                                    remove=True)
        self._thread.stop()
        self._thread.wait(3000)
        # Only clear the registry if a newer feed hasn't already taken
        # over (this feed's stop() must not evict a feed opened after it).
        global _ACTIVE_FEED
        if _ACTIVE_FEED is self:
            _ACTIVE_FEED = None


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
