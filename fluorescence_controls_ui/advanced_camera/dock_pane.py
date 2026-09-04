# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Dock pane for advanced ASI camera controls (binning, resolution, image
type, gamma, white balance, offset, flip, USB bandwidth, ...).

Settings edited here apply to the running camera live (the capture thread
picks them up between frames) and persist across sessions. Every write is
clamped to the connected camera's own reported control range, so cameras
with narrower capability sets stay safe.
"""

# Enthought library imports.
from pyface.tasks.api import TraitsDockPane
from traits.api import Instance
from traitsui.api import Handler

# Local imports.
from ..consts import PKG
from .controller import AdvancedCameraController
from .model import AdvancedCameraModel
from .view import advanced_camera_view

# Logger import.
from logger.logger_service import get_logger

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
            kind="subpanel", parent=parent, handler=self.controller
        )
        return self.ui.control

    def destroy(self):
        """Detach the controller from the settings singleton so a
        hot-unloaded pane doesn't keep receiving capability updates."""
        if self.controller is not None:
            self.controller.remove_camera_caps_observers()
        super().destroy()
