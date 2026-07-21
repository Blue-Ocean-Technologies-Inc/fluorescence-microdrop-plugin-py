from traits.api import (
    Bool, Button, Enum, Event, Instance, List, Range, Str, observe,
)
from traits.observation.api import parse

from microdrop_utils.traitsui_qt_helpers import RangeWithViewHints

from template_status_and_controls.base_model import BaseStatusModel

from .cameras.consts import ASI_GAIN_MIN, ASI_GAIN_MAX
from .chain_model import FluorescenceChainRow
from .consts import (
    disconnected_color, connected_color, halted_color,
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
    INTENSITY_DEFAULT, FREQUENCY_DEFAULT,
    EXPOSURE_DEFAULT, GAIN_DEFAULT,
    EXPOSURE_MS_MIN, EXPOSURE_MS_MAX, PERSISTED_CONTROL_TRAITS,
)

from logger.logger_service import get_logger
from .preferences import FluorescencePreferences

logger = get_logger(__name__)


class FluorescenceStatusModel(BaseStatusModel):
    """Model for fluorescence LED controls (port of the standalone app's
    per-mode brightfield/fluorescence LED state).

    A single LED/camera param set now drives whichever chain row is being
    edited (the mode/br_/fl_ split is gone — see the capture-chain design);
    the master light toggle applies it directly, with no mode gating.
    """

    DISCONNECTED_COLOR = Str(disconnected_color)
    # No "connected but no chip" sub-state on the LED board — the base model
    # parks connected devices on CONNECTED_NO_DEVICE_COLOR until a DropBot
    # chip_inserted signal that never comes, so connected maps straight to green.
    CONNECTED_NO_DEVICE_COLOR = Str(connected_color)
    CONNECTED_COLOR = Str(connected_color)
    HALTED_COLOR = Str(halted_color)

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

    # Single LED/camera param set (defaults match the old brightfield row).
    # Chain-row labels are DERIVED (image_tag_wavelength_index, read-only
    # in the table); the panel edits only this optional tag.
    image_tag = Str("")
    # Protocol phase(s) a capture fires in (per-row, edited via the panel
    # like every other param): step start, step end, or both. The view's
    # enabled_when guards keep at least one on.
    capture_start = Bool(True)
    capture_end = Bool(False)
    wavelength = Enum(*LED_WAVELENGTHS)
    intensity = Range(
        LED_DUTY_MIN, LED_DUTY_MAX, value=INTENSITY_DEFAULT, mode="slider",
        desc="LED duty to apply (%)",
    )
    frequency = Range(
        LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=FREQUENCY_DEFAULT, mode="xslider",
        desc="LED PWM frequency (Hz)",
    )
    exposure = RangeWithViewHints(
        float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=float(EXPOSURE_DEFAULT),
        desc="camera exposure (milliseconds)",
    )
    gain = Range(
        ASI_GAIN_MIN, ASI_GAIN_MAX, value=GAIN_DEFAULT, mode="slider",
        desc="camera gain",
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
    show_params = Bool(True, desc="Expand the LED/camera params section")

    @property
    def led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.wavelength)

    # ------------------------------------------------------------------ #
    # Capture-chain state                                                  #
    # ------------------------------------------------------------------ #
    #: The chain currently shown in the table: either a step/group's
    #: attached chain, or `free_chain` while `attached_step_id == ""`.
    chain_rows = List(Instance(FluorescenceChainRow))
    #: The selected row (the TableEditor's `selected=` binds an object,
    #: not an index).
    chain_selection = Instance(FluorescenceChainRow)
    #: uuid of the protocol step `chain_rows` is attached to; "" = free mode.
    attached_step_id = Str("")
    #: uuid of the protocol step-group `chain_rows` is attached to.
    attached_group_id = Str("")
    #: Display context of the attached step, read from the row_selected
    #: broadcast's `name`/`id` cells — names a pane-initiated burst folder
    #: exactly like a protocol-run burst (`<desc>_<dotted>_<utc>`).
    attached_step_desc = Str("")
    attached_step_dotted = Str("")
    #: The unattached stash, shown whenever `attached_step_id == ""`.
    free_chain = List(Instance(FluorescenceChainRow))

    # Chain-table buttons (Qt-free `Button` traits, same convention as the
    # advanced-camera pane's "Defaults" buttons): the view fires these on
    # click, the controller observes them and runs the actual add/run
    # logic (`FluorescenceControlsController.add_capture`/`run_capture`) —
    # that logic needs controller-level access (chain write-back,
    # threading), so it stays out of the model.
    # Button labels are Material Symbols glyph names: the app-wide
    # BASE_BUTTON_STYLE puts the icon font on every QPushButton, so a
    # Button("play_circle") renders as a glyph — same scheme as the route
    # view's run_controls (device_viewer/models/route.py:203-208).
    add_capture_button = Button("add")
    run_capture_button = Button("play_circle")
    delete_capture_button = Button("delete")
    #: Capture ONLY the selected row now (Run Capture bursts all ticked).
    capture_selected_button = Button("photo_camera")
    #: Reposition the selected row (drag-reorder is disabled: TableEditor
    #: drops fire remove+insert as separate list events, which raced the
    #: per-mutation persistence into losing rows).
    move_up_button = Button("arrow_upward")
    move_down_button = Button("arrow_downward")

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
