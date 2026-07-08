from traitsui.api import View, VGroup, HGroup, Item, Readonly, EnumEditor, RangeEditor

from microdrop_utils.traitsui_qt_helpers import SlidingToggleEditor

from .consts import LED_DUTY_MIN, LED_DUTY_MAX, LED_FREQUENCY_MIN, LED_FREQUENCY_MAX

# Connection / board identity + last board ack line.
status_group = VGroup(
    Readonly("connection_status_text", label="Connection"),
    Readonly("last_reading", label="Board"),
    show_border=True,
)

# Imaging mode + master light toggle.
mode_group = HGroup(
    Item("mode", style="custom", show_label=False,
         editor=EnumEditor(values={"br": "Brightfield",
                                   "fl": "Fluorescence",
                                   "dual": "Dual"}, cols=3)),
    Item("light_on", label="Light", editor=SlidingToggleEditor()),
    show_border=True,
)

# Per-mode LED sets. Enablement mirrors the standalone app: brightfield
# controls active in br+dual, fluorescence controls in fl+dual.
brightfield_group = VGroup(
    Item("br_wavelength", label="Wavelength"),
    Item("br_intensity", label="Intensity (%)",
         editor=RangeEditor(low=LED_DUTY_MIN, high=LED_DUTY_MAX)),
    Item("br_frequency", label="Frequency (Hz)",
         editor=RangeEditor(low=LED_FREQUENCY_MIN, high=LED_FREQUENCY_MAX)),
    label="Brightfield",
    show_border=True,
    enabled_when="mode != 'fl'",
)

fluorescence_group = VGroup(
    Item("fl_wavelength", label="Wavelength"),
    Item("fl_intensity", label="Intensity (%)",
         editor=RangeEditor(low=LED_DUTY_MIN, high=LED_DUTY_MAX)),
    Item("fl_frequency", label="Frequency (Hz)",
         editor=RangeEditor(low=LED_FREQUENCY_MIN, high=LED_FREQUENCY_MAX)),
    label="Fluorescence",
    show_border=True,
    enabled_when="mode != 'br'",
)

UnifiedView = View(
    VGroup(status_group, mode_group, brightfield_group, fluorescence_group),
    resizable=True,
)
