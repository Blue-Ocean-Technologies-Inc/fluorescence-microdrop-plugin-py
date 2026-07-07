from template_status_and_controls.base_controller import BaseStatusController

from logger.logger_service import get_logger
logger = get_logger(__name__)


class FluorescenceControlsController(BaseStatusController):
    """Fluorescence controls controller.

    Translates model changes into published command topics. Control observers
    get added here as the standalone app's workflow is ported.
    """
