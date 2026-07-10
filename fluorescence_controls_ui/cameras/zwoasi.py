"""ctypes wrapper for the ZWO ASI camera SDK.

Port of the standalone fluorescence app's ``zwoasi.py`` with two changes:
the SDK directory comes from a preference (defaulting to the ``ASI_SDK``
copy bundled with the plugin) instead of the working directory, and OpenCV
is imported lazily only for debayering color sensors (mono cameras never
need it).
"""
import os
import platform
import sys
import time
from ctypes import (
    CDLL, Structure, byref, c_char, c_double, c_float, c_int, c_long,
    create_string_buffer,
)
from pathlib import Path

import numpy as np

from logger.logger_service import get_logger

logger = get_logger(__name__)


class ASI_CAMERA_INFO(Structure):
    _fields_ = [
        ('Name', c_char * 64),
        ('CameraID', c_int),
        ('MaxHeight', c_long),
        ('MaxWidth', c_long),
        ('IsColorCam', c_int),
        ('BayerPattern', c_int),
        ('SupportedBins', c_int * 16),
        ('SupportedVideoFormat', c_int * 8),
        ('PixelSize', c_double),  # in um
        ('MechanicalShutter', c_int),
        ('ST4Port', c_int),
        ('IsCoolerCam', c_int),
        ('IsUSB3Host', c_int),
        ('IsUSB3Camera', c_int),
        ('ElecPerADU', c_float),
        ('BitDepth', c_int),
        ('IsTriggerCam', c_int),
        ('Unused', c_char * 16)
    ]


class ASI_CONTROL_CAPS(Structure):
    _fields_ = [
        ('Name', c_char * 64),
        ('Description', c_char * 128),
        ('MaxValue', c_long),
        ('MinValue', c_long),
        ('DefaultValue', c_long),
        ('IsAutoSupported', c_int),
        ('IsWritable', c_int),
        ('ControlType', c_int),
        ('Unused', c_char * 32),
    ]


# Exposure status constants
ASI_EXP_IDLE = 0
ASI_EXP_WORKING = 1
ASI_EXP_SUCCESS = 2
ASI_EXP_FAILED = 3

# Image type constants (ASI_IMG_TYPE)
ASI_IMG_RAW8 = 0
ASI_IMG_RGB24 = 1
ASI_IMG_RAW16 = 2
ASI_IMG_Y8 = 3

#: Image type by the UI's lowercase name, and bytes per pixel of each.
ASI_IMG_TYPES = {
    "raw8": ASI_IMG_RAW8,
    "rgb24": ASI_IMG_RGB24,
    "raw16": ASI_IMG_RAW16,
    "y8": ASI_IMG_Y8,
}
ASI_IMG_BYTES_PER_PIXEL = {
    ASI_IMG_RAW8: 1,
    ASI_IMG_RGB24: 3,
    ASI_IMG_RAW16: 2,
    ASI_IMG_Y8: 1,
}

# Control type constants (ASI_CONTROL_TYPE)
ASI_GAIN = 0
ASI_EXPOSURE = 1
ASI_GAMMA = 2
ASI_WB_R = 3
ASI_WB_B = 4
ASI_OFFSET = 5
ASI_BANDWIDTHOVERLOAD = 6
ASI_OVERCLOCK = 7
ASI_TEMPERATURE = 8          # read-only, 10 * degrees C
ASI_FLIP = 9
ASI_AUTO_MAX_GAIN = 10
ASI_AUTO_MAX_EXP = 11
ASI_AUTO_TARGET_BRIGHTNESS = 12
ASI_HARDWARE_BIN = 13
ASI_HIGH_SPEED_MODE = 14
ASI_COOLER_POWER_PERC = 15
ASI_TARGET_TEMP = 16
ASI_COOLER_ON = 17
ASI_MONO_BIN = 18
ASI_FAN_ON = 19
ASI_PATTERN_ADJUST = 20
ASI_ANTI_DEW_HEATER = 21

#: Flip value by the UI's lowercase name (ASI_FLIP_STATUS).
ASI_FLIP_VALUES = {"none": 0, "horizontal": 1, "vertical": 2, "both": 3}


def roi_dimensions(max_width, max_height, binning, width=None, height=None):
    """The SDK-legal (width, height) for a centered crop of the binned
    field: None means the full binned frame, requests larger than it are
    clamped, and width % 8 == 0 / height % 2 == 0 are enforced. Shared by
    set_roi and the advanced pane's resolution choices."""
    binned_width = max_width // binning
    binned_height = max_height // binning
    width = binned_width if width is None else min(width, binned_width)
    height = binned_height if height is None else min(height, binned_height)
    return width // 8 * 8, height // 2 * 2


class ASIError(Exception):
    """Base exception class for ASI camera errors"""


class ASIIOError(ASIError):
    """Exception class for all errors returned from the ASI SDK library"""

    def __init__(self, message, error_code=None):
        ASIError.__init__(self, message)
        self.error_code = error_code


class ASICaptureError(ASIError):
    """Exception class for when image capture fails"""

    def __init__(self, message, exposure_status=None):
        ASIError.__init__(self, message)
        self.exposure_status = exposure_status


class ASICamera:
    """Single ASI camera handle over the vendor SDK.

    ``sdk_dir`` is the root of the ASI SDK (the directory holding ``Win/``
    and ``Unix/``); the Fluorescence preferences default it to the copy
    bundled with the plugin.
    """

    def __init__(self, sdk_dir):
        self.camera_id = None
        self.camera_info = None
        self.is_open = False
        self.default_timeout = -1
        # Per-camera control caps ({control_type: ASI_CONTROL_CAPS}) and the
        # active ROI format — populated by open_camera / set_roi.
        self.control_caps = {}
        # Unsupported-capability warnings already logged, so a UI slider the
        # camera lacks warns once instead of on every edit.
        self._warned_unsupported = set()
        self.roi_width = 0
        self.roi_height = 0
        self.roi_binning = 1
        self.roi_img_type = ASI_IMG_RAW16
        self._load_sdk(Path(sdk_dir))

    def _load_sdk(self, sdk_dir):
        """Load the ASI SDK library from ``sdk_dir``."""
        if sys.platform == "win32":
            sdk_path = sdk_dir / "Win"
            dll_name = "ASICamera2.dll"
        elif sys.platform == "darwin":
            sdk_path = sdk_dir / "Unix"
            dll_name = "libASICamera2.dylib.1.37"
            self._symlink_mac_libusb(sdk_path)
        else:  # Linux
            sdk_path = sdk_dir / "Unix"
            dll_name = "libASICamera2.so.1.37"

        arch = ("mac" if sys.platform == "darwin"
                else ("x64" if platform.architecture()[0] == '64bit' else "x86"))
        lib_path = sdk_path / "lib" / arch

        if sys.platform == "win32":
            os.environ["PATH"] = str(lib_path) + os.pathsep + os.environ["PATH"]
        else:
            os.environ["LD_LIBRARY_PATH"] = (
                str(lib_path) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))

        library_path = lib_path / dll_name
        if not library_path.exists():
            raise ASIIOError(f"ASI SDK library not found at: {library_path}")

        self.asidll = CDLL(str(library_path))

    @staticmethod
    def _symlink_mac_libusb(sdk_path):
        """macOS: the SDK dylib needs libusb next to it; link the env's copy."""
        path_conda = Path(sys.prefix) / "lib" / "libusb-1.0.0.dylib"
        path_libusb = None
        if path_conda.exists():
            path_libusb = path_conda
        else:
            for root, _dirs, files in os.walk(sys.prefix):
                for file in files:
                    if file == "libusb-1.0.0.dylib":
                        path_libusb = Path(root) / file
                        break
                if path_libusb is not None:
                    break
        if path_libusb is None:
            raise ASIIOError("libusb-1.0.0.dylib not found")
        link = sdk_path / "lib" / "mac" / "libusb-1.0.0.dylib"
        if link.is_symlink():
            link.unlink()
        link.symlink_to(path_libusb)

    # ------------------------------------------------------------------ #
    # Enumeration / lifecycle                                              #
    # ------------------------------------------------------------------ #
    def get_num_connected_cameras(self):
        return self.asidll.ASIGetNumOfConnectedCameras()

    def get_camera_info(self, camera_id):
        info = ASI_CAMERA_INFO()
        result = self.asidll.ASIGetCameraProperty(byref(info), camera_id)
        if result == 0:
            return info
        return None

    def open_camera(self, camera_id):
        if self.is_open:
            self.close_camera()
        result = self.asidll.ASIOpenCamera(camera_id)
        if result == 0:
            self.camera_id = camera_id
            self.camera_info = self.get_camera_info(camera_id)
            if self.camera_info:
                self.is_open = True
                return True
        return False

    def close_camera(self):
        if self.is_open:
            self.asidll.ASICloseCamera(self.camera_id)
            self.is_open = False
            self.camera_id = None
            self.camera_info = None
            self.control_caps = {}

    def init_camera(self):
        """Initialize: full-resolution RAW16, no binning, centered — and
        read the camera's control caps for later clamped control writes."""
        if not self.is_open:
            return False
        result = self.asidll.ASIInitCamera(self.camera_id)
        if result != 0:
            logger.error(f"Failed to initialize camera: {result}")
            return False
        self.control_caps = self._read_control_caps()
        return self.set_roi()

    # ------------------------------------------------------------------ #
    # Capabilities                                                          #
    # ------------------------------------------------------------------ #
    def _read_control_caps(self):
        """{control_type: ASI_CONTROL_CAPS} for every control the connected
        camera reports (the set varies per model)."""
        num_controls = c_int()
        result = self.asidll.ASIGetNumOfControls(
            self.camera_id, byref(num_controls))
        if result != 0:
            logger.warning(f"Failed to get number of controls: {result}")
            return {}
        caps = {}
        for index in range(num_controls.value):
            control = ASI_CONTROL_CAPS()
            if self.asidll.ASIGetControlCaps(
                    self.camera_id, index, byref(control)) == 0:
                caps[control.ControlType] = control
        return caps

    def supported_bins(self):
        """Binning factors the camera supports (the info array is
        zero-terminated)."""
        bins = []
        for value in self.camera_info.SupportedBins:
            if value == 0:
                break
            bins.append(value)
        return bins

    def supported_img_types(self):
        """Image types the camera supports (the info array is terminated
        by ASI_IMG_END == -1)."""
        img_types = []
        for value in self.camera_info.SupportedVideoFormat:
            if value == -1:
                break
            img_types.append(value)
        return img_types

    # ------------------------------------------------------------------ #
    # Controls                                                              #
    # ------------------------------------------------------------------ #
    def set_control_value(self, control_type, value):
        """Write one control, clamped to the camera's reported range.

        Controls the camera does not report (or reports read-only) are
        skipped with a warning instead of erroring, so one UI can drive
        cameras with different capability sets."""
        if not self.is_open:
            return False
        caps = self.control_caps.get(control_type)
        if caps is None:
            if control_type not in self._warned_unsupported:
                self._warned_unsupported.add(control_type)
                logger.warning(
                    f"Camera does not support control {control_type}; "
                    "skipping (warned once)")
            return False
        if not caps.IsWritable:
            if control_type not in self._warned_unsupported:
                self._warned_unsupported.add(control_type)
                logger.warning(
                    f"Control {caps.Name.decode(errors='replace')} is "
                    "read-only; skipping (warned once)")
            return False
        clamped = max(caps.MinValue, min(caps.MaxValue, int(value)))
        if clamped != int(value):
            logger.warning(
                f"Control {caps.Name.decode(errors='replace')} value {value} "
                f"clamped to camera range [{caps.MinValue}, {caps.MaxValue}]")
        result = self.asidll.ASISetControlValue(
            self.camera_id, control_type, c_long(clamped), 0)
        if result != 0:
            logger.error(f"Failed to set control {control_type}: {result}")
            return False
        return True

    def get_control_value(self, control_type):
        """Current value of one control, or None (e.g. ASI_TEMPERATURE
        returns 10 * degrees C)."""
        if not self.is_open:
            return None
        value = c_long()
        auto = c_int()
        result = self.asidll.ASIGetControlValue(
            self.camera_id, control_type, byref(value), byref(auto))
        if result != 0:
            return None
        return value.value

    # ------------------------------------------------------------------ #
    # ROI format (resolution / binning / image type)                        #
    # ------------------------------------------------------------------ #
    def set_roi(self, binning=1, img_type=ASI_IMG_RAW16, width=None,
                height=None):
        """Set binning, output image type, and a centered crop.

        ``width``/``height`` are the requested crop of the binned field of
        view (None = full binned frame; oversize requests are clamped).
        The SDK requires width % 8 == 0 and height % 2 == 0; start position
        is in binned coordinates. Must not be called during an exposure
        (the capture thread applies changes between frames)."""
        if not self.is_open:
            return False
        if binning not in self.supported_bins():
            logger.warning(
                f"Camera does not support bin {binning} "
                f"(supported: {self.supported_bins()}); keeping bin "
                f"{self.roi_binning}")
            binning = self.roi_binning
        if img_type not in self.supported_img_types():
            # Nearest supported fallback: Y8 (color-cam mono output) and
            # RGB24 requests degrade to RAW8 when available — the same bit
            # depth, just undebayered — else RAW16.
            fallback = (ASI_IMG_RAW8
                        if ASI_IMG_RAW8 in self.supported_img_types()
                        and img_type in (ASI_IMG_Y8, ASI_IMG_RGB24)
                        else ASI_IMG_RAW16)
            logger.warning(
                f"Camera does not support image type {img_type} "
                f"(supported: {self.supported_img_types()}); using "
                f"{fallback}")
            img_type = fallback
        binned_width = self.camera_info.MaxWidth // binning
        binned_height = self.camera_info.MaxHeight // binning
        width, height = roi_dimensions(
            self.camera_info.MaxWidth, self.camera_info.MaxHeight,
            binning, width, height)
        result = self.asidll.ASISetROIFormat(
            self.camera_id, width, height, binning, img_type)
        if result != 0:
            logger.error(
                f"Failed to set ROI format {width}x{height} bin {binning} "
                f"type {img_type}: {result}")
            return False
        result = self.asidll.ASISetStartPos(
            self.camera_id, (binned_width - width) // 2,
            (binned_height - height) // 2)
        if result != 0:
            logger.error(f"Failed to set start position: {result}")
            return False
        self.roi_width = width
        self.roi_height = height
        self.roi_binning = binning
        self.roi_img_type = img_type
        logger.info(
            f"ASI ROI format: {width}x{height}, bin {binning}, "
            f"image type {img_type}")
        return True

    # ------------------------------------------------------------------ #
    # Settings / capture                                                   #
    # ------------------------------------------------------------------ #
    def set_camera_settings(self, gain=0, exposure=100000):
        """Set gain and exposure (exposure in microseconds)."""
        if not self.is_open:
            return False
        result = self.asidll.ASISetControlValue(self.camera_id, ASI_GAIN, gain, False)
        if result != 0:
            logger.error(f"Failed to set gain: {result}")
            return False
        result = self.asidll.ASISetControlValue(self.camera_id, ASI_EXPOSURE, exposure, False)
        if result != 0:
            logger.error(f"Failed to set exposure: {result}")
            return False
        logger.debug(f"Camera settings updated - Gain: {gain}, Exposure: {exposure / 1000} ms")
        return True

    def debayer_image(self, img):
        """Debayer a raw color frame (RGGB). OpenCV is imported lazily: mono
        cameras never need it, and the plugin env may not ship it yet."""
        if not self.camera_info.IsColorCam:
            return img
        try:
            import cv2
        except ImportError:
            logger.warning(
                "OpenCV unavailable: showing the color sensor's raw Bayer "
                "frame as grayscale")
            return img
        return cv2.cvtColor(img, cv2.COLOR_BayerRG2RGB)

    def abort_exposure(self):
        if not self.is_open:
            return False
        try:
            result = self.asidll.ASIStopExposure(self.camera_id)
            if result != 0:
                logger.warning(f"Failed to abort exposure: {result}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error aborting exposure: {e}")
            return False

    def capture_image(self, gain=None, exposure=None):
        """Capture a single frame (RAW16, debayered for color sensors).

        Optionally updates gain / exposure (microseconds) first.
        """
        if not self.is_open:
            return None

        if gain is not None or exposure is not None:
            current_gain = gain if gain is not None else 0
            current_exposure = exposure if exposure is not None else 1000000
            if not self.set_camera_settings(current_gain, current_exposure):
                return None

        result = self.asidll.ASIStartExposure(self.camera_id)
        if result != 0:
            raise ASIIOError(f"Failed to start exposure: {result}")

        # Poll the exposure status at a cadence scaled to the exposure time.
        step_counter = 0
        max_steps = 10
        check_interval = exposure / 1000000 / max_steps if exposure else 0.1
        time.sleep(check_interval)

        while True:
            exp_status = c_int()
            result = self.asidll.ASIGetExpStatus(self.camera_id, byref(exp_status))
            if result != 0:
                raise ASIIOError(f"Failed to get exposure status: {result}")
            if exp_status.value == ASI_EXP_SUCCESS:
                break
            elif exp_status.value == ASI_EXP_FAILED:
                raise ASICaptureError("Exposure failed", exp_status.value)

            step_counter += 1
            if step_counter > max_steps:
                if self.asidll.ASIGetNumOfConnectedCameras() == 0:
                    raise ASIIOError("Camera disconnected!")
                if exp_status.value == ASI_EXP_WORKING:
                    logger.debug(
                        f"Exposure still in progress after {step_counter} checks")
                    time.sleep(0.1)
                    continue
                raise ASICaptureError("Exposure timeout", exp_status.value)
            time.sleep(check_interval)

        result = self.asidll.ASIStopExposure(self.camera_id)
        if result != 0:
            raise ASIIOError(f"Failed to stop exposure: {result}")

        width = self.roi_width
        height = self.roi_height
        img_type = self.roi_img_type
        buffer_size = width * height * ASI_IMG_BYTES_PER_PIXEL[img_type]
        buffer = create_string_buffer(buffer_size)

        result = self.asidll.ASIGetDataAfterExp(self.camera_id, buffer, buffer_size)
        if result != 0:
            return None
        if img_type == ASI_IMG_RAW16:
            img = np.frombuffer(buffer, dtype=np.uint16).reshape((height, width))
            if self.camera_info.IsColorCam:
                img = self.debayer_image(img)
            if self.camera_info.BitDepth == 12:
                img = img >> 4
            return img
        if img_type == ASI_IMG_RAW8:
            img = np.frombuffer(buffer, dtype=np.uint8).reshape((height, width))
            if self.camera_info.IsColorCam:
                img = self.debayer_image(img)
            return img
        if img_type == ASI_IMG_RGB24:
            # Debayered on-camera; BGR channel order like the debayer path,
            # so the shared display/save swap applies unchanged.
            return np.frombuffer(buffer, dtype=np.uint8).reshape(
                (height, width, 3))
        return np.frombuffer(buffer, dtype=np.uint8).reshape((height, width))


def default_asi_sdk_dir() -> str:
    """The ASI SDK bundled with the plugin (the ``ASI_SDK`` directory holding
    ``Win/`` and ``Unix/``), or '' if absent.

    Two locations cover both install modes: inside the package (wheel/conda
    installs force-include it there) and at the repo root (dev checkouts).
    """
    package_root = Path(__file__).resolve().parents[1]
    for candidate in (package_root / "ASI_SDK", package_root.parent / "ASI_SDK"):
        if candidate.is_dir():
            return str(candidate)
    return ""


def list_asi_cameras(sdk_dir) -> list:
    """``[(camera_id, name)]`` for every connected ASI camera, or ``[]`` when
    the SDK directory is unset/invalid or no cameras are attached."""
    if not sdk_dir:
        return []
    try:
        sdk = ASICamera(sdk_dir)
    except ASIError as e:
        logger.info(f"ASI SDK not usable ({e}); skipping ASI enumeration")
        return []
    cameras = []
    for camera_id in range(sdk.get_num_connected_cameras()):
        info = sdk.get_camera_info(camera_id)
        if info is not None:
            cameras.append((camera_id, info.Name.decode(errors="replace")))
    return cameras
