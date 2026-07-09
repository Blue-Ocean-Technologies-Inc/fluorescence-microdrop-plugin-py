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

# Image type constants
ASI_IMG_RAW8 = 0
ASI_IMG_RGB24 = 1
ASI_IMG_RAW16 = 2
ASI_IMG_Y8 = 3

# Control type constants (subset used here)
ASI_GAIN = 0
ASI_EXPOSURE = 1


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

    def init_camera(self):
        """Initialize: full-resolution RAW16, no binning, origin at (0, 0)."""
        if not self.is_open:
            return False
        result = self.asidll.ASIInitCamera(self.camera_id)
        if result != 0:
            logger.error(f"Failed to initialize camera: {result}")
            return False
        result = self.asidll.ASISetROIFormat(
            self.camera_id, self.camera_info.MaxWidth,
            self.camera_info.MaxHeight, 1, ASI_IMG_RAW16)
        if result != 0:
            logger.error(f"Failed to set ROI format: {result}")
            return False
        result = self.asidll.ASISetStartPos(self.camera_id, 0, 0)
        if result != 0:
            logger.error(f"Failed to set start position: {result}")
            return False
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

        width = self.camera_info.MaxWidth
        height = self.camera_info.MaxHeight
        buffer_size = width * height * 2  # RAW16: 2 bytes per pixel
        buffer = create_string_buffer(buffer_size)

        result = self.asidll.ASIGetDataAfterExp(self.camera_id, buffer, buffer_size)
        if result == 0:
            img = np.frombuffer(buffer, dtype=np.uint16).reshape((height, width))
            if self.camera_info.IsColorCam:
                img = self.debayer_image(img)
            if self.camera_info.BitDepth == 12:
                img = img >> 4
            return img
        return None


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
