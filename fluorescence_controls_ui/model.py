from traits.api import Bool, Enum, Str, observe

from microdrop_utils.traitsui_qt_helpers import RangeWithSteppedSpinViewHint

from template_status_and_controls.base_model import BaseStatusModel

from .consts import (
    disconnected_color, connected_color, halted_color,
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
    BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT,
    FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT,
)

from logger.logger_service import get_logger
logger = get_logger(__name__)


class FluorescenceStatusModel(BaseStatusModel):
    """Model for fluorescence LED controls (port of the standalone app's
    per-mode brightfield/fluorescence LED state).

    Mode gating mirrors the original: brightfield controls apply live in
    "br" mode, fluorescence controls in "fl" mode; "dual" enables both
    control groups but the light toggle drives the brightfield set (the
    dual capture sequence alternates LEDs itself).
    """

    DISCONNECTED_COLOR = disconnected_color
    # No "connected but no chip" sub-state on the LED board — the base model
    # parks connected devices on CONNECTED_NO_DEVICE_COLOR until a DropBot
    # chip_inserted signal that never comes, so connected maps straight to green.
    CONNECTED_NO_DEVICE_COLOR = connected_color
    CONNECTED_COLOR = connected_color
    HALTED_COLOR = halted_color

    # Imaging mode: brightfield / fluorescence / dual.
    mode = Enum("br", "fl", "dual")

    # Board identity (from the led_help probe on connect).
    board_id_text = Str("-")

    # Latest ack/telemetry line from the board.
    last_reading = Str("-")

    # Master light toggle (the standalone light button).
    light_on = Bool(False)

    # Brightfield LED set.
    br_wavelength = Enum(*LED_WAVELENGTHS)
    br_intensity = RangeWithSteppedSpinViewHint(
        LED_DUTY_MIN, LED_DUTY_MAX, value=BR_INTENSITY_DEFAULT, suffix=" %",
        desc="brightfield LED duty to apply (%)",
    )
    br_frequency = RangeWithSteppedSpinViewHint(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=BR_FREQUENCY_DEFAULT, suffix=" Hz",
        desc="brightfield LED PWM frequency (Hz)",
    )

    # Fluorescence LED set.
    fl_wavelength = Enum(*LED_WAVELENGTHS)
    fl_intensity = RangeWithSteppedSpinViewHint(
        LED_DUTY_MIN, LED_DUTY_MAX, value=FL_INTENSITY_DEFAULT, suffix=" %",
        desc="fluorescence LED duty to apply (%)",
    )
    fl_frequency = RangeWithSteppedSpinViewHint(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=FL_FREQUENCY_DEFAULT, suffix=" Hz",
        desc="fluorescence LED PWM frequency (Hz)",
    )

    # ------------------------------------------------------------------ #
    # Collapsible-section switches (view headers toggle these)             #
    # ------------------------------------------------------------------ #
    show_status = Bool(True, desc="Expand the Status section")
    show_control = Bool(True, desc="Expand the Control section")
    show_brightfield = Bool(True, desc="Expand the Brightfield section")
    show_fluorescence = Bool(False, desc="Expand the Fluorescence section")

    @observe("mode")
    def _collapse_unused_mode_sections(self, event):
        """Selecting a mode also collapses the set it disables: br/fl expand
        only their own section, dual expands both. The user can still re-expand
        anything by hand afterwards."""
        self.show_brightfield = self.mode != "fl"
        self.show_fluorescence = self.mode != "br"

    @property
    def br_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.br_wavelength)

    @property
    def fl_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.fl_wavelength)
