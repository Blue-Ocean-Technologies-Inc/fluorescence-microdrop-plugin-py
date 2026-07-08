"""Fluorescence UI preferences.

A small PreferencesHelper on the SAME "Peripheral Settings" node the other
peripheral plugins use (``microdrop.peripheral_settings``), holding only the
fluorescence plugin's own traits.
"""
from apptools.preferences.api import PreferencesHelper
from traits.api import Bool


class FluorescencePreferences(PreferencesHelper):
    """Fluorescence-owned slice of the shared Peripheral Settings node."""

    preferences_path = "microdrop.peripheral_settings"

    # One-time notice pointing Windows users at the ZWO ASI camera driver
    # download (required before an ASI camera can be used).
    fluorescence_show_asi_driver_notice = Bool(
        True, desc="Show the ASI camera driver download notice on plugin start"
    )
