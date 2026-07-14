import json

from traits.api import Event, Instance, Str, observe

from template_status_and_controls.base_message_handler import BaseMessageHandler
from logger.logger_service import get_logger

from fluorescence_protocol_controls.consts import (
    FLUORESCENCE_ON_COLUMN_ID, FLUORESCENCE_SETTINGS_COLUMN_ID,
)
from pluggable_protocol_tree.models.cell_sync import (
    ProtocolTreeRowSelectedMessage,
)

from .live_state import fluorescence_live_state
from .model import FluorescenceStatusModel

logger = get_logger(__name__)


class FluorescenceMessageHandler(BaseMessageHandler):
    """Dramatiq message handler for the fluorescence UI.

    Inherits the common connected / disconnected handlers from
    BaseMessageHandler; adds fluorescence-specific signal handlers.
    """

    model = Instance(FluorescenceStatusModel)

    #: Raw PROTOCOL_TREE_ROW_SELECTED payload from the worker-thread
    #: listener; the dispatch="ui" observer consumes it on the GUI thread
    #: (the protocol tree's device_viewer_sync pattern).
    _row_selected_event = Event(Str)

    def _on_row_selected_triggered(self, body):
        self._row_selected_event = body

    def _on_fluorescence_applied_triggered(self, body):
        """Backend ack for a protocol step's LED apply — consumed by the
        protocol executor's ack mailbox; the signals/# subscription lands
        it here too, so it needs a handler (else a missing-handler error
        is logged on every step)."""
        logger.debug(f"Fluorescence applied ack: {body}")

    @observe("_row_selected_event", dispatch="ui")
    def _on_row_selected(self, event):
        """Track the tree's selected step: a step whose fluorescence cell
        holds a snapshot becomes the pane's live-tracked step and its
        snapshot loads into the pane (controller observer on the
        live-state event); anything else stops tracking."""
        try:
            row_selected_msg = ProtocolTreeRowSelectedMessage.deserialize(
                event.new)
        except Exception as e:
            logger.warning(f"Unparseable row-selected payload: {e}")
            return
        cells = row_selected_msg.cells or {}
        snapshot = cells.get(FLUORESCENCE_SETTINGS_COLUMN_ID)
        if (row_selected_msg.step_id
                and cells.get(FLUORESCENCE_ON_COLUMN_ID)
                and isinstance(snapshot, dict)):
            fluorescence_live_state.tracked_step_uuid = row_selected_msg.step_id
            fluorescence_live_state.step_snapshot_selected = snapshot
        else:
            fluorescence_live_state.tracked_step_uuid = ""

    def _on_searching_triggered(self, body):
        """Backend scan state (json bool) -> the model, which drives the
        status-bar icon's click affordance and tooltip."""
        try:
            self.model.searching = json.loads(body)
        except Exception:
            logger.error(f"Unparseable searching payload: {body!r}")

    def _on_telemetry_triggered(self, body):
        """Raw board ack line -> the Log readout."""
        self.model.last_reading = body

    def _on_board_id_triggered(self, body):
        """Identity from the connect-time whoami probe -> the Board readout
        (device_id first, like the heater pane)."""
        try:
            identity = json.loads(body)
        except Exception:
            logger.error(f"Unparseable board id payload: {body!r}")
            return
        self.model.board_id_text = str(
            identity.get("device_id") or identity.get("uid") or "unknown")
