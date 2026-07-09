"""Fluorescence UI preferences.

A small PreferencesHelper on the SAME "Peripheral Settings" node the other
peripheral plugins use (``microdrop.peripheral_settings``), holding only the
fluorescence plugin's own traits.
"""
from apptools.preferences.api import PreferencesHelper
from envisage.ui.tasks.api import PreferencesPane
from traits.api import Bool, Directory, Int, Str, Float
from traitsui.api import Item, View, VGroup

from microdrop_style.text_styles import preferences_group_style_sheet
from microdrop_utils.preferences_UI_helpers import create_item_label_group
from logger.logger_service import get_logger

from .consts import (
    LED_WAVELENGTHS,
    BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT,
    BR_EXPOSURE_DEFAULT, BR_GAIN_DEFAULT,
    FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT,
    FL_EXPOSURE_DEFAULT, FL_GAIN_DEFAULT,
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
    # preferences tab. Defaults match the model's.
    mode = Str("br", desc="Imaging mode: br / fl / dual")
    br_wavelength = Str(
        LED_WAVELENGTHS[0], desc="Brightfield LED wavelength")
    br_intensity = Int(
        BR_INTENSITY_DEFAULT, desc="Brightfield LED duty (%)")
    br_frequency = Int(
        BR_FREQUENCY_DEFAULT, desc="Brightfield LED PWM frequency (Hz)")
    br_exposure = Float(
        BR_EXPOSURE_DEFAULT, desc="Brightfield camera exposure (ms)")
    br_gain = Int(
        BR_GAIN_DEFAULT, desc="Brightfield camera gain")
    fl_wavelength = Str(
        LED_WAVELENGTHS[0], desc="Fluorescence LED wavelength")
    fl_intensity = Int(
        FL_INTENSITY_DEFAULT, desc="Fluorescence LED duty (%)")
    fl_frequency = Int(
        FL_FREQUENCY_DEFAULT, desc="Fluorescence LED PWM frequency (Hz)")
    fl_exposure = Float(
        FL_EXPOSURE_DEFAULT, desc="Fluorescence camera exposure (ms)")
    fl_gain = Int(
        FL_GAIN_DEFAULT, desc="Fluorescence camera gain")


class FluorescencePreferencesPane(PreferencesPane):
    """Fluorescence group on the shared Peripheral Settings tab.

    Same category id the magnet/heater settings use; envisage merges panes
    of one category into a single tab (and auto-creates the category when
    the magnet group that declares it is not loaded).
    """

    model_factory = FluorescencePreferences

    category = "microdrop.peripheral_settings"

    settings = VGroup(
        create_item_label_group("fluorescence_show_asi_driver_notice", label_text="Show the ASI camera driver notice at launch (Windows)"),
        create_item_label_group("fluorescence_asi_sdk_dir", label_text="ASI Camera SDK Directory"),
        label="Remote Backend",
        show_border=True,
        style_sheet=preferences_group_style_sheet,
    )

    view = View(
        settings,
        Item("_"),  # Separator to space this out from further contributions.
        resizable=True,
    )
