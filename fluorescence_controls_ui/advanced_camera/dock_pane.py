"""Dock pane for advanced ASI camera controls (binning, resolution, image
type, gamma, white balance, offset, flip, USB bandwidth, ...).

Settings edited here apply to the running camera live (the capture thread
picks them up between frames) and persist across sessions. Every write is
clamped to the connected camera's own reported control range, so cameras
with narrower capability sets stay safe.
"""
from pyface.tasks.api import TraitsDockPane
from traits.api import Instance
from traitsui.api import Handler

from logger.logger_service import get_logger

from ..consts import PKG
from .controller import AdvancedCameraController
from .model import AdvancedCameraModel
from .view import advanced_camera_view

logger = get_logger(__name__)


class AdvancedCameraDockPane(TraitsDockPane):
    """Advanced capture settings for the fluorescence ASI camera."""

    id = PKG + ".advanced_camera.dock_pane"
    name = "Advanced Fluorescence Camera Controls"

    view = advanced_camera_view

    controller = Instance(Handler)

    def traits_init(self):
        self.model = AdvancedCameraModel()
        self.controller = AdvancedCameraController(self.model)
        # Mirror the restored settings into the shared ASI camera settings
        # once — the controller's observer only fires on later edits.
        self.controller.push_all_advanced_camera_settings()

    def create_contents(self, parent):
        self.ui = self.edit_traits(
            kind="subpanel", parent=parent, handler=self.controller)
        return self.ui.control

    def destroy(self):
        """Detach the controller from the settings singleton so a
        hot-unloaded pane doesn't keep receiving capability updates."""
        if self.controller is not None:
            self.controller.remove_camera_caps_observers()
        super().destroy()
