"""Shared ASI camera settings — the single source of truth for the ACTIVE
exposure/gain and the device-viewer stream checkbox.

Three parties meet here (all on the GUI thread):

* the fluorescence controls pane holds per-mode values (br_/fl_) and writes
  the current mode's pair here whenever they or the mode change — plus the
  device-viewer stream checkbox;
* the device viewer's ASI settings row edits these traits directly;
* the running ASI feed observes them: exposure/gain changes are applied to
  the camera, and frames are emitted for the device viewer's video layer
  only while device_viewer_stream is on.

The advanced camera controls pane writes the ADVANCED_CAMERA_TRAITS here
the same way; the running feed forwards changes to the capture thread,
which applies them between frames.

Traits only notify on real changes, so the pane <-> settings back-sync
naturally terminates instead of looping.
"""
from traits.api import Bool, Enum, Float, HasTraits, Int, List, Range, Str

from .consts import (
    ASI_BINNING_CHOICES, ASI_EXPOSURE_DEFAULT, ASI_FLIP_CHOICES,
    ASI_GAIN_DEFAULT, ASI_GAIN_MAX, ASI_GAIN_MIN, ASI_IMAGE_TYPE_CHOICES,
    ASI_OFFSET_DEFAULT, ASI_OFFSET_MAX, ASI_OFFSET_MIN,
    ASI_USB_BANDWIDTH_DEFAULT, ASI_USB_BANDWIDTH_MAX, ASI_USB_BANDWIDTH_MIN,
    ASI_WHITE_BALANCE_BLUE_DEFAULT, ASI_WHITE_BALANCE_MAX,
    ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_RED_DEFAULT,
    AUTO_MAX_EXPOSURE_MS_DEFAULT, AUTO_MAX_GAIN_DEFAULT,
    AUTO_TARGET_BRIGHTNESS_DEFAULT, AUTO_TARGET_BRIGHTNESS_MAX,
    AUTO_TARGET_BRIGHTNESS_MIN,
    DISPLAY_BRIGHTNESS_DEFAULT, DISPLAY_BRIGHTNESS_MAX,
    DISPLAY_BRIGHTNESS_MIN, DISPLAY_CONTRAST_DEFAULT, DISPLAY_CONTRAST_MAX,
    DISPLAY_CONTRAST_MIN, DISPLAY_GAMMA_DEFAULT, DISPLAY_GAMMA_MAX,
    DISPLAY_GAMMA_MIN,
)

#: Advanced settings owned by the advanced camera controls pane, with the
#: SAME trait names here, on the pane model, and in preferences. The
#: ROI-shaping ones (binning, image_type, resolution) re-shape the sensor
#: readout, the SDK controls go to the camera, the display_* trio +
#: add_timestamp are software post-processing on the live preview, and
#: the auto_* values parameterize the capture thread's auto-exposure loop.
ADVANCED_CAMERA_TRAITS = (
    "binning", "image_type", "resolution", "white_balance_red",
    "white_balance_blue", "offset", "usb_bandwidth", "high_speed_mode",
    "hardware_bin", "mono_bin", "flip", "add_timestamp",
    "display_gamma", "display_contrast", "display_brightness",
    "auto_target_brightness", "auto_max_gain",
)

#: Software auto-exposure parameters the feed forwards to the capture
#: thread (auto_exposure/auto_gain checkboxes live in the main controls
#: pane; the limits in the advanced pane's Auto tab).
AUTO_SETTING_TRAITS = (
    "auto_exposure", "auto_gain", "auto_target_brightness",
    "auto_max_gain", "auto_max_exposure",
)

#: Capabilities the running feed reports back after camera init (sensor
#: size, color/mono, supported bins/image types); the advanced pane
#: narrows its dropdowns to them and shows concrete resolutions.
CAMERA_CAPS_TRAITS = (
    "camera_max_width", "camera_max_height", "camera_is_color",
    "camera_supported_bins", "camera_supported_image_types",
)


class AsiCameraSettings(HasTraits):
    """Active exposure (microseconds), gain, preview state, and advanced
    capture settings for the ASI camera."""

    exposure = Int(ASI_EXPOSURE_DEFAULT)
    gain = Int(ASI_GAIN_DEFAULT)
    device_viewer_stream = Bool(True)

    # Software auto-exposure / auto-gain (see AUTO_SETTING_TRAITS): the
    # capture thread converges frame brightness on the target within the
    # limits; the manual exposure/gain values are ignored while on.
    auto_exposure = Bool(False)
    auto_gain = Bool(False)
    auto_target_brightness = Range(
        AUTO_TARGET_BRIGHTNESS_MIN, AUTO_TARGET_BRIGHTNESS_MAX,
        AUTO_TARGET_BRIGHTNESS_DEFAULT)
    auto_max_gain = Range(ASI_GAIN_MIN, ASI_GAIN_MAX, AUTO_MAX_GAIN_DEFAULT)
    #: Microseconds (the pane edits a value + ms/s unit pair).
    auto_max_exposure = Int(AUTO_MAX_EXPOSURE_MS_DEFAULT * 1_000)

    # Sensor readout shape. resolution: "full" or a centered-crop "WxH"
    # (see the advanced pane's resolution choices).
    binning = Enum(*ASI_BINNING_CHOICES)
    image_type = Enum(*ASI_IMAGE_TYPE_CHOICES)
    resolution = Str("full")

    # Image controls: white balance goes to the camera (color cameras
    # only); the display_* trio is software post-processing on the live
    # preview (like the ZWO native app's image panel), never touching the
    # saved raw captures.
    white_balance_red = Range(
        ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_MAX,
        ASI_WHITE_BALANCE_RED_DEFAULT)
    white_balance_blue = Range(
        ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_MAX,
        ASI_WHITE_BALANCE_BLUE_DEFAULT)
    display_gamma = Range(
        DISPLAY_GAMMA_MIN, DISPLAY_GAMMA_MAX, DISPLAY_GAMMA_DEFAULT)
    display_contrast = Range(
        DISPLAY_CONTRAST_MIN, DISPLAY_CONTRAST_MAX, DISPLAY_CONTRAST_DEFAULT)
    display_brightness = Range(
        DISPLAY_BRIGHTNESS_MIN, DISPLAY_BRIGHTNESS_MAX,
        DISPLAY_BRIGHTNESS_DEFAULT)
    flip = Enum(*ASI_FLIP_CHOICES)
    offset = Range(ASI_OFFSET_MIN, ASI_OFFSET_MAX, ASI_OFFSET_DEFAULT)
    #: Stamp the current time onto preview frames (display-only).
    add_timestamp = Bool(False)

    # Transfer / binning behavior.
    usb_bandwidth = Range(
        ASI_USB_BANDWIDTH_MIN, ASI_USB_BANDWIDTH_MAX,
        ASI_USB_BANDWIDTH_DEFAULT)
    high_speed_mode = Bool(False)
    hardware_bin = Bool(False)
    mono_bin = Bool(False)

    # Capabilities reported by the running camera (see CAMERA_CAPS_TRAITS;
    # 0 / empty until a feed's camera initializes).
    camera_max_width = Int(0)
    camera_max_height = Int(0)
    camera_is_color = Bool(False)
    camera_supported_bins = List(Int)
    camera_supported_image_types = List(Str)

    #: Latest sensor temperature in degrees C (polled by the capture
    #: thread; NaN until a camera reports).
    camera_temperature = Float(float("nan"))


#: Module-level singleton shared inside the fluorescence plugin.
asi_camera_settings = AsiCameraSettings()
