"""Per-step fluorescence state: the same knobs as the controls pane
(mode, light, per-mode wavelength/intensity/frequency/exposure/gain),
edited in the protocol column's dialog and stored on the row as a plain
dict — or None when the step leaves the fluorescence state untouched.
"""
from traits.api import Bool, Enum, HasTraits
from traitsui.api import EnumEditor, HGroup, Item, OKCancelButtons, VGroup, View

from microdrop_utils.traitsui_qt_helpers import (
    InPlaceToggleEditor, RangeWithSteppedSpinViewHint,
)
from logger.logger_service import get_logger

from fluorescence_controller.consts import (
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
)
from fluorescence_controls_ui.cameras.consts import ASI_GAIN_MIN, ASI_GAIN_MAX
from fluorescence_controls_ui.consts import (
    EXPOSURE_MS_MIN, EXPOSURE_MS_MAX,
    BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT,
    BR_EXPOSURE_DEFAULT, BR_GAIN_DEFAULT,
    FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT,
    FL_EXPOSURE_DEFAULT, FL_GAIN_DEFAULT,
)

logger = get_logger(__name__)

#: The dict keys a step stores (identical to the pane's trait names).
STEP_SETTING_TRAITS = (
    "mode", "light_on",
    "br_wavelength", "br_intensity", "br_frequency", "br_exposure", "br_gain",
    "fl_wavelength", "fl_intensity", "fl_frequency", "fl_exposure", "fl_gain",
)


class FluorescenceStepSettings(HasTraits):
    """Dialog model for one step's fluorescence state."""

    #: Unchecked = the step leaves the fluorescence state untouched (the
    #: column's stored value stays None).
    apply = Bool(False, desc="Set the fluorescence state on this step")

    mode = Enum("br", "fl", "dual")
    light_on = Bool(False)

    br_wavelength = Enum(*LED_WAVELENGTHS)
    br_intensity = RangeWithSteppedSpinViewHint(
        LED_DUTY_MIN, LED_DUTY_MAX, value=BR_INTENSITY_DEFAULT, suffix=" %",
        desc="brightfield LED duty to apply (%)",
    )
    br_frequency = RangeWithSteppedSpinViewHint(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=BR_FREQUENCY_DEFAULT,
        suffix=" Hz", desc="brightfield LED PWM frequency (Hz)",
    )
    br_exposure = RangeWithSteppedSpinViewHint(
        EXPOSURE_MS_MIN, EXPOSURE_MS_MAX, value=BR_EXPOSURE_DEFAULT,
        suffix=" ms", desc="brightfield camera exposure (milliseconds)",
    )
    br_gain = RangeWithSteppedSpinViewHint(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=BR_GAIN_DEFAULT,
        desc="brightfield camera gain",
    )

    fl_wavelength = Enum(*LED_WAVELENGTHS)
    fl_intensity = RangeWithSteppedSpinViewHint(
        LED_DUTY_MIN, LED_DUTY_MAX, value=FL_INTENSITY_DEFAULT, suffix=" %",
        desc="fluorescence LED duty to apply (%)",
    )
    fl_frequency = RangeWithSteppedSpinViewHint(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=FL_FREQUENCY_DEFAULT,
        suffix=" Hz", desc="fluorescence LED PWM frequency (Hz)",
    )
    fl_exposure = RangeWithSteppedSpinViewHint(
        EXPOSURE_MS_MIN, EXPOSURE_MS_MAX, value=FL_EXPOSURE_DEFAULT,
        suffix=" ms", desc="fluorescence camera exposure (milliseconds)",
    )
    fl_gain = RangeWithSteppedSpinViewHint(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=FL_GAIN_DEFAULT,
        desc="fluorescence camera gain",
    )

    @property
    def br_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.br_wavelength)

    @property
    def fl_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.fl_wavelength)

    # ------------------------------------------------------------------ #
    # Column-value round trip                                              #
    # ------------------------------------------------------------------ #
    @classmethod
    def from_value(cls, value):
        """Settings seeded from a stored column value (dict or None).
        Unknown/invalid stored entries are skipped so a stale protocol
        file can't break the dialog."""
        settings = cls()
        if isinstance(value, dict):
            settings.apply = True
            for name in STEP_SETTING_TRAITS:
                if name in value:
                    try:
                        setattr(settings, name, value[name])
                    except Exception as e:
                        logger.warning(f"Ignoring stored step setting "
                                       f"{name}={value[name]!r}: {e}")
        return settings

    def to_value(self):
        """The column value to store: a plain dict, or None when the step
        applies nothing."""
        if not self.apply:
            return None
        return {name: getattr(self, name) for name in STEP_SETTING_TRAITS}


# The controls-pane layout, per step: mode + light on top, then the two
# LED sets with the pane's exact gating (brightfield editable outside fl
# mode; in dual mode the camera runs on the brightfield pair, so the fl
# exposure/gain stay editable only in fl mode).
step_settings_view = View(
    VGroup(
        Item("apply", label="Set fluorescence state on this step"),
        VGroup(
            HGroup(
                Item("mode", style="custom", show_label=False,
                     editor=EnumEditor(values={"br": "Brightfield",
                                               "fl": "Fluorescence",
                                               "dual": "Dual"}, cols=3)),
                Item("light_on", label="Light",
                     editor=InPlaceToggleEditor(on_label="Light On",
                                                off_label="Light Off")),
            ),
            VGroup(
                Item("br_wavelength", label="Wavelength"),
                Item("br_intensity", label="Intensity"),
                Item("br_frequency", label="Frequency"),
                Item("br_exposure", label="Exposure"),
                Item("br_gain", label="Gain"),
                label="Brightfield", show_border=True,
                enabled_when="mode != 'fl'",
            ),
            VGroup(
                Item("fl_wavelength", label="Wavelength"),
                Item("fl_intensity", label="Intensity"),
                Item("fl_frequency", label="Frequency"),
                Item("fl_exposure", label="Exposure",
                     enabled_when="mode == 'fl'"),
                Item("fl_gain", label="Gain", enabled_when="mode == 'fl'"),
                label="Fluorescence", show_border=True,
                enabled_when="mode != 'br'",
            ),
            enabled_when="apply",
        ),
    ),
    title="Fluorescence Step Settings",
    buttons=OKCancelButtons,
    resizable=True,
)
