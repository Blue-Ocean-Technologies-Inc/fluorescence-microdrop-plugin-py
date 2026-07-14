"""Per-step fluorescence state: a snapshot of the live controls pane
(mode, light, per-mode wavelength/intensity/frequency/exposure/gain, the
auto exposure/gain flags, and the advanced camera settings), grabbed when
the user checks the step's fluorescence cell and stored on the row as a
plain dict — or None when the step leaves the fluorescence state untouched.
"""
from traits.api import Bool, Dict, Enum, HasTraits

from microdrop_utils.traitsui_qt_helpers import RangeWithSteppedSpinViewHint
from logger.logger_service import get_logger

from fluorescence_controller.consts import (
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
)
from fluorescence_controls_ui.cameras.camera_settings import (
    ADVANCED_CAMERA_TRAITS, asi_camera_settings,
)
from fluorescence_controls_ui.cameras.consts import ASI_GAIN_MIN, ASI_GAIN_MAX
from fluorescence_controls_ui.consts import (
    EXPOSURE_MS_MIN, EXPOSURE_MS_MAX,
    BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT,
    BR_EXPOSURE_DEFAULT, BR_GAIN_DEFAULT,
    FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT,
    FL_EXPOSURE_DEFAULT, FL_GAIN_DEFAULT,
)
from fluorescence_controls_ui.live_state import fluorescence_live_state
from fluorescence_controls_ui.preferences import FluorescencePreferences

from .consts import STEP_SETTING_TRAITS

logger = get_logger(__name__)


class FluorescenceStepSettings(HasTraits):
    """Typed carrier for one step's fluorescence state."""

    #: False = the step leaves the fluorescence state untouched (the
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
        float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX),
        value=float(BR_EXPOSURE_DEFAULT),
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
        float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX),
        value=float(FL_EXPOSURE_DEFAULT),
        suffix=" ms", desc="fluorescence camera exposure (milliseconds)",
    )
    fl_gain = RangeWithSteppedSpinViewHint(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=FL_GAIN_DEFAULT,
        desc="fluorescence camera gain",
    )

    #: Software auto-exposure / auto-gain flags, snapshotted with the rest.
    auto_exposure = Bool(False)
    auto_gain = Bool(False)

    #: Advanced camera settings (ADVANCED_CAMERA_TRAITS name -> value),
    #: snapshotted from the shared ASI settings. JSON-native values.
    advanced = Dict()

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
    def snapshot_current(cls):
        """Settings grabbed from the LIVE fluorescence controls (device-
        viewer semantics: arrange the pane, then check the step's cell).

        The LED sets, mode and auto flags come from FluorescencePreferences
        (the pane mirrors every persisted control there as it changes), the
        light state from the live-state singleton (deliberately never
        persisted), and the advanced camera settings from the shared ASI
        camera settings."""
        settings = cls(apply=True,
                       light_on=fluorescence_live_state.light_on)
        preferences = FluorescencePreferences()
        for name in STEP_SETTING_TRAITS:
            if name == "light_on":
                continue
            try:
                setattr(settings, name, getattr(preferences, name))
            except Exception as e:
                logger.warning(
                    f"Snapshot keeps the default for {name}: {e}")
        settings.advanced = {
            name: getattr(asi_camera_settings, name)
            for name in ADVANCED_CAMERA_TRAITS}
        return settings

    @classmethod
    def from_value(cls, value):
        """Settings seeded from a stored column value (dict or None).
        Unknown/invalid stored entries are skipped so a stale protocol
        file can't break the run."""
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
            settings.advanced = {
                name: stored
                for name, stored in (value.get("advanced") or {}).items()
                if name in ADVANCED_CAMERA_TRAITS}
        return settings

    def to_value(self):
        """The column value to store: a plain dict, or None when the step
        applies nothing."""
        if not self.apply:
            return None
        value = {name: getattr(self, name) for name in STEP_SETTING_TRAITS}
        value["advanced"] = dict(self.advanced)
        return value
