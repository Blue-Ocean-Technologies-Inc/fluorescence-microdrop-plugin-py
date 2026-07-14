from traits.api import Bool, Enum, Event, Str, observe, Instance, Range
from traits.observation.api import parse

from microdrop_utils.traitsui_qt_helpers import RangeWithViewHints

from template_status_and_controls.base_model import BaseStatusModel

from .cameras.consts import ASI_GAIN_MIN, ASI_GAIN_MAX
from .consts import (
    disconnected_color, connected_color, halted_color,
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
    BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT,
    FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT,
    BR_EXPOSURE_DEFAULT, BR_GAIN_DEFAULT,
    FL_EXPOSURE_DEFAULT, FL_GAIN_DEFAULT,
    EXPOSURE_MS_MIN, EXPOSURE_MS_MAX, PERSISTED_CONTROL_TRAITS,
)

from logger.logger_service import get_logger
from .preferences import FluorescencePreferences

logger = get_logger(__name__)


class FluorescenceStatusModel(BaseStatusModel):
    """Model for fluorescence LED controls (port of the standalone app's
    per-mode brightfield/fluorescence LED state).

    Mode gating mirrors the original: brightfield controls apply live in
    "br" mode, fluorescence controls in "fl" mode; "dual" enables both
    control groups but the light toggle drives the brightfield set (the
    dual capture sequence alternates LEDs itself).
    """

    DISCONNECTED_COLOR = Str(disconnected_color)
    # No "connected but no chip" sub-state on the LED board — the base model
    # parks connected devices on CONNECTED_NO_DEVICE_COLOR until a DropBot
    # chip_inserted signal that never comes, so connected maps straight to green.
    CONNECTED_NO_DEVICE_COLOR = Str(connected_color)
    CONNECTED_COLOR = Str(connected_color)
    HALTED_COLOR = Str(halted_color)

    # Imaging mode: brightfield / fluorescence / dual.
    mode = Enum("br", "fl", "dual")

    # Board identity (from the led_help probe on connect).
    board_id_text = Str("-")

    # Latest ack/telemetry line from the board.
    last_reading = Str("-")

    # Master light toggle (the standalone light button).
    light_on = Bool(False)

    # Master gate paralleling the heater pane's stream toggle: while off,
    # the pane sends the LED board no commands — lighting edits are staged
    # and applied when the stream starts. Deliberately not persisted (the
    # board always starts silent), like light_on.
    stream_active = Bool(False, desc="LED board control active")

    # Fired by the controller when a lighting edit is staged because the
    # stream is off; the dock pane shows a one-time warning in response.
    stream_off_edit_warning = Event()

    # Render the live ASI feed in the device viewer's video layer. On by
    # default; uncheck for a smoother GUI — full-resolution sensor frames
    # under the electrodes cost rendering time, and the image viewer pane
    # previews captures regardless.
    device_viewer_stream = Bool(True)

    # Software auto-exposure / auto-gain: the capture thread converges the
    # frame brightness on the Auto-tab target (advanced camera pane) within
    # its limits; the manual sliders are ignored (and disabled) while on.
    auto_exposure = Bool(True)
    auto_gain = Bool(True)

    # Brightfield LED set.
    br_wavelength = Enum(*LED_WAVELENGTHS)
    br_intensity = Range(
        LED_DUTY_MIN, LED_DUTY_MAX, value=BR_INTENSITY_DEFAULT, mode="slider",
        desc="brightfield LED duty to apply (%)",
    )
    br_frequency = Range(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=BR_FREQUENCY_DEFAULT, mode="xslider",
        desc="brightfield LED PWM frequency (Hz)",
    )
    br_exposure = RangeWithViewHints(
        float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=float(BR_EXPOSURE_DEFAULT),
        desc="brightfield camera exposure (milliseconds)",
    )
    br_gain = Range(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=BR_GAIN_DEFAULT, mode="slider",
        desc="brightfield camera gain",
    )

    # Fluorescence LED set.
    fl_wavelength = Enum(*LED_WAVELENGTHS)
    fl_intensity = Range(
        LED_DUTY_MIN, LED_DUTY_MAX, value=FL_INTENSITY_DEFAULT, mode="slider",
        desc="fluorescence LED duty to apply (%)",
    )
    fl_frequency = Range(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=FL_FREQUENCY_DEFAULT, mode="xslider",
        desc="fluorescence LED PWM frequency (Hz)",
    )
    fl_exposure = RangeWithViewHints(
        float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=float(FL_EXPOSURE_DEFAULT),
        desc="fluorescence camera exposure (milliseconds)",
    )
    fl_gain = Range(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=FL_GAIN_DEFAULT, mode="slider",
        desc="fluorescence camera gain",
    )

    preferences = Instance(FluorescencePreferences, FluorescencePreferences())

    #: Guards the two-way preferences sync against echoing its own writes
    #: (declared trait, so the pull observer can read it in any ordering).
    _self_preference_change = Bool(False)

    def traits_init(self):
        logger.debug(f"Fluorescence Status Model: Initial fluorescence preferences to model sync")
        self._self_preference_change = True
        self.trait_set(**{key: self.preferences.trait_get(key)[key] for key in PERSISTED_CONTROL_TRAITS})
        self._self_preference_change = False # private trait to stop pull preference observer acting on self updates

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

    @observe(f"[{','.join(PERSISTED_CONTROL_TRAITS)}]", post_init=True)
    def _push_preferences(self, event):
        logger.debug(f"Fluorescence Status Model: Saving preferences event: {event}")
        self._self_preference_change = True
        self.preferences.trait_set(**{event.name: event.new})
        self._self_preference_change = False

    @observe(parse("preferences").match(lambda name, trait: name in PERSISTED_CONTROL_TRAITS))
    def _pull_preferences(self, event):
        if not self._self_preference_change:
            logger.debug(f"Fluorescence Status Model: Syncing changed preferences values into model: {event}")
            self.trait_set(**{event.name: event.new})