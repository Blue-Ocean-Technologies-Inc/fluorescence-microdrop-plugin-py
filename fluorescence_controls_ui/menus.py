# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

# Standard library imports.
import webbrowser

# Enthought library imports.
from pyface.action.api import Action
from pyface.action.schema.schema import SGroup, SMenu
from traits.api import Instance, Str

# Microdrop utils imports.
from microdrop_utils.dramatiq_traits_helpers import DramatiqMessagePublishAction
from microdrop_utils.firmware_upload_dialog.controller import (
    FirmwareUploadDialogController,
)

# Local imports.
from .ai_install import install_ai_support
from .consts import ASI_DRIVER_URL, START_DEVICE_MONITORING
from .firmware_upload.controller import make_firmware_upload_controller
from .image_viewer.analysis.roi_model import roi_analysis_model
from .image_viewer.analysis.sam_detect import sam_available


class InstallAsiDriverAction(Action):
    name = Str("Install Fluorescence Camera &Driver (Windows)...")
    tooltip = "Open the ZWO ASI camera driver download page"

    def perform(self, event):
        webbrowser.open(ASI_DRIVER_URL)


class InstallAiSupportAction(Action):
    name = Str("Install &AI ROI Support...")
    tooltip = "Install the SAM segmentation stack (osam) with pixi"

    def perform(self, event):
        if install_ai_support():
            # sam_available() retries the osam import in-process, so a
            # successful install becomes usable without an app restart;
            # a failed/partial install (returns False) still leaves the
            # toolbar disabled instead of lying about availability.
            roi_analysis_model.ai_available = sam_available()


class UploadFirmwareAction(Action):
    name = Str("Upload &Firmware...")
    tooltip = "Flash the fluorescence board's MicroPython firmware"

    #: One controller for the action's lifetime: reopening raises the live
    #: dialog instead of duplicating it, and the log/options survive reopens.
    controller = Instance(FirmwareUploadDialogController)

    def perform(self, event):
        if self.controller is None:
            self.controller = make_firmware_upload_controller()
        self.controller.open()


def help_menu_factory():
    """Help-menu group: the Windows camera-driver download link (the same
    URL the launch notice points at) and the optional AI ROI support
    installer."""
    return SGroup(
        InstallAsiDriverAction(),
        InstallAiSupportAction(),
        id="fluorescence_help_actions",
    )


def fluorescence_tools_menu_factory():
    """Tools > Peripherals > Fluorescence > Search Connection / Upload
    Firmware."""
    search = DramatiqMessagePublishAction(
        name="&Search Connection", topic=START_DEVICE_MONITORING
    )
    return SMenu(
        items=[search, UploadFirmwareAction()],
        id="fluorescence_tools",
        name="&Fluorescence",
    )


def tools_menu_factory():
    # The fluorescence plugin contributes its own Tools -> Peripherals entry.
    return SMenu(
        items=[fluorescence_tools_menu_factory()],
        id="peripherals_tools",
        name="&Peripherals",
    )
