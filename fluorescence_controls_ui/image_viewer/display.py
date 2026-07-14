"""Pure display helpers for the 16-bit image viewer (hardware/Qt-light,
testable): loading QImages into numpy and window/level stretching."""
import numpy as np
from PySide6.QtGui import QImage

#: Percentiles used by auto-contrast (ignores hot pixels / dark borders).
AUTO_CONTRAST_PERCENTILES = (0.1, 99.9)


def qimage_to_array(image: QImage) -> np.ndarray:
    """A numpy copy of a loaded image: (H, W) uint16 for 16-bit grayscale,
    (H, W) uint8 for 8-bit grayscale, (H, W, 3) uint8 otherwise."""
    if image.format() == QImage.Format_Grayscale16:
        image = image.copy()
        array = np.frombuffer(image.constBits(), dtype=np.uint16)
        stride = image.bytesPerLine() // 2
        return array.reshape(image.height(), stride)[:, :image.width()].copy()
    if image.format() == QImage.Format_Grayscale8:
        image = image.copy()
        array = np.frombuffer(image.constBits(), dtype=np.uint8)
        return array.reshape(image.height(), image.bytesPerLine())[:, :image.width()].copy()
    rgb = image.convertToFormat(QImage.Format_RGB888)
    array = np.frombuffer(rgb.constBits(), dtype=np.uint8)
    return array.reshape(rgb.height(), rgb.bytesPerLine())[:, :rgb.width() * 3] \
        .reshape(rgb.height(), rgb.width(), 3).copy()


def load_image_array(path) -> np.ndarray:
    """Pixel data for an image file via :func:`qimage_to_array`, or None
    when the file is missing/unreadable."""
    image = QImage(str(path))
    if image.isNull():
        return None
    return qimage_to_array(image)


def stretch_to_8bit(array: np.ndarray, auto_contrast: bool = True,
                    window=None) -> np.ndarray:
    """Window a grayscale frame into displayable 8-bit.

    auto_contrast maps the (0.1, 99.9) percentile window onto 0..255 —
    without it a typical fluorescence frame (small bright signal on a dark
    field) renders nearly black. Off = the manual ``window`` (low, high)
    when given, else the full dtype range, linearly.
    """
    if array.ndim != 2:
        return array if array.dtype == np.uint8 else (array >> 8).astype(np.uint8)
    data = array.astype(np.float64)
    if auto_contrast:
        low, high = np.percentile(data, AUTO_CONTRAST_PERCENTILES)
        if high <= low:
            low, high = float(data.min()), float(data.max() or 1)
    elif window is not None:
        low, high = float(window[0]), float(window[1])
    else:
        low, high = 0.0, float(np.iinfo(array.dtype).max)
    if high <= low:
        return np.zeros(array.shape, dtype=np.uint8)
    scaled = np.clip((data - low) / (high - low) * 255.0, 0, 255)
    return scaled.astype(np.uint8)
