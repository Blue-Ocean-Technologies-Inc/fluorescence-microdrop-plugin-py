from fluorescence_controller.consts import FLUORESCENCE_HWID, START_DEVICE_MONITORING
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from microdrop_utils.hardware_device_monitoring_helpers import check_connected_ports_hwid
from template_status_and_controls.base_plugin import BaseStatusPlugin
from traits.api import observe

from logger.logger_service import get_logger
logger = get_logger(__name__)

from .consts import PKG, PKG_name, ACTOR_TOPIC_DICT


class FluorescenceControlsUiPlugin(BaseStatusPlugin):
    """Envisage plugin for fluorescence status display and controls.

    Contributes a Tools > Peripherals > Fluorescence > Search Connection menu
    entry (the connection scan, also reachable by clicking the status-bar
    icon).
    """

    id = PKG + ".plugin"
    name = f"{PKG_name} Plugin"

    def _get_dock_pane_class(self):
        from .dock_pane import FluorescenceStatusDockPane
        return FluorescenceStatusDockPane

    def _get_actor_topic_dict(self) -> dict:
        return ACTOR_TOPIC_DICT

    def _get_menu_additions(self) -> list:
        from pyface.action.schema.schema_addition import SchemaAddition
        from .menus import tools_menu_factory
        return [
            SchemaAddition(
                factory=tools_menu_factory,
                path="MenuBar/Tools",
            )
        ]

    @observe("application:extra_plugins_loaded")
    def _on_app_initialized(self, event):

        # check if peripheral board connected
        if check_connected_ports_hwid(FLUORESCENCE_HWID):
            logger.critical(
                "Fluorescence Board Maybe Connected: Requesting Fluorescence Board Search"
            )
            publish_message(message="", topic=START_DEVICE_MONITORING)
        else:
            logger.info(
                "Fluorescence Board not connected. To start search, goto tools menu: "
                "Tools -> Peripherals -> Fluorescence -> Search Connection "
                "or use the Fluorescence UI status bar button."
            )
