import json

from traits.api import observe

from template_status_and_controls.base_controller import BaseStatusController
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from microdrop_utils.traitsui_qt_helpers import stretch_group_layouts_horizontally
from logger.logger_service import get_logger

from fluorescence_protocol_controls.consts import (
    FLUORESCENCE_SETTINGS_COLUMN_ID, STEP_SETTING_TRAITS,
)
from pluggable_protocol_tree.consts import protocol_tree_set_cell_publisher

from .cameras.camera_settings import (
    ADVANCED_CAMERA_TRAITS, asi_camera_settings,
)
from .cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from .live_state import fluorescence_live_state
from .consts import (
    ALL_LEDS_OFF, EXPOSURE_MS_MAX, EXPOSURE_MS_MIN, SET_LED,
    SET_LED_FREQUENCY,
)

logger = get_logger(__name__)

#: Live-state events through which step/protocol-origin snapshots load into
#: the pane (fired on the GUI thread; hooked in the controller's init).
SNAPSHOT_LOAD_EVENTS_EXPRESSION = (
    "[step_snapshot_selected,protocol_step_settings_applied]")
#: The advanced camera settings are part of a step snapshot, so their edits
#: also re-snapshot the tracked step.
ADVANCED_CAMERA_TRAITS_EXPRESSION = f"[{','.join(ADVANCED_CAMERA_TRAITS)}]"


class FluorescenceControlsController(BaseStatusController):
    """Fluorescence LED controls controller — port of the standalone app's
    LED slots (on_light_button_click, update_br_/fl_ handlers).

    Live-command gating matches the original exactly: edits publish only
    while the light is on AND the edited set's mode is active ("br" edits in
    br mode, "fl" edits in fl mode; in dual mode edits are staged and the
    light toggle drives the brightfield set). Wavelength switches publish ONE
    exclusive set_led request — the backend runs the legacy off->on sequence
    atomically (two pub/sub messages would have no ordering guarantee).

    The standalone 0.5 s duplicate-command debounce is unnecessary here:
    trait observers only fire on actual value changes.

    Run gating (device-viewer semantics): while a protocol runs, the
    protocol steps own the LED board and camera — every hardware publish
    here is gated on ``model.protocol_running`` and the pane becomes a
    passive mirror of what the run applies. Idle, the pane also
    live-tracks the tree's selected step: a step whose fluorescence cell
    holds a snapshot loads into the pane (and drives the hardware exactly
    like manual edits), and any pane edit re-snapshots into that step.
    """

    # ------------------------------------------------------------------ #
    # UI build hook                                                        #
    # ------------------------------------------------------------------ #
    def init(self, info):
        """Stretch the collapsible sections to the full pane width once the UI
        is built (TraitsUI otherwise left-hugs each group to its content),
        and hook the pane <-> protocol-step live-tracking observers on the
        shared singletons."""
        stretch_group_layouts_horizontally(info.ui.control)
        fluorescence_live_state.observe(
            self._load_step_snapshot, SNAPSHOT_LOAD_EVENTS_EXPRESSION)
        asi_camera_settings.observe(
            self._push_snapshot_to_tracked_step,
            ADVANCED_CAMERA_TRAITS_EXPRESSION)
        return super().init(info)

    def closed(self, info, is_ok):
        """Unhook the singleton observers wired in init (the pane can be
        unmounted and remounted at runtime via plugin hot load)."""
        fluorescence_live_state.observe(
            self._load_step_snapshot, SNAPSHOT_LOAD_EVENTS_EXPRESSION,
            remove=True)
        asi_camera_settings.observe(
            self._push_snapshot_to_tracked_step,
            ADVANCED_CAMERA_TRAITS_EXPRESSION, remove=True)
        return super().closed(info, is_ok)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _publish(topic, payload):
        publish_message(message=json.dumps(payload), topic=topic)

    def _active_led_payload(self, exclusive=False):
        """The LED the light toggle drives: brightfield in br/dual mode
        (the original's abs/double branch), fluorescence in fl mode."""
        if self.model.mode == "fl":
            payload = {"led": self.model.fl_led_index, "duty": self.model.fl_intensity}
        else:
            payload = {"led": self.model.br_led_index, "duty": self.model.br_intensity}
        if exclusive:
            payload["exclusive"] = True
        return payload

    # ------------------------------------------------------------------ #
    # Controller Interface                                                 #
    # ------------------------------------------------------------------ #
    def br_frequency_setattr(self, info, object, traitname, value):
        return super().setattr(info, object, traitname, int(value))

    def fl_frequency_setattr(self, info, object, traitname, value):
        return super().setattr(info, object, traitname, int(value))

    # ------------------------------------------------------------------ #
    # Master light toggle                                                  #
    # ------------------------------------------------------------------ #
    @observe("model:light_on")
    def _light_toggled(self, event):
        # Mirror the live light state for the protocol column's snapshot
        # (light_on is deliberately never persisted — see live_state).
        fluorescence_live_state.light_on = bool(event.new)
        # During a run the protocol steps command the LEDs; the pane's
        # toggle only mirrors their state.
        if self.model.protocol_running:
            return
        if not self.model.stream_active:
            # Staged: applies when the stream starts. Snapshot loads stage
            # silently — the toggle wasn't a user edit.
            if event.new and not fluorescence_live_state.loading_step_snapshot:
                self.model.stream_off_edit_warning = True
            return
        if event.new:
            self._publish(SET_LED, self._active_led_payload())
        else:
            self._publish(ALL_LEDS_OFF, {})

    # ------------------------------------------------------------------ #
    # Stream master gate (heater pane parity)                             #
    # ------------------------------------------------------------------ #
    @observe("model:stream_active")
    def _stream_toggled(self, event):
        """Starting re-asserts the staged lighting state: the active set's
        frequency, then the light as one exclusive off->on set if staged
        on. Stopping turns the lights out and forces the light toggle off
        — the board is silent while the stream is off."""
        if self.model.protocol_running:
            return
        if event.new:
            fl_mode = self.model.mode == "fl"
            self._publish(SET_LED_FREQUENCY, {
                "led": self.model.fl_led_index if fl_mode
                else self.model.br_led_index,
                "frequency": self.model.fl_frequency if fl_mode
                else self.model.br_frequency,
            })
            if self.model.light_on:
                self._publish(SET_LED,
                              self._active_led_payload(exclusive=True))
        else:
            # Forcing the toggle off is a stream-session action, not a
            # step edit — it must not re-snapshot into a tracked step.
            # The light toggle observer publishes nothing here either
            # (the gate is already off); one explicit all-off silences
            # the board.
            fluorescence_live_state.loading_step_snapshot = True
            try:
                self.model.light_on = False
            finally:
                fluorescence_live_state.loading_step_snapshot = False
            self._publish(ALL_LEDS_OFF, {})

    # ------------------------------------------------------------------ #
    # Brightfield set (live only in br mode, light on, stream on, idle)    #
    # ------------------------------------------------------------------ #
    def _br_live(self):
        return (self.model.stream_active and self.model.light_on
                and self.model.mode == "br"
                and not self.model.protocol_running)

    @observe("model:br_intensity")
    def _br_intensity_changed(self, event):
        if self._br_live():
            self._publish(SET_LED, {"led": self.model.br_led_index, "duty": event.new})

    @observe("model:br_frequency")
    def _br_frequency_changed(self, event):
        if self._br_live():
            self._publish(SET_LED_FREQUENCY,
                          {"led": self.model.br_led_index, "frequency": event.new})

    @observe("model:br_wavelength")
    def _br_wavelength_changed(self, event):
        if self._br_live():
            self._publish(SET_LED, self._active_led_payload(exclusive=True))

    # ------------------------------------------------------------------ #
    # Fluorescence set (live only in fl mode, light on, stream on, idle)   #
    # ------------------------------------------------------------------ #
    def _fl_live(self):
        return (self.model.stream_active and self.model.light_on
                and self.model.mode == "fl"
                and not self.model.protocol_running)

    @observe("model:fl_intensity")
    def _fl_intensity_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED, {"led": self.model.fl_led_index, "duty": event.new})

    @observe("model:fl_frequency")
    def _fl_frequency_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED_FREQUENCY,
                          {"led": self.model.fl_led_index, "frequency": event.new})

    @observe("model:fl_wavelength")
    def _fl_wavelength_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED, self._active_led_payload(exclusive=True))

    # ------------------------------------------------------------------ #
    # Camera settings (per-mode, like the standalone UI's br_/fl_          #
    # exposure/gain): the CURRENT mode's pair is mirrored into the shared  #
    # ASI settings, which the running camera feed applies live. The pane   #
    # is the ONLY editor — the device viewer shows no settings row.        #
    # ------------------------------------------------------------------ #
    def _camera_mode_is_fl(self):
        return self.model.mode == "fl"

    @observe("model:mode")
    @observe("model:br_exposure")
    @observe("model:br_gain")
    @observe("model:fl_exposure")
    @observe("model:fl_gain")
    def _push_active_camera_settings(self, event):
        # During a run the protocol column mirrors each step's camera
        # state into the shared ASI settings itself.
        if self.model.protocol_running:
            return
        # The pane shows milliseconds; the camera takes microseconds.
        if self._camera_mode_is_fl():
            asi_camera_settings.exposure = int(self.model.fl_exposure * 1000)
            asi_camera_settings.gain = int(self.model.fl_gain)
        else:
            asi_camera_settings.exposure = int(self.model.br_exposure * 1000)
            asi_camera_settings.gain = int(self.model.br_gain)

    @observe("model:device_viewer_stream")
    def _push_device_viewer_stream(self, event):
        asi_camera_settings.device_viewer_stream = self.model.device_viewer_stream

    @observe("model:auto_exposure")
    @observe("model:auto_gain")
    def _push_auto_flags(self, event):
        # During a run the protocol column mirrors each step's auto flags
        # into the shared ASI settings itself.
        if self.model.protocol_running:
            return
        asi_camera_settings.auto_exposure = self.model.auto_exposure
        asi_camera_settings.auto_gain = self.model.auto_gain
        # Toggling auto OFF adopts the camera's converged value as the
        # manual setting for the active mode (persisted via the model's
        # preference push), so disabling auto keeps the current look
        # instead of snapping back to the stale manual value.
        if event:
            if event.old and not event.new:
                self._adopt_auto_value(event.name)

    def _adopt_auto_value(self, auto_flag_name):
        prefix = "fl" if self._camera_mode_is_fl() else "br"
        if auto_flag_name == "auto_exposure":
            exposure_us = asi_camera_settings.auto_current_exposure
            if exposure_us < 0:   # no camera report yet
                return
            # The camera runs microseconds; the pane shows milliseconds,
            # clamped to the manual slider's range.
            setattr(self.model, f"{prefix}_exposure",
                    min(max(exposure_us / 1000.0, float(EXPOSURE_MS_MIN)),
                        float(EXPOSURE_MS_MAX)))
        else:
            gain = asi_camera_settings.auto_current_gain
            if gain < 0:   # no camera report yet
                return
            setattr(self.model, f"{prefix}_gain",
                    int(min(max(gain, ASI_GAIN_MIN), ASI_GAIN_MAX)))

    # ------------------------------------------------------------------ #
    # Protocol-step live tracking (device-viewer semantics): selecting a  #
    # checked step loads its snapshot into the pane; while it stays        #
    # selected, pane edits re-snapshot into it via the tree's set_cell.    #
    # ------------------------------------------------------------------ #
    def _current_step_snapshot(self):
        """The pane's state in the step-snapshot dict shape: the scalar
        controls from the model, the advanced camera settings from the
        shared ASI settings."""
        snapshot = {name: getattr(self.model, name)
                    for name in STEP_SETTING_TRAITS}
        snapshot["advanced"] = {
            name: getattr(asi_camera_settings, name)
            for name in ADVANCED_CAMERA_TRAITS}
        return snapshot

    def _load_step_snapshot(self, event):
        """Apply a step snapshot (possibly partial) to the pane. Idle, the
        model observers then drive the hardware exactly as for manual
        edits; during a run they are gated and the pane just mirrors.
        light_on applies LAST so its SET_LED publish uses the loaded LED
        values. Invalid stored entries are skipped so a stale protocol
        file cannot break the pane."""
        snapshot = event.new
        if (not isinstance(snapshot, dict)
                or snapshot == self._current_step_snapshot()):
            return
        fluorescence_live_state.loading_step_snapshot = True
        try:
            for name in STEP_SETTING_TRAITS:
                if name == "light_on" or name not in snapshot:
                    continue
                try:
                    setattr(self.model, name, snapshot[name])
                except Exception as e:
                    logger.warning(
                        f"Pane keeps its value for {name}: {e}")
            advanced = {
                name: stored
                for name, stored in (snapshot.get("advanced") or {}).items()
                if name in ADVANCED_CAMERA_TRAITS}
            if advanced:
                try:
                    asi_camera_settings.trait_set(**advanced)
                except Exception as e:
                    logger.warning(
                        f"Advanced camera settings not fully applied: {e}")
            if "light_on" in snapshot:
                self.model.light_on = bool(snapshot["light_on"])
        finally:
            fluorescence_live_state.loading_step_snapshot = False

    @observe(f"model:[{','.join(STEP_SETTING_TRAITS)}]")
    def _push_snapshot_to_tracked_step(self, event):
        """Re-snapshot the pane into the live-tracked step on any pane
        edit (the advanced camera settings route here too — hooked in
        init). Loads must not echo back, and a run's mirrored values must
        not rewrite steps, so both are gated."""
        if (fluorescence_live_state.loading_step_snapshot
                or self.model.protocol_running
                or not fluorescence_live_state.tracked_step_uuid):
            return
        protocol_tree_set_cell_publisher.publish(
            step_id=fluorescence_live_state.tracked_step_uuid,
            col_id=FLUORESCENCE_SETTINGS_COLUMN_ID,
            value=self._current_step_snapshot(),
            only_if_set=True)
