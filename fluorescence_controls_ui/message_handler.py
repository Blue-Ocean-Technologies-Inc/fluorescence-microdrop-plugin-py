import json

from traits.api import Instance

from template_status_and_controls.base_message_handler import BaseMessageHandler
from logger.logger_service import get_logger

from .model import FluorescenceStatusModel

logger = get_logger(__name__)


class FluorescenceMessageHandler(BaseMessageHandler):
    """Dramatiq message handler for the fluorescence UI.

    Inherits the common connected / disconnected handlers from
    BaseMessageHandler; adds fluorescence-specific signal handlers.
    """

    model = Instance(FluorescenceStatusModel)

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
