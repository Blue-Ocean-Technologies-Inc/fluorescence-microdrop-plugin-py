"""Live (non-persisted) fluorescence pane state shared inside the plugin.

The pane mirrors every persisted control into FluorescencePreferences as it
changes (PERSISTED_CONTROL_TRAITS) and the camera state into the shared
``asi_camera_settings`` — but the master light toggle is deliberately never
persisted (the light always starts OFF).

This singleton also carries the pane <-> protocol-tree live-tracking state
(device-viewer semantics): the GUI-thread event through which a tree row
selection reaches the controller's free-mode capture-chain attach flow.
"""
from traits.api import Bool, Event, HasTraits


class FluorescenceLiveState(HasTraits):
    """Pane state that is intentionally not persisted anywhere."""

    #: The pane's master light toggle, mirrored live by the controller.
    light_on = Bool(False)

    #: Parsed `ProtocolTreeRowSelectedMessage` ferried from the
    #: worker-thread PROTOCOL_TREE_ROW_SELECTED listener (message_handler
    #: .py) to the GUI thread: the controller observes this with
    #: dispatch="ui" to run the capture-chain free-mode attach flow, whose
    #: `choose()` dialogs are safely modal there (never inside a table
    #: commit).
    tree_row_selected = Event()

    #: The entry a running protocol is firing right now (dict payload of
    #: PROTOCOL_STEP_FLUORESCENCE), ferried worker->GUI: the controller's
    #: dispatch="ui" observer mirrors its params into the panel and
    #: highlights the firing chain row while the run has the pane's own
    #: publishes suppressed.
    protocol_step_applied = Event()

    #: A capture session's start (True) / end (False), from
    #: PROTOCOL_FLUORESCENCE_SESSION. On end the controller drops the live
    #: mirror (light off, nothing highlighted).
    protocol_session_active = Event()


#: Module-level singleton shared inside the fluorescence plugin.
fluorescence_live_state = FluorescenceLiveState()
