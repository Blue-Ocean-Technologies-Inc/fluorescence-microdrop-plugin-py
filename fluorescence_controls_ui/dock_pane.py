from template_status_and_controls.base_dock_pane import BaseStatusDockPane
from microdrop_style.icons.icons import ICON_EMOJI_OBJECTS
from logger.logger_service import get_logger

from .consts import PKG, PKG_name, listener_name
from .model import FluorescenceStatusModel
from .controller import FluorescenceControlsController
from .view import UnifiedView
from .message_handler import FluorescenceMessageHandler

logger = get_logger(__name__)


class FluorescenceStatusDockPane(BaseStatusDockPane):
    """Dock pane for fluorescence status display and controls.

    The status bar shows the lightbulb icon (clickable, triggers a
    connection scan)."""

    id = PKG + ".dock_pane"
    name = f"{PKG_name} Dock Pane"

    view = UnifiedView
    status_bar_icon_glyph = ICON_EMOJI_OBJECTS

    # ------------------------------------------------------------------ #
    # BaseStatusDockPane factory hooks                                     #
    # ------------------------------------------------------------------ #
    def _create_model(self):
        return FluorescenceStatusModel()

    def _create_controller(self):
        return FluorescenceControlsController(self.model)

    def _create_message_handler(self) -> FluorescenceMessageHandler:
        return FluorescenceMessageHandler(model=self.model, name=listener_name)
