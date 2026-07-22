"""Live (non-persisted) fluorescence pane state shared inside the plugin.

The pane mirrors every persisted control into FluorescencePreferences as it
changes (PERSISTED_CONTROL_TRAITS) and the camera state into the shared
``asi_camera_settings`` — but the master light toggle is deliberately never
persisted (the light always starts OFF).

This singleton also carries the pane <-> protocol-tree live-tracking state
(device-viewer semantics): the GUI-thread event through which a tree row
selection reaches the controller's free-mode capture-chain attach flow.
"""
from traits.api import Bool, Event, HasTraits, Str


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

    #: (topic, message) tuples of the backend's firmware-upload signals
    #: (started / log line / finished), ferried from the worker-thread
    #: listener to the GUI thread: the firmware-upload dialog controller
    #: observes this with dispatch="ui". An Event trait fires on every write
    #: — a plain trait's equality check would swallow consecutive identical
    #: log lines.
    firmware_upload_message = Event()

    #: The connected board's whoami device_id (BOARD_ID signal), ferried from
    #: the worker-thread listener to the GUI thread. The firmware-upload
    #: dialog shows it read-only and flashes exactly that board; empty until
    #: a board identifies.
    board_device_id = Str()

    #: The connected board's serial port (CONNECTED signal), ferried from the
    #: worker-thread listener to the GUI thread. The firmware-upload dialog
    #: keeps its port combo in sync with this auto-detected port; empty while
    #: disconnected.
    board_port = Str()


#: Module-level singleton shared inside the fluorescence plugin.
fluorescence_live_state = FluorescenceLiveState()
