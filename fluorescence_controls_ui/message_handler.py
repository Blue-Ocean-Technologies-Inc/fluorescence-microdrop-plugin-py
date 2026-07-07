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
        """Raw board line -> placeholder readout (real parsing TBD)."""
        self.model.last_reading = body
