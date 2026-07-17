import json
import threading

from traits.api import Bool, observe

from template_status_and_controls.base_controller import BaseStatusController
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from microdrop_utils.traitsui_qt_helpers import stretch_group_layouts_horizontally
from microdrop_application.dialogs.pyface_wrapper import choose
from logger.logger_service import get_logger

from pluggable_protocol_tree.consts import (
    protocol_tree_add_step_publisher, protocol_tree_set_cell_publisher,
)

from fluorescence_protocol_controls.capture_chain import (
    ChainEntry, dump_chain, parse_chain, sanitize_label, ticked,
    unique_label,
)
from fluorescence_protocol_controls.consts import FLUORESCENCE_CHAIN_COLUMN_ID

from .cameras.camera_settings import asi_camera_settings
from .cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from .chain_model import FluorescenceChainRow
from .live_state import fluorescence_live_state
from .consts import (
    ALL_LEDS_OFF, EXPOSURE_MS_MAX, EXPOSURE_MS_MIN, SET_LED,
    SET_LED_FREQUENCY,
)

logger = get_logger(__name__)

#: The panel<->chain-row params kept in lockstep by the live binding: a
#: row click loads these into the panel (driving the LED live through the
#: existing single-set observers below), a panel edit re-saves them into
#: the selected row.
CHAIN_ROW_PARAM_TRAITS = (
    "label", "wavelength", "intensity", "frequency", "exposure", "gain")
CHAIN_ROW_PARAM_TRAITS_EXPRESSION = f"[{','.join(CHAIN_ROW_PARAM_TRAITS)}]"


class FluorescenceControlsController(BaseStatusController):
    """Fluorescence LED controls controller — port of the standalone app's
    LED slots (on_light_button_click, update_*), reworked around a single
    LED/camera param set (issue #6): the br/fl/dual mode split is gone.
    The panel doubles as the editor for whichever capture-chain row is
    selected — a row click loads its params into the panel (driving the
    LED live, exactly like a manual edit, via the same observers below)
    and a panel edit re-saves into the selected row and pushes the chain
    out to wherever it lives (an attached step's cell, or the free-mode
    stash).

    Live-command gating: edits publish only while the stream is on AND
    the light is on AND idle (``_live()``). Wavelength switches publish
    ONE exclusive set_led request — the backend runs the legacy off->on
    sequence atomically (two pub/sub messages would have no ordering
    guarantee).

    The standalone 0.5 s duplicate-command debounce is unnecessary here:
    trait observers only fire on actual value changes.

    Run gating (device-viewer semantics): while a protocol runs, the
    protocol steps own the LED board and camera — every hardware publish
    here is gated on ``model.protocol_running`` and the pane becomes a
    passive mirror of what the run applies.

    Capture-chain / free-mode attach flow: the pane live-tracks the
    protocol tree's selected row (``PROTOCOL_TREE_ROW_SELECTED``, ferried
    through ``live_state.tree_row_selected``). A selected step's chain
    loads into the pane; a group or deselection returns to free mode; a
    free-mode chain holding unsaved captures offers the operator a
    four-way Append / Replace / New step / Cancel choice before the pane
    switches away from it (see ``_on_tree_row_selected``).
    """

    #: Guards the panel<->row live binding against write-back loops while
    #: a row selection is loading its values into the panel traits.
    _loading_row = Bool(False)
    #: Guards the label re-uniquify observer against its own rewrite.
    _relabeling = Bool(False)

    # ------------------------------------------------------------------ #
    # UI build hook                                                        #
    # ------------------------------------------------------------------ #
    def init(self, info):
        """Stretch the collapsible sections to the full pane width once the
        UI is built (TraitsUI otherwise left-hugs each group to its
        content), and hook the tree-row-selection live-tracking observer
        on the shared live-state singleton."""
        stretch_group_layouts_horizontally(info.ui.control)
        fluorescence_live_state.observe(
            self._on_tree_row_selected, "tree_row_selected", dispatch="ui")
        return super().init(info)

    def closed(self, info, is_ok):
        """Unhook the singleton observer wired in init (the pane can be
        unmounted and remounted at runtime via plugin hot load)."""
        fluorescence_live_state.observe(
            self._on_tree_row_selected, "tree_row_selected", dispatch="ui",
            remove=True)
        return super().closed(info, is_ok)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _publish(topic, payload):
        publish_message(message=json.dumps(payload), topic=topic)

    def _active_led_payload(self, exclusive=False):
        """The single LED/camera param set's LED, as a set_led payload."""
        payload = {"led": self.model.led_index, "duty": self.model.intensity}
        if exclusive:
            payload["exclusive"] = True
        return payload

    def _live(self):
        return (self.model.stream_active and self.model.light_on
                and not self.model.protocol_running)

    # ------------------------------------------------------------------ #
    # Controller Interface                                                 #
    # ------------------------------------------------------------------ #
    def frequency_setattr(self, info, object, traitname, value):
        return super().setattr(info, object, traitname, int(value))

    # ------------------------------------------------------------------ #
    # Master light toggle                                                  #
    # ------------------------------------------------------------------ #
    @observe("model:light_on")
    def _light_toggled(self, event):
        # Mirror the live light state (deliberately never persisted).
        fluorescence_live_state.light_on = bool(event.new)
        # During a run the protocol steps command the LEDs; the pane's
        # toggle only mirrors their state.
        if self.model.protocol_running:
            return
        if not self.model.stream_active:
            # Staged: applies when the stream starts.
            if event.new:
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
        """Starting re-asserts the staged lighting state: the set's
        frequency, then the light as one exclusive off->on set if staged
        on. Stopping turns the lights out and forces the light toggle off
        — the board is silent while the stream is off."""
        if self.model.protocol_running:
            return
        if event.new:
            self._publish(SET_LED_FREQUENCY, {
                "led": self.model.led_index,
                "frequency": self.model.frequency,
            })
            if self.model.light_on:
                self._publish(SET_LED,
                              self._active_led_payload(exclusive=True))
        else:
            # Forcing the toggle off is a stream-session action; one
            # explicit all-off silences the board (the light toggle
            # observer publishes nothing here — the gate is already off).
            self.model.light_on = False
            self._publish(ALL_LEDS_OFF, {})

    # ------------------------------------------------------------------ #
    # Single LED/camera param set (live only while lit, stream on, idle)   #
    # ------------------------------------------------------------------ #
    @observe("model:intensity")
    def _intensity_changed(self, event):
        if self._live():
            self._publish(SET_LED,
                          {"led": self.model.led_index, "duty": event.new})

    @observe("model:frequency")
    def _frequency_changed(self, event):
        if self._live():
            self._publish(SET_LED_FREQUENCY,
                          {"led": self.model.led_index, "frequency": event.new})

    @observe("model:wavelength")
    def _wavelength_changed(self, event):
        if self._live():
            self._publish(SET_LED, self._active_led_payload(exclusive=True))

    # ------------------------------------------------------------------ #
    # Camera settings — the pane is the ONLY editor (no device-viewer      #
    # settings row): pushed straight into the shared ASI settings, which  #
    # a running camera feed applies live.                                 #
    # ------------------------------------------------------------------ #
    @observe("model:exposure")
    @observe("model:gain")
    def _push_camera_settings(self, event):
        # During a run the protocol column mirrors each step's camera
        # state into the shared ASI settings itself.
        if self.model.protocol_running:
            return
        # The pane shows milliseconds; the camera takes microseconds.
        asi_camera_settings.exposure = int(self.model.exposure * 1000)
        asi_camera_settings.gain = int(self.model.gain)

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
        # manual setting (persisted via the model's preference push), so
        # disabling auto keeps the current look instead of snapping back
        # to the stale manual value.
        if event:
            if event.old and not event.new:
                self._adopt_auto_value(event.name)

    def _adopt_auto_value(self, auto_flag_name):
        if auto_flag_name == "auto_exposure":
            exposure_us = asi_camera_settings.auto_current_exposure
            if exposure_us < 0:   # no camera report yet
                return
            # The camera runs microseconds; the pane shows milliseconds,
            # clamped to the manual slider's range.
            self.model.exposure = min(
                max(exposure_us / 1000.0, float(EXPOSURE_MS_MIN)),
                float(EXPOSURE_MS_MAX))
        else:
            gain = asi_camera_settings.auto_current_gain
            if gain < 0:   # no camera report yet
                return
            self.model.gain = int(min(max(gain, ASI_GAIN_MIN), ASI_GAIN_MAX))

    # ------------------------------------------------------------------ #
    # Panel <-> chain-row live binding                                     #
    # ------------------------------------------------------------------ #
    @observe("model:chain_selection")
    def _load_selected_row(self, event):
        """A row click loads its params into the panel. `wavelength` is
        set LAST so its exclusive SET_LED publish (below) carries the
        row's already-updated intensity — that firing IS the
        row-click-drives-LED rule."""
        row = event.new
        if row is None:
            return
        self._loading_row = True
        try:
            self.model.label = row.label
            self.model.intensity = row.intensity
            self.model.frequency = row.frequency
            self.model.exposure = row.exposure
            self.model.gain = row.gain
            self.model.wavelength = row.wavelength
        finally:
            self._loading_row = False

    @observe(f"model:{CHAIN_ROW_PARAM_TRAITS_EXPRESSION}")
    def _sync_panel_to_selected_row(self, event):
        """A panel edit re-saves into the selected row (guarded against
        echoing a row-click load) and pushes the chain out."""
        if self._loading_row or self.model.chain_selection is None:
            return
        setattr(self.model.chain_selection, event.name, event.new)
        self._push_chain_to_step()

    @observe("model:chain_rows:items:label")
    def _relabel_on_collision(self, event):
        """A label edit (panel or direct table edit) that collides with
        another row in the chain gets suffixed uniquely. Reentrant: the
        rewrite below re-fires this same observer, guarded off."""
        if self._relabeling:
            return
        row = event.object
        others = {r.label for r in self.model.chain_rows if r is not row}
        unique = unique_label(row.label, others)
        if unique != row.label:
            self._relabeling = True
            try:
                row.label = unique
            finally:
                self._relabeling = False
        self._push_chain_to_step()

    def _push_chain_to_step(self):
        """Persist `chain_rows` to wherever it currently lives: an
        attached step's cell (tree write-back, blanking the cell when the
        chain empties), or the free-mode stash (nothing to write to the
        tree while unattached)."""
        if self.model.attached_step_id:
            entries = [ChainEntry(**r.to_entry_dict())
                       for r in self.model.chain_rows]
            protocol_tree_set_cell_publisher.publish(
                step_id=self.model.attached_step_id,
                col_id=FLUORESCENCE_CHAIN_COLUMN_ID,
                value=dump_chain(entries) or None)
        else:
            self.model.free_chain = list(self.model.chain_rows)

    # ------------------------------------------------------------------ #
    # Chain-table button wiring (model:add_capture_button/run_capture_button
    # are Button traits — see model.py; the click fires an Event, the value
    # itself is unused here, only the firing matters).                      #
    # ------------------------------------------------------------------ #
    @observe("model:add_capture_button")
    def _add_capture_button_clicked(self, event):
        self.add_capture()

    @observe("model:run_capture_button")
    def _run_capture_button_clicked(self, event):
        self.run_capture()

    # ------------------------------------------------------------------ #
    # Add                                                                   #
    # ------------------------------------------------------------------ #
    def add_capture(self):
        """Append a new row seeded from the panel's current values,
        select it (re-loading it into the panel — a no-op except for the
        uniquified label), and persist the chain."""
        existing_labels = {r.label for r in self.model.chain_rows}
        label = unique_label(
            sanitize_label(self.model.label or self.model.wavelength),
            existing_labels)
        row = FluorescenceChainRow(
            label=label, wavelength=self.model.wavelength,
            intensity=self.model.intensity, frequency=self.model.frequency,
            exposure=self.model.exposure, gain=self.model.gain)
        self.model.chain_rows = self.model.chain_rows + [row]
        self.model.chain_selection = row
        self._push_chain_to_step()

    # ------------------------------------------------------------------ #
    # Free-mode attach flow                                                #
    # ------------------------------------------------------------------ #
    def _suffixed(self, rows, existing):
        """`rows` (free-mode chain rows) as `ChainEntry` objects, labels
        re-uniquified against `existing`'s labels (and each other) so an
        Append never collides."""
        used = {e.label for e in existing}
        suffixed = []
        for row in rows:
            entry = ChainEntry(**row.to_entry_dict())
            label = unique_label(entry.label, used)
            if label != entry.label:
                entry = entry.model_copy(update={"label": label})
            used.add(entry.label)
            suffixed.append(entry)
        return suffixed

    def _attach_to_step(self, step_id, entries):
        """Adopt `entries` (a list[ChainEntry]) as the pane's chain,
        attached to `step_id`, and push the write-back."""
        self.model.attached_step_id = step_id
        self.model.attached_group_id = ""
        self.model.chain_selection = None
        self.model.chain_rows = [
            FluorescenceChainRow.from_entry(e) for e in entries]
        self._push_chain_to_step()

    def _load_step_chain(self, step_id, cells):
        """Plain step selection: no free-mode captures were in play, so
        just load the step's own stored chain.

        A panel edit on this same attached step publishes set_cell, which
        the tree applies and then rebroadcasts PROTOCOL_TREE_ROW_SELECTED
        for the still-selected step — that echo lands right back here. If
        the incoming chain matches what `chain_rows` already holds, this
        is that echo (not a genuine external change): skip the reload so
        `chain_selection` survives it."""
        entries = parse_chain(cells.get(FLUORESCENCE_CHAIN_COLUMN_ID))
        if step_id == self.model.attached_step_id and [
                e.model_dump() for e in entries] == [
                r.to_entry_dict() for r in self.model.chain_rows]:
            return
        self.model.attached_step_id = step_id
        self.model.attached_group_id = ""
        self.model.chain_selection = None
        self.model.chain_rows = [
            FluorescenceChainRow.from_entry(e) for e in entries]

    def _enter_free_mode(self):
        """Group selected, or nothing selected: restore the free-mode
        stash into the visible chain."""
        self.model.attached_step_id = ""
        self.model.attached_group_id = ""
        self.model.chain_selection = None
        self.model.chain_rows = list(self.model.free_chain)

    def _clear_free_chain(self):
        """After a free-mode chain has been attached (or handed off to a
        brand-new step) it no longer needs stashing. If the pane is still
        showing free mode — the "New step" case, where the new step's
        uuid is not yet known — the visible chain empties too (documented
        deviation: the pane does not auto-follow the new step; the next
        click on it loads the chain)."""
        self.model.free_chain = []
        if self.model.attached_step_id == "":
            self.model.chain_rows = []

    def _on_tree_row_selected(self, event):
        """React to the tree's PROTOCOL_TREE_ROW_SELECTED broadcast
        (ferried from the worker-thread listener via
        `live_state.tree_row_selected`, dispatch="ui" hooked in init()).
        A free-mode chain with unsaved captures blocks a switch to a
        step/group until the operator resolves the attach dialog — safe
        to be modal here since this observer runs on the GUI thread,
        never inside a table commit."""
        free = (list(self.model.free_chain)
                if self.model.attached_step_id == "" else [])
        msg = event.new
        if msg.step_id:
            if free:
                n = len(free)
                choice = choose(
                    None,
                    f"The free-mode chain holds {n} capture"
                    f"{'s' if n != 1 else ''}. Attach to the selected step?",
                    title="Attach Capture Chain",
                    choices=["Append", "Replace", "New step"])
                if choice is None:
                    return                       # chain stays unattached
                if choice == "New step":
                    protocol_tree_add_step_publisher.publish(
                        after_step_id=msg.step_id,
                        cells={FLUORESCENCE_CHAIN_COLUMN_ID:
                               dump_chain([ChainEntry(**r.to_entry_dict())
                                           for r in free])},
                        name="Step (capture chain)")
                    self._clear_free_chain()
                    return                       # pane returns to empty free mode
                existing = parse_chain(
                    msg.cells.get(FLUORESCENCE_CHAIN_COLUMN_ID))
                if choice == "Append":
                    merged = existing + self._suffixed(free, existing)
                else:                            # Replace
                    merged = [ChainEntry(**r.to_entry_dict()) for r in free]
                self._attach_to_step(msg.step_id, merged)
                self._clear_free_chain()
                return
            self._load_step_chain(msg.step_id, msg.cells)   # plain selection
        elif msg.group_id:
            if free:
                n = len(free)
                choice = choose(
                    None,
                    f"The free-mode chain holds {n} capture"
                    f"{'s' if n != 1 else ''}. Add it as a new step in "
                    f"this group?",
                    title="Attach Capture Chain",
                    choices=["New step"])            # group: only New step
                if choice == "New step":
                    protocol_tree_add_step_publisher.publish(
                        group_id=msg.group_id,
                        cells={FLUORESCENCE_CHAIN_COLUMN_ID:
                               dump_chain([ChainEntry(**r.to_entry_dict())
                                           for r in free])},
                        name="Step (capture chain)")
                    self._clear_free_chain()
                    return
            self._enter_free_mode()
        else:
            self._enter_free_mode()

    # ------------------------------------------------------------------ #
    # Run Capture                                                          #
    # ------------------------------------------------------------------ #
    def run_capture(self):
        """Fire the current chain's ticked entries as a burst off the GUI
        thread. `capture_service` is Task 6's module and does not exist
        yet in this task, so the import is lazily deferred inside this
        method — it must never be imported at module load time."""
        if self.model.protocol_running:
            return
        entries = ticked(
            [ChainEntry(**r.to_entry_dict()) for r in self.model.chain_rows])
        if not entries:
            return

        from fluorescence_controls_ui import capture_service

        step_id = self.model.attached_step_id

        def _run():
            try:
                capture_service.run_burst(
                    entries, step_desc=None, step_id=step_id)
            except Exception as e:
                logger.error(f"Capture burst failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
