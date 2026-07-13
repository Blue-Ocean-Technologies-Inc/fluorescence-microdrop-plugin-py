"""ASI camera frame-grabber thread + display-conversion helpers.

Port of the standalone app's ``ASIVideoThread``: open/init the camera on the
thread, loop single-frame captures, emit each frame as a numpy array. The
display helpers are pure functions so they stay hardware-free testable.
"""
import math
import threading
import time

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from logger.logger_service import get_logger

from .consts import (
    ASI_EXPOSURE_MIN, ASI_GAIN_MIN, AUTO_BRIGHTNESS_TOLERANCE,
    AUTO_MAX_EXPOSURE_MS_DEFAULT, AUTO_MAX_GAIN_DEFAULT,
    AUTO_TARGET_BRIGHTNESS_DEFAULT, TEMPERATURE_POLL_INTERVAL_S,
)
from .zwoasi import (
    ASI_BANDWIDTHOVERLOAD, ASI_FLIP, ASI_FLIP_VALUES, ASI_HARDWARE_BIN,
    ASI_HIGH_SPEED_MODE, ASI_IMG_TYPES, ASI_MONO_BIN, ASI_OFFSET,
    ASI_TEMPERATURE, ASI_WB_B, ASI_WB_R, ASICamera, ASIError,
)

logger = get_logger(__name__)

#: Give up after this many consecutive failed frames (standalone behavior).
MAX_FRAME_ERRORS = 5

#: Advanced setting name -> SDK control type, for plain value controls.
#: ROI-shaping settings (binning / image_type / resolution) are handled
#: separately: they go through ASICamera.set_roi between frames.
ADVANCED_CONTROL_TYPES = {
    "white_balance_red": ASI_WB_R,
    "white_balance_blue": ASI_WB_B,
    "offset": ASI_OFFSET,
    "usb_bandwidth": ASI_BANDWIDTHOVERLOAD,
    "high_speed_mode": ASI_HIGH_SPEED_MODE,
    "hardware_bin": ASI_HARDWARE_BIN,
    "mono_bin": ASI_MONO_BIN,
    "flip": ASI_FLIP,
}

ROI_SETTING_NAMES = ("binning", "image_type", "resolution")

#: Advanced settings the camera itself consumes; the rest (the display_*
#: trio) are software post-processing the feed applies to the preview.
THREAD_APPLIED_SETTINGS = (
    frozenset(ADVANCED_CONTROL_TYPES) | frozenset(ROI_SETTING_NAMES))


def parse_resolution(resolution):
    """(width, height) from the UI's resolution value: "1920x1080" ->
    (1920, 1080); "full" / unset -> (None, None) = the full binned frame."""
    if not resolution or resolution == "full":
        return None, None
    width, _, height = resolution.partition("x")
    return int(width), int(height)


def display_adjust_lut(gamma: float, contrast: float,
                       brightness: float) -> np.ndarray:
    """256-entry uint8 lookup table for the display adjustments (like the
    ZWO native app's image panel): brightness multiplies, contrast scales
    around mid-gray, gamma curves — 1.0 is neutral for all three. Applied
    to 8-bit display frames only, never to the raw capture data."""
    values = np.arange(256, dtype=np.float64) / 255.0
    values = values * brightness
    values = (values - 0.5) * contrast + 0.5
    values = np.clip(values, 0.0, 1.0) ** (1.0 / gamma)
    return (values * 255.0 + 0.5).astype(np.uint8)


def to_display_8bit(img: np.ndarray) -> np.ndarray:
    """16-bit sensor frames scaled for display (standalone heuristic: full
    16-bit range when values exceed 12 bits, else treat as 12-bit data).
    8-bit frames pass through untouched."""
    if img.dtype == np.uint16:
        if img.max() > 2 ** 12:
            return (img / 256).astype(np.uint8)
        return (img / 16).astype(np.uint8)
    return img


def debayered_to_rgb(img: np.ndarray) -> np.ndarray:
    """Channel-swap a debayered color frame to RGB; mono frames pass through.

    The capture path's OpenCV Bayer code leaves color frames in BGR order
    (OpenCV names Bayer codes by the opposite corner of the 2x2 tile), so
    the standalone UI swapped channels before display and its BGR-order
    image writer swapped again on save — both ended up true-color. Every
    display/save conversion here goes through this swap to match."""
    if img.ndim == 3:
        return img[:, :, ::-1]
    return img


def raw_to_qimage(img: np.ndarray) -> QImage:
    """A lossless QImage from a raw sensor frame: 16-bit grayscale stays
    Grayscale16; 16-bit color (debayered) becomes RGBA64; 8-bit data
    falls through to the display path."""
    frame = np.ascontiguousarray(debayered_to_rgb(img))
    height, width = frame.shape[:2]
    if frame.dtype == np.uint16 and frame.ndim == 2:
        qimage = QImage(frame.data, width, height, frame.strides[0],
                        QImage.Format_Grayscale16)
        return qimage.copy()
    if frame.dtype == np.uint16 and frame.ndim == 3:
        # Pad to RGBA64 (alpha opaque) — Qt has no 48-bit RGB format.
        rgba = np.empty((height, width, 4), dtype=np.uint16)
        rgba[:, :, :3] = frame
        rgba[:, :, 3] = 65535
        qimage = QImage(rgba.data, width, height, rgba.strides[0],
                        QImage.Format_RGBA64)
        return qimage.copy()
    return frame_to_qimage(to_display_8bit(frame))


def frame_to_qimage(img: np.ndarray) -> QImage:
    """A display QImage from an 8-bit grayscale (H, W) or RGB (H, W, 3)
    frame. Copies, so the QImage outlives the source buffer."""
    frame = np.ascontiguousarray(img)
    height, width = frame.shape[:2]
    if frame.ndim == 2:
        qimage = QImage(frame.data, width, height, frame.strides[0],
                        QImage.Format_Grayscale8)
    else:
        qimage = QImage(frame.data, width, height, frame.strides[0],
                        QImage.Format_RGB888)
    return qimage.copy()


class ASIVideoThread(QThread):
    """Grabs frames from an ASI camera and emits them for display."""

    change_pixmap_signal = Signal(np.ndarray)
    #: Camera capabilities (CAMERA_CAPS_TRAITS dict), emitted once after
    #: init so the UI can narrow its choices to what the camera supports.
    camera_caps_signal = Signal(dict)
    #: Sensor temperature in degrees C, polled every few seconds.
    temperature_signal = Signal(float)
    #: The operating (exposure_us, gain) while software auto-exposure /
    #: auto-gain is on — emitted every frame so the UI can adopt the
    #: converged values when the user toggles auto off.
    auto_values_signal = Signal(int, int)
    error_signal = Signal(str)

    def __init__(self, sdk_dir, camera_index, exposure=20000, gain=300,
                 advanced=None):
        super().__init__()
        self.sdk_dir = sdk_dir
        self.camera_index = camera_index
        self.camera = None
        self.running = True
        self.exposure = exposure   # microseconds
        self.gain = gain
        # Advanced settings (controls + ROI format) queue up here and are
        # applied on THIS thread between frames — the SDK forbids ROI
        # changes during an exposure. The initial dict is applied right
        # after camera init, before the first frame.
        self._advanced_lock = threading.Lock()
        self._pending_advanced = dict(advanced or {})
        # The full ROI trio must be re-sent together, so remember the
        # last-applied values to fill in whichever the change omits.
        self._roi_settings = {
            name: self._pending_advanced.get(name)
            for name in ROI_SETTING_NAMES}
        # Software auto-exposure state (see _auto_adjust; the GUI thread
        # updates these via set_auto_settings — plain attribute writes).
        self.auto_exposure = False
        self.auto_gain = False
        self.auto_target_brightness = AUTO_TARGET_BRIGHTNESS_DEFAULT
        self.auto_max_gain = AUTO_MAX_GAIN_DEFAULT
        self.auto_max_exposure = AUTO_MAX_EXPOSURE_MS_DEFAULT * 1_000
        self._last_temperature_poll = 0.0

    def set_camera_settings(self, exposure=None, gain=None):
        """Update live capture settings (applied by the running camera)."""
        if exposure is not None:
            self.exposure = exposure
        if gain is not None:
            self.gain = gain
        if self.camera:
            try:
                self.camera.set_camera_settings(exposure=self.exposure,
                                                gain=self.gain)
            except Exception as e:
                logger.warning(f"Error setting camera parameters: {e}")

    def set_advanced_settings(self, **settings):
        """Queue advanced setting changes (any of ADVANCED_CONTROL_TYPES
        keys, binning, image_type, resolution); the capture loop applies
        them before the next frame."""
        with self._advanced_lock:
            self._pending_advanced.update(settings)

    def set_auto_settings(self, **settings):
        """Update the software auto-exposure parameters (AUTO_SETTING_TRAITS
        names); the loop reads them before each adjustment step."""
        for name, value in settings.items():
            setattr(self, name, value)

    def _apply_pending_advanced(self):
        with self._advanced_lock:
            pending = self._pending_advanced
            self._pending_advanced = {}
        if not pending:
            return
        for name, value in pending.items():
            if name in ROI_SETTING_NAMES:
                continue
            control_type = ADVANCED_CONTROL_TYPES.get(name)
            if control_type is None:
                logger.warning(f"Unknown advanced camera setting {name!r}")
                continue
            if name == "flip":
                value = ASI_FLIP_VALUES[value]
            self.camera.set_control_value(control_type, int(value))
        if any(pending.get(name) is not None for name in ROI_SETTING_NAMES):
            self._roi_settings.update(
                {name: pending[name] for name in ROI_SETTING_NAMES
                 if pending.get(name) is not None})
            width, height = parse_resolution(self._roi_settings["resolution"])
            self.camera.set_roi(
                binning=self._roi_settings["binning"] or 1,
                img_type=ASI_IMG_TYPES[
                    self._roi_settings["image_type"] or "raw16"],
                width=width, height=height)
            # Remember what the camera actually accepted (unsupported
            # requests fall back inside set_roi), so a later change to one
            # setting doesn't re-request — and re-warn about — the others.
            # The resolution request is kept as-is: "full" should stay
            # full across binning changes.
            img_type_names = {value: name
                              for name, value in ASI_IMG_TYPES.items()}
            self._roi_settings["binning"] = self.camera.roi_binning
            self._roi_settings["image_type"] = img_type_names[
                self.camera.roi_img_type]

    def run(self):
        try:
            time.sleep(0.1)   # avoid connection conflicts right after enumeration
            self.camera = ASICamera(self.sdk_dir)
            if not self.camera.open_camera(self.camera_index):
                raise ASIError("Failed to open ASI camera")
            time.sleep(0.1)
            if not self.camera.init_camera():
                raise ASIError("Failed to initialize ASI camera")
            time.sleep(0.1)
            self.camera.set_camera_settings(exposure=self.exposure, gain=self.gain)

            img_type_names = {value: name
                              for name, value in ASI_IMG_TYPES.items()}
            self.camera_caps_signal.emit({
                "camera_max_width": int(self.camera.camera_info.MaxWidth),
                "camera_max_height": int(self.camera.camera_info.MaxHeight),
                "camera_is_color": bool(self.camera.camera_info.IsColorCam),
                "camera_supported_bins": self.camera.supported_bins(),
                "camera_supported_image_types": [
                    img_type_names[img_type]
                    for img_type in self.camera.supported_img_types()
                    if img_type in img_type_names],
            })

            frame_error_count = 0
            while self.running:
                try:
                    self._apply_pending_advanced()
                    img = self.camera.capture_image()
                    if img is not None:
                        frame_error_count = 0
                        # Raw sensor data (16-bit for RAW16 cameras): the
                        # consumer converts for display and can keep the raw
                        # frame for captures.
                        self.change_pixmap_signal.emit(img)
                        self._auto_adjust(img)
                        if self.auto_exposure or self.auto_gain:
                            self.auto_values_signal.emit(
                                self.exposure, self.gain)
                        self._poll_temperature()
                    else:
                        frame_error_count += 1
                        logger.warning(
                            f"ASI frame capture failed "
                            f"({frame_error_count}/{MAX_FRAME_ERRORS})")
                        if frame_error_count >= MAX_FRAME_ERRORS:
                            self.error_signal.emit(
                                "ASI camera stopped providing frames")
                            break
                        time.sleep(0.1)
                except Exception as e:
                    frame_error_count += 1
                    logger.error(
                        f"Error capturing ASI frame: {e} "
                        f"({frame_error_count}/{MAX_FRAME_ERRORS})")
                    if frame_error_count >= MAX_FRAME_ERRORS:
                        self.error_signal.emit(
                            f"Repeated errors during ASI capture: {e}")
                        break
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"ASI camera initialization error: {e}", exc_info=True)
            self.error_signal.emit(f"ASI camera initialization error: {e}")
        finally:
            self.cleanup_camera()

    def _auto_adjust(self, img):
        """Software auto-exposure/auto-gain, one step per frame: nudge the
        frame's 8-bit display mean toward the target (native-app Auto tab
        semantics), exposure first, gain when exposure hits its limit.

        The SDK's own auto controls only iterate in video-capture mode,
        which this snapshot-based loop doesn't use — hence software."""
        if not (self.auto_exposure or self.auto_gain):
            return
        mean = float(to_display_8bit(img).mean())
        target = float(self.auto_target_brightness)
        if abs(mean - target) <= AUTO_BRIGHTNESS_TOLERANCE:
            return
        # Brightness scales ~linearly with exposure and exponentially with
        # gain (0.1 dB units); bound the per-frame step so noisy frames
        # can't cause oscillation.
        ratio = min(max(target / max(mean, 1.0), 0.5), 2.0)
        if self.auto_exposure:
            new_exposure = int(min(max(self.exposure * ratio,
                                       ASI_EXPOSURE_MIN),
                                   self.auto_max_exposure))
            if new_exposure != self.exposure:
                logger.debug(f"Auto exposure: mean {mean:.0f} -> target "
                             f"{target:.0f}, exposure {new_exposure} us")
                self.set_camera_settings(exposure=new_exposure)
                return
        if self.auto_gain:
            step = int(60 * math.log2(ratio))
            if step == 0:
                step = 1 if ratio > 1 else -1
            new_gain = int(min(max(self.gain + step, ASI_GAIN_MIN),
                               self.auto_max_gain))
            if new_gain != self.gain:
                logger.debug(f"Auto gain: mean {mean:.0f} -> target "
                             f"{target:.0f}, gain {new_gain}")
                self.set_camera_settings(gain=new_gain)

    def _poll_temperature(self):
        """Report the sensor temperature every few seconds (the SDK's
        ASI_TEMPERATURE control returns 10 * degrees C, read-only)."""
        now = time.monotonic()
        if now - self._last_temperature_poll < TEMPERATURE_POLL_INTERVAL_S:
            return
        self._last_temperature_poll = now
        value = self.camera.get_control_value(ASI_TEMPERATURE)
        if value is not None:
            self.temperature_signal.emit(value / 10.0)

    def cleanup_camera(self):
        if self.camera:
            try:
                self.camera.close_camera()
                logger.info("ASI camera closed")
            except Exception as e:
                logger.error(f"Error closing ASI camera: {e}")
            self.camera = None

    def stop(self):
        """Signal the capture loop to stop; the loop cleans up on exit."""
        self.running = False
