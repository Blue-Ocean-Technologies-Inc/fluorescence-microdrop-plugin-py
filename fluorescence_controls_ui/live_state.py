"""Live (non-persisted) fluorescence pane state shared inside the plugin.

The pane mirrors every persisted control into FluorescencePreferences as it
changes (PERSISTED_CONTROL_TRAITS) and the camera state into the shared
``asi_camera_settings`` — but the master light toggle is deliberately never
persisted (the light always starts OFF). The protocol column's
snapshot-on-toggle still needs the CURRENT light state, so the controls
controller mirrors it here.

This singleton also carries the pane <-> protocol-step live-tracking state
(device-viewer semantics): which selected step the pane re-snapshots into,
and the GUI-thread events through which step/protocol-origin snapshots
load INTO the pane.
"""
from traits.api import Bool, Event, HasTraits, Str


class FluorescenceLiveState(HasTraits):
    """Pane state that is intentionally not persisted anywhere."""

    #: The pane's master light toggle, mirrored live by the controller.
    light_on = Bool(False)

    #: uuid of the protocol step the pane live-tracks: the tree's selected
    #: step whose fluorescence cell holds a snapshot. Pane edits re-snapshot
    #: into that step; "" = free mode / group / unchecked step selected.
    tracked_step_uuid = Str()

    #: True while step/protocol-origin settings are being loaded INTO the
    #: pane, so the controller's push-back-to-step observer does not echo
    #: the load as a fresh pane edit.
    loading_step_snapshot = Bool(False)

    #: Snapshot dict fired (on the GUI thread) when the user selects a step
    #: whose fluorescence cell is set — the pane loads it and, when idle,
    #: drives the hardware exactly as if the settings were made manually.
    step_snapshot_selected = Event()

    #: Snapshot dict fired (on the GUI thread) as a running protocol applies
    #: a step's fluorescence settings — the pane mirrors it visually (its
    #: hardware publishes are gated during a run). May be partial: the run's
    #: end fires {"light_on": False}.
    protocol_step_settings_applied = Event()


#: Module-level singleton shared inside the fluorescence plugin.
fluorescence_live_state = FluorescenceLiveState()
