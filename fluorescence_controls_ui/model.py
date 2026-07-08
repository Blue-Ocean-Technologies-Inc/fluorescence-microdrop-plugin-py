from traits.api import Bool, Enum, Int, Str

from template_status_and_controls.base_model import BaseStatusModel

from .consts import (
    disconnected_color, connected_color,
    LED_WAVELENGTHS,
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
    CONNECTED_COLOR = connected_color

    # Imaging mode: brightfield / fluorescence / dual.
    mode = Enum("br", "fl", "dual")

    # Master light toggle (the standalone light button).
    light_on = Bool(False)

    # Brightfield LED set.
    br_wavelength = Enum(*LED_WAVELENGTHS)
    br_intensity = Int(BR_INTENSITY_DEFAULT)
    br_frequency = Int(BR_FREQUENCY_DEFAULT)

    # Fluorescence LED set.
    fl_wavelength = Enum(*LED_WAVELENGTHS)
    fl_intensity = Int(FL_INTENSITY_DEFAULT)
    fl_frequency = Int(FL_FREQUENCY_DEFAULT)

    # Latest ack/telemetry line from the board.
    last_reading = Str("-")

    @property
    def br_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.br_wavelength)

    @property
    def fl_led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.fl_wavelength)
