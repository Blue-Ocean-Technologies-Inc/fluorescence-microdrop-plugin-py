import json

from traits.api import Instance

from template_status_and_controls.base_message_handler import BaseMessageHandler
from logger.logger_service import get_logger

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

    def _on_row_selected_triggered(self, body):
        """Worker-thread listener for PROTOCOL_TREE_ROW_SELECTED: parse
        the broadcast and ferry it straight to the GUI thread via
        live_state — this handler must never touch the model or run a
        dialog itself (the controller's dispatch="ui" observer does,
        safely, on the GUI thread)."""
        try:
            row_selected_msg = ProtocolTreeRowSelectedMessage.deserialize(
                body)
        except Exception as e:
            logger.warning(f"Unparseable row-selected payload: {e}")
            return
        fluorescence_live_state.tree_row_selected = row_selected_msg

    def _on_fluorescence_applied_triggered(self, body):
        """Backend ack for a protocol step's LED apply — consumed by the
        protocol executor's ack mailbox; the signals/# subscription lands
        it here too, so it needs a handler (else a missing-handler error
        is logged on every step)."""
        logger.debug(f"Fluorescence applied ack: {body}")

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
