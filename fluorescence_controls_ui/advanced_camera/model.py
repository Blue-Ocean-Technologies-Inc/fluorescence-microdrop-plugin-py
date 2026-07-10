"""Qt-free HasTraits model for the advanced ASI camera controls pane.

Holds the user's advanced capture settings (sensor readout shape, image
controls, transfer behavior) with the same two-way preferences sync the
main controls pane uses. The controller mirrors every edit into the shared
``asi_camera_settings`` singleton, which the running feed applies live.
"""
import math
import time

from traits.api import (
    Bool, Button, Enum, Float, HasTraits, Instance, Int, List, Property,
    Range, Str, observe,
)
from traits.observation.api import parse

from ..cameras.camera_settings import ADVANCED_CAMERA_TRAITS
from ..cameras.consts import (
    ASI_BINNING_CHOICES, ASI_BINNING_LABELS, ASI_FLIP_CHOICES,
    ASI_GAIN_MAX, ASI_GAIN_MIN, ASI_IMAGE_TYPE_CHOICES,
    ASI_IMAGE_TYPE_LABELS, ASI_OFFSET_DEFAULT, ASI_OFFSET_MAX,
    ASI_OFFSET_MIN, ASI_RESOLUTION_PRESETS,
    ASI_USB_BANDWIDTH_DEFAULT, ASI_USB_BANDWIDTH_MAX, ASI_USB_BANDWIDTH_MIN,
    ASI_WHITE_BALANCE_BLUE_DEFAULT, ASI_WHITE_BALANCE_MAX,
    ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_RED_DEFAULT,
    AUTO_MAX_EXPOSURE_MS_DEFAULT, AUTO_MAX_EXPOSURE_UNIT_HIGHS,
    AUTO_MAX_EXPOSURE_UNITS, AUTO_MAX_GAIN_DEFAULT,
    AUTO_TARGET_BRIGHTNESS_DEFAULT, AUTO_TARGET_BRIGHTNESS_MAX,
    AUTO_TARGET_BRIGHTNESS_MIN,
    DISPLAY_BRIGHTNESS_DEFAULT, DISPLAY_BRIGHTNESS_MAX,
    DISPLAY_BRIGHTNESS_MIN, DISPLAY_CONTRAST_DEFAULT, DISPLAY_CONTRAST_MAX,
    DISPLAY_CONTRAST_MIN, DISPLAY_GAMMA_DEFAULT, DISPLAY_GAMMA_MAX,
    DISPLAY_GAMMA_MIN,
)
from ..cameras.zwoasi import roi_dimensions
from ..preferences import FluorescencePreferences

#: Everything this pane persists: the shared advanced settings plus the
#: max-exposure value/unit pair (the singleton holds only the computed
#: microseconds — see the controller's conversion).
ADVANCED_PANE_PERSISTED_TRAITS = ADVANCED_CAMERA_TRAITS + (
    "auto_max_exposure_value", "auto_max_exposure_unit")


class AdvancedCameraModel(HasTraits):
    """Advanced ASI capture settings (see cameras.camera_settings for how
    they reach the camera)."""

    # Sensor readout shape: binning factor, output image type, and the
    # capture resolution ("full" or a centered-crop "WxH" preset).
    binning = Enum(*ASI_BINNING_CHOICES, desc="sensor binning factor")
    image_type = Enum(*ASI_IMAGE_TYPE_CHOICES,
                      desc="output image type (bit depth / color mode)")
    resolution = Str("full",
                     desc="capture resolution: the full binned frame or a "
                          "centered crop")

    # Display adjustments (like the ZWO native app's image panel):
    # software post-processing on the live preview — never applied to the
    # saved raw captures. 1.0 = neutral for all three.
    display_gamma = Range(
        DISPLAY_GAMMA_MIN, DISPLAY_GAMMA_MAX, DISPLAY_GAMMA_DEFAULT,
        mode="slider", desc="preview gamma curve (1.0 = neutral)")
    display_contrast = Range(
        DISPLAY_CONTRAST_MIN, DISPLAY_CONTRAST_MAX, DISPLAY_CONTRAST_DEFAULT,
        mode="slider", desc="preview contrast around mid-gray "
                            "(1.0 = neutral)")
    display_brightness = Range(
        DISPLAY_BRIGHTNESS_MIN, DISPLAY_BRIGHTNESS_MAX,
        DISPLAY_BRIGHTNESS_DEFAULT, mode="slider",
        desc="preview brightness multiplier (1.0 = neutral)")

    # Per-tab Defaults buttons: each reverts its tab's setters.
    format_defaults_button = Button("Defaults")
    display_defaults_button = Button("Defaults")
    usb_defaults_button = Button("Defaults")
    auto_defaults_button = Button("Defaults")

    @observe("format_defaults_button")
    def _reset_format_settings(self, event):
        self.trait_set(binning=1, image_type="raw16", resolution="full")

    @observe("display_defaults_button")
    def _reset_display_adjustments(self, event):
        self.trait_set(display_gamma=DISPLAY_GAMMA_DEFAULT,
                       display_contrast=DISPLAY_CONTRAST_DEFAULT,
                       display_brightness=DISPLAY_BRIGHTNESS_DEFAULT,
                       white_balance_red=ASI_WHITE_BALANCE_RED_DEFAULT,
                       white_balance_blue=ASI_WHITE_BALANCE_BLUE_DEFAULT)

    @observe("usb_defaults_button")
    def _reset_usb_settings(self, event):
        self.trait_set(offset=ASI_OFFSET_DEFAULT,
                       usb_bandwidth=ASI_USB_BANDWIDTH_DEFAULT,
                       high_speed_mode=False, hardware_bin=False,
                       mono_bin=False, add_timestamp=False, flip="none")

    @observe("auto_defaults_button")
    def _reset_auto_settings(self, event):
        self.trait_set(
            auto_target_brightness=AUTO_TARGET_BRIGHTNESS_DEFAULT,
            auto_max_gain=AUTO_MAX_GAIN_DEFAULT,
            auto_max_exposure_unit="ms",
            auto_max_exposure_value=AUTO_MAX_EXPOSURE_MS_DEFAULT)

    # Camera-side image controls.
    white_balance_red = Range(
        ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_MAX,
        ASI_WHITE_BALANCE_RED_DEFAULT, mode="slider",
        desc="white-balance red gain (color cameras)")
    white_balance_blue = Range(
        ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_MAX,
        ASI_WHITE_BALANCE_BLUE_DEFAULT, mode="slider",
        desc="white-balance blue gain (color cameras)")
    offset = Range(
        ASI_OFFSET_MIN, ASI_OFFSET_MAX, ASI_OFFSET_DEFAULT, mode="slider",
        desc="black-level offset (the native app's Brightness(Offset))")
    flip = Enum(*ASI_FLIP_CHOICES, desc="image flip")
    add_timestamp = Bool(
        False, desc="Stamp the current time onto preview frames")

    # Software auto-exposure limits (the Auto checkboxes live next to the
    # exposure/gain sliders in the main controls pane).
    auto_target_brightness = Range(
        AUTO_TARGET_BRIGHTNESS_MIN, AUTO_TARGET_BRIGHTNESS_MAX,
        AUTO_TARGET_BRIGHTNESS_DEFAULT, mode="slider",
        desc="8-bit display mean the auto loop converges on")
    auto_max_gain = Range(
        ASI_GAIN_MIN, ASI_GAIN_MAX, AUTO_MAX_GAIN_DEFAULT, mode="slider",
        desc="highest gain the auto loop may reach")
    auto_max_exposure_unit = Enum(
        *AUTO_MAX_EXPOSURE_UNITS, desc="unit of the max exposure limit")
    _auto_max_exposure_high = Property(observe="auto_max_exposure_unit")
    auto_max_exposure_value = Range(
        1, "_auto_max_exposure_high", AUTO_MAX_EXPOSURE_MS_DEFAULT,
        desc="longest exposure the auto loop may reach")

    def _get__auto_max_exposure_high(self):
        return AUTO_MAX_EXPOSURE_UNIT_HIGHS[self.auto_max_exposure_unit]

    @observe("auto_max_exposure_unit")
    def _clamp_auto_max_exposure_value(self, event):
        high = AUTO_MAX_EXPOSURE_UNIT_HIGHS[self.auto_max_exposure_unit]
        if self.auto_max_exposure_value > high:
            self.auto_max_exposure_value = high

    # ------------------------------------------------------------------ #
    # Sensor temperature (Temp tab)                                        #
    # ------------------------------------------------------------------ #
    #: Latest sensor reading (the controller copies it from the shared
    #: settings; NaN until a camera reports).
    camera_temperature = Float(float("nan"))
    #: (elapsed seconds, degrees C) points since monitoring began.
    temperature_history = List()
    initial_temperature = Float(float("nan"))
    _monitoring_started = Float(0.0)

    initial_temperature_text = Property(
        Str, observe="temperature_history.items")
    current_temperature_text = Property(
        Str, observe="temperature_history.items")
    monitor_time_text = Property(Str, observe="temperature_history.items")

    @observe("camera_temperature")
    def _record_temperature(self, event):
        if math.isnan(event.new):
            return
        now = time.monotonic()
        if not self.temperature_history:
            self._monitoring_started = now
            self.initial_temperature = event.new
        self.temperature_history.append(
            (now - self._monitoring_started, event.new))

    def _get_initial_temperature_text(self):
        if not self.temperature_history:
            return "-"
        return f"{self.initial_temperature:.1f} \N{DEGREE SIGN}C"

    def _get_current_temperature_text(self):
        if not self.temperature_history:
            return "-"
        return f"{self.temperature_history[-1][1]:.1f} \N{DEGREE SIGN}C"

    def _get_monitor_time_text(self):
        if not self.temperature_history:
            return "-"
        elapsed = int(self.temperature_history[-1][0])
        return f"{elapsed // 60:d}:{elapsed % 60:02d}"

    # Transfer / binning behavior.
    usb_bandwidth = Range(
        ASI_USB_BANDWIDTH_MIN, ASI_USB_BANDWIDTH_MAX,
        ASI_USB_BANDWIDTH_DEFAULT, mode="slider",
        desc="USB bandwidth limit (%) — lower if transfers stall")
    high_speed_mode = Bool(
        False, desc="High-speed (10-bit ADC) readout — faster, noisier")
    hardware_bin = Bool(
        False, desc="Bin on the sensor instead of in software")
    mono_bin = Bool(
        False, desc="Mono binning (less grid artifact on color cameras)")

    # Capabilities reported by the running camera (the controller copies
    # them from the shared ASI camera settings; 0 / empty until a camera
    # initializes). The choice dicts below narrow the dropdowns to them.
    camera_max_width = Int(0)
    camera_max_height = Int(0)
    camera_is_color = Bool(False)
    camera_supported_bins = List(Int)
    camera_supported_image_types = List(Str)

    #: Dropdown choices ({value: label}), narrowed to the camera's
    #: capabilities once known — all options offered until then.
    binning_choices = Property(observe="camera_supported_bins.items")
    image_type_choices = Property(
        observe="camera_supported_image_types.items")
    #: Resolution ladder (like the ZWO native GUI): the full binned frame
    #: plus every standard preset that fits it — concrete once the sensor
    #: size is known, following the binning choice.
    resolution_choices = Property(
        observe="binning, camera_max_width, camera_max_height")

    def _get_binning_choices(self):
        supported = self.camera_supported_bins or list(ASI_BINNING_CHOICES)
        return {value: label for value, label in ASI_BINNING_LABELS.items()
                if value in supported}

    def _get_image_type_choices(self):
        supported = (self.camera_supported_image_types
                     or list(ASI_IMAGE_TYPE_CHOICES))
        return {value: label
                for value, label in ASI_IMAGE_TYPE_LABELS.items()
                if value in supported}

    def _get_resolution_choices(self):
        if not (self.camera_max_width and self.camera_max_height):
            return {"full": "Full"}
        full_width, full_height = roi_dimensions(
            self.camera_max_width, self.camera_max_height, self.binning)
        choices = {"full": f"{full_width}x{full_height} (full)"}
        for width, height in ASI_RESOLUTION_PRESETS:
            if (width, height) == (full_width, full_height):
                continue
            if width <= full_width and height <= full_height:
                choices[f"{width}x{height}"] = f"{width}x{height}"
        return choices

    @observe("camera_supported_bins.items,"
             "camera_supported_image_types.items")
    def _snap_to_supported(self, event):
        """When capabilities arrive, move settings the camera can't do to
        safe ones (e.g. a persisted 'y8' on a mono camera -> raw16)."""
        if (self.camera_supported_bins
                and self.binning not in self.camera_supported_bins):
            self.binning = 1
        if (self.camera_supported_image_types
                and self.image_type not in self.camera_supported_image_types):
            self.image_type = "raw16"

    @observe("binning, camera_max_width, camera_max_height")
    def _snap_resolution_to_choices(self, event):
        """A resolution preset that no longer fits (e.g. 2560x1440 after
        switching to bin 2) falls back to the full binned frame."""
        if self.resolution not in self.resolution_choices:
            self.resolution = "full"

    #: Persistence backing (two-way, same pattern as the main controls
    #: pane): edits push to preferences, external changes pull back.
    preferences = Instance(FluorescencePreferences, FluorescencePreferences())

    #: Guards the two-way preferences sync against echoing its own writes
    #: (declared trait, so the pull observer can read it in any ordering).
    _self_preference_change = Bool(False)

    def traits_init(self):
        self._self_preference_change = True
        self.trait_set(**{
            name: getattr(self.preferences, name)
            for name in ADVANCED_PANE_PERSISTED_TRAITS})
        self._self_preference_change = False

    @observe(f"[{','.join(ADVANCED_PANE_PERSISTED_TRAITS)}]", post_init=True)
    def _push_preferences(self, event):
        self._self_preference_change = True
        self.preferences.trait_set(**{event.name: event.new})
        self._self_preference_change = False

    @observe(parse("preferences").match(
        lambda name, trait: name in ADVANCED_PANE_PERSISTED_TRAITS))
    def _pull_preferences(self, event):
        if not self._self_preference_change:
            self.trait_set(**{event.name: event.new})
