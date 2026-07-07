from traits.api import Str

from template_status_and_controls.base_model import BaseStatusModel

from .consts import disconnected_color, connected_color

from logger.logger_service import get_logger
logger = get_logger(__name__)


class FluorescenceStatusModel(BaseStatusModel):
    """Model for fluorescence status display and controls.

    Extends BaseStatusModel with placeholder readout traits; the real
    measurement/control state gets ported from the standalone app.
    """

    DISCONNECTED_COLOR = disconnected_color
    CONNECTED_COLOR = connected_color

    # Latest raw telemetry line from the board (placeholder readout until the
    # real measurement model is ported).
    last_reading = Str("-")
