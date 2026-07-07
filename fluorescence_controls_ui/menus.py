from pyface.action.schema.schema import SMenu

from microdrop_utils.dramatiq_traits_helpers import DramatiqMessagePublishAction

from .consts import START_DEVICE_MONITORING


def fluorescence_tools_menu_factory():
    """Tools > Peripherals > Fluorescence > Search Connection."""
    search = DramatiqMessagePublishAction(
        name="&Search Connection", topic=START_DEVICE_MONITORING)
    return SMenu(items=[search], id="fluorescence_tools", name="&Fluorescence")


def tools_menu_factory():
    # The fluorescence plugin contributes its own Tools -> Peripherals entry.
    return SMenu(items=[fluorescence_tools_menu_factory()],
                 id="peripherals_tools", name="&Peripherals")
