"""ASI camera frame-grabber thread + display-conversion helpers.

Port of the standalone app's ``ASIVideoThread``: open/init the camera on the
thread, loop single-frame captures, emit each frame as a numpy array. The
display helpers are pure functions so they stay hardware-free testable.
"""
import time

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from logger.logger_service import get_logger

from .zwoasi import ASICamera, ASIError

logger = get_logger(__name__)

#: Give up after this many consecutive failed frames (standalone behavior).
MAX_FRAME_ERRORS = 5


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
    error_signal = Signal(str)

    def __init__(self, sdk_dir, camera_index, exposure=20000, gain=300):
        super().__init__()
        self.sdk_dir = sdk_dir
        self.camera_index = camera_index
        self.camera = None
        self.running = True
        self.exposure = exposure   # microseconds
        self.gain = gain

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

            frame_error_count = 0
            while self.running:
                try:
                    img = self.camera.capture_image()
                    if img is not None:
                        frame_error_count = 0
                        # Raw sensor data (16-bit for RAW16 cameras): the
                        # consumer converts for display and can keep the raw
                        # frame for captures.
                        self.change_pixmap_signal.emit(img)
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
            logger.error(f"ASI camera initialization error: {e}")
            self.error_signal.emit(f"ASI camera initialization error: {e}")
        finally:
            self.cleanup_camera()

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
