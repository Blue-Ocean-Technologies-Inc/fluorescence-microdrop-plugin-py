"""Fluorescence UI preferences.

A small PreferencesHelper on the SAME "Peripheral Settings" node the other
peripheral plugins use (``microdrop.peripheral_settings``), holding only the
fluorescence plugin's own traits.
"""
from apptools.preferences.api import PreferencesHelper
from envisage.ui.tasks.api import PreferencesPane
from traits.api import Bool, Directory
from traitsui.api import Item, View, VGroup

from microdrop_style.text_styles import preferences_group_style_sheet
from microdrop_utils.preferences_UI_helpers import create_item_label_group


class FluorescencePreferences(PreferencesHelper):
    """Fluorescence-owned slice of the shared Peripheral Settings node."""

    preferences_path = "microdrop.peripheral_settings"

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
