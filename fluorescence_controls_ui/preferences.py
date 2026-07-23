"""Fluorescence UI preferences.

A small PreferencesHelper on the SAME "Peripheral Settings" node the other
peripheral plugins use (``microdrop.peripheral_settings``), holding only the
fluorescence plugin's own traits.
"""
from apptools.preferences.api import PreferencesHelper
from envisage.ui.tasks.api import PreferencesPane, PreferencesCategory
from traits.api import Bool, Directory, Int, Str, Float
from traitsui.api import Item, View, VGroup

from microdrop_style.text_styles import preferences_group_style_sheet
from microdrop_utils.preferences_UI_helpers import create_item_label_group
from logger.logger_service import get_logger

from .cameras.consts import (
    ASI_OFFSET_DEFAULT, ASI_USB_BANDWIDTH_DEFAULT,
    ASI_WHITE_BALANCE_BLUE_DEFAULT, ASI_WHITE_BALANCE_RED_DEFAULT,
    AUTO_MAX_EXPOSURE_MS_DEFAULT, AUTO_MAX_GAIN_DEFAULT,
    AUTO_TARGET_BRIGHTNESS_DEFAULT,
    DISPLAY_BRIGHTNESS_DEFAULT, DISPLAY_CONTRAST_DEFAULT,
    DISPLAY_GAMMA_DEFAULT,
)
from .consts import (
    LED_WAVELENGTHS,
    INTENSITY_DEFAULT, FREQUENCY_DEFAULT,
    EXPOSURE_DEFAULT, GAIN_DEFAULT,
)

logger = get_logger(__name__)


class FluorescencePreferences(PreferencesHelper):
    """Fluorescence-owned slice of the shared Peripheral Settings node."""

    preferences_path = Str("microdrop.peripheral_settings")

    # One-time notice pointing Windows users at the ZWO ASI camera driver
    # download (required before an ASI camera can be used).
    fluorescence_show_asi_driver_notice = Bool(
        True, desc="Show the ASI camera driver download notice on plugin start"
    )

    # One-time note that lighting edits made while the pane's stream is off
    # are staged until the stream starts (heater pane parity; the dialog's
    # don't-show-again checkbox clears this).
    fluorescence_show_stream_off_warning = Bool(
        True, desc="Warn when a lighting edit is staged because the stream is off"
    )

    # Root of the ZWO ASI SDK (the directory holding Win/ and Unix/).
    # Defaults to the copy bundled with the plugin; empty disables ASI.
    fluorescence_asi_sdk_dir = Directory(
        desc="Directory of the ZWO ASI camera SDK (holds Win/ and Unix/)"
    )

    def _fluorescence_asi_sdk_dir_default(self):
        from .cameras.zwoasi import default_asi_sdk_dir
        return default_asi_sdk_dir()

    # Image viewer display window. Edited from the image viewer dock pane's
    # own toolbar — deliberately NOT on the preferences tab.
    fluorescence_viewer_auto_contrast = Bool(
        True, desc="Auto-contrast the image viewer display window"
    )
    fluorescence_viewer_window_min = Float(
        0, desc="Manual display-window minimum (used when auto-contrast is off)"
    )
    fluorescence_viewer_window_max = Float(
        10000, desc="Manual display-window maximum (used when auto-contrast is off)"
    )

    # Control-pane values (see consts.PERSISTED_CONTROL_TRAITS). Edited from
    # the fluorescence controls dock pane — deliberately NOT on the
    # preferences tab. Defaults match the model's. `label` is NOT
    # persisted — it defaults from the wavelength at Add time.
    wavelength = Str(
        LED_WAVELENGTHS[0], desc="LED wavelength")
    intensity = Int(
        INTENSITY_DEFAULT, desc="LED duty (%)")
    frequency = Int(
        FREQUENCY_DEFAULT, desc="LED PWM frequency (Hz)")
    exposure = Float(
        EXPOSURE_DEFAULT, desc="camera exposure (ms)")
    gain = Int(
        GAIN_DEFAULT, desc="camera gain")
    device_viewer_stream = Bool(
        True, desc="Render the live ASI feed in the device viewer")
    auto_exposure = Bool(
        False, desc="Auto-adjust camera exposure toward the target brightness")
    auto_gain = Bool(
        False, desc="Auto-adjust camera gain toward the target brightness")

    # Advanced camera settings (see cameras.camera_settings
    # ADVANCED_CAMERA_TRAITS). Edited from the advanced camera controls
    # dock pane — deliberately NOT on the preferences tab.
    binning = Int(1, desc="Sensor binning factor")
    image_type = Str("raw16", desc="Output image type: raw16/raw8/rgb24/y8")
    resolution = Str(
        "full", desc="Capture resolution: full or a centered-crop WxH")
    white_balance_red = Int(
        ASI_WHITE_BALANCE_RED_DEFAULT, desc="White-balance red gain")
    white_balance_blue = Int(
        ASI_WHITE_BALANCE_BLUE_DEFAULT, desc="White-balance blue gain")
    display_gamma = Float(
        DISPLAY_GAMMA_DEFAULT, desc="Preview gamma curve (1.0 = neutral)")
    display_contrast = Float(
        DISPLAY_CONTRAST_DEFAULT,
        desc="Preview contrast around mid-gray (1.0 = neutral)")
    display_brightness = Float(
        DISPLAY_BRIGHTNESS_DEFAULT,
        desc="Preview brightness multiplier (1.0 = neutral)")
    usb_bandwidth = Int(
        ASI_USB_BANDWIDTH_DEFAULT, desc="USB bandwidth limit (%)")
    high_speed_mode = Bool(False, desc="High-speed (10-bit ADC) readout")
    hardware_bin = Bool(False, desc="Bin on the sensor instead of software")
    mono_bin = Bool(False, desc="Mono binning for color cameras")
    flip = Str("none", desc="Image flip: none/horizontal/vertical/both")
    offset = Int(
        ASI_OFFSET_DEFAULT, desc="Black-level offset (Brightness(Offset))")
    add_timestamp = Bool(
        False, desc="Stamp the current time onto preview frames")
    auto_target_brightness = Int(
        AUTO_TARGET_BRIGHTNESS_DEFAULT,
        desc="8-bit display mean the auto-exposure loop converges on")
    auto_max_gain = Int(
        AUTO_MAX_GAIN_DEFAULT, desc="Highest gain the auto loop may reach")
    auto_max_exposure_value = Int(
        AUTO_MAX_EXPOSURE_MS_DEFAULT,
        desc="Longest exposure the auto loop may reach (in the unit below)")
    auto_max_exposure_unit = Str(
        "ms", desc="Unit of the max exposure limit: ms or s")

    firmware_source = Directory(desc="Firmware directory or zip file")


fluorescence_tab = PreferencesCategory(
    id="microdrop.peripheral_settings.fluorescence",
    name="Fluorescence Settings",
    after="microdrop.dropbot_settings"
)

class FluorescencePreferencesPane(PreferencesPane):
    """The fluorescence plugin's own Fluorescence Settings tab (its traits
    stay on the shared ``microdrop.peripheral_settings`` node, so values
    saved before the tab split keep working)."""

    model_factory = FluorescencePreferences

    category = fluorescence_tab.id

    settings = VGroup(
        create_item_label_group("fluorescence_show_asi_driver_notice", label_text="Show the ASI camera driver notice at launch (Windows)"),
        create_item_label_group("fluorescence_asi_sdk_dir", label_text="ASI Camera SDK Directory"),
        label="Backend",
        show_border=True,
        style_sheet=preferences_group_style_sheet,
    )

    controls_group = create_item_label_group(
        "fluorescence_show_stream_off_warning",
        label_text="Warn when a lighting edit is staged because the stream is off",
        orientation="horizontal",
        label_position="last",
        group_label="Controls",
        group_show_border=True,
        group_style_sheet=preferences_group_style_sheet,
    )

    view = View(
        settings,
        controls_group,
        Item("_"),  # Separator to space this out from further contributions.
        resizable=True,
    )
