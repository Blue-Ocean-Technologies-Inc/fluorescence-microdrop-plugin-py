import webbrowser

from pyface.action.api import Action
from pyface.action.schema.schema import SGroup, SMenu
from traits.api import Str

from microdrop_utils.dramatiq_traits_helpers import DramatiqMessagePublishAction

from .consts import START_DEVICE_MONITORING, ASI_DRIVER_URL


class InstallAsiDriverAction(Action):
    name = Str("Install Fluorescence Camera &Driver (Windows)...")
    tooltip = "Open the ZWO ASI camera driver download page"

    def perform(self, event):
        webbrowser.open(ASI_DRIVER_URL)


def help_menu_factory():
    """Help-menu group: the Windows camera-driver download link (the same
    URL the launch notice points at)."""
    return SGroup(InstallAsiDriverAction(), id="fluorescence_help_actions")


def fluorescence_tools_menu_factory():
    """Tools > Peripherals > Fluorescence > Search Connection."""
    search = DramatiqMessagePublishAction(
        name="&Search Connection", topic=START_DEVICE_MONITORING)
    return SMenu(items=[search], id="fluorescence_tools", name="&Fluorescence")


def tools_menu_factory():
    # The fluorescence plugin contributes its own Tools -> Peripherals entry.
    return SMenu(items=[fluorescence_tools_menu_factory()],
                 id="peripherals_tools", name="&Peripherals")
