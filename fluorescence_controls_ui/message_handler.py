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

    def _on_telemetry_triggered(self, body):
        """Raw board ack line -> the Log readout."""
        self.model.last_reading = body

    def _on_board_id_triggered(self, body):
        """Identity from the connect-time led_help probe -> the Board readout."""
        try:
            identity = json.loads(body)
        except Exception:
            logger.error(f"Unparseable board id payload: {body!r}")
            return
        name = identity.get("name", "?")
        leds = identity.get("leds", [])
        self.model.board_id_text = f"{name} ({len(leds)} LEDs)" if leds else name
