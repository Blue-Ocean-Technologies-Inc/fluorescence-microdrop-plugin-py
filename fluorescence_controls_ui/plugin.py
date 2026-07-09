import platform

from device_viewer.consts import CAMERA_SOURCES
from envisage.ids import PREFERENCES_PANES
from traits.api import List

from fluorescence_controller.consts import FLUORESCENCE_HWID, START_DEVICE_MONITORING
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from microdrop_utils.hardware_device_monitoring_helpers import check_connected_ports_hwid
from template_status_and_controls.base_plugin import BaseStatusPlugin
from traits.api import observe

from logger.logger_service import get_logger
logger = get_logger(__name__)

from .consts import PKG, PKG_name, ACTOR_TOPIC_DICT, ASI_DRIVER_URL


class FluorescenceControlsUiPlugin(BaseStatusPlugin):
    """Envisage plugin for fluorescence status display and controls.

    Contributes a Tools > Peripherals > Fluorescence > Search Connection menu
    entry (the connection scan, also reachable by clicking the status-bar
    icon).
    """

    id = PKG + ".plugin"
    name = f"{PKG_name} Plugin"

    # Fluorescence group on the shared Peripheral Settings preferences tab
    # (re-enable the driver notice there after opting out of the popup).
    preferences_panes = List(contributes_to=PREFERENCES_PANES)

    def _preferences_panes_default(self):
        from .preferences import FluorescencePreferencesPane
        return [FluorescencePreferencesPane]

    # ASI cameras join the device viewer's own camera dropdown and render
    # through its video layer (perspective-aligned under the electrodes).
    camera_sources = List(contributes_to=CAMERA_SOURCES)

    def _camera_sources_default(self):
        from .cameras.provider import AsiCameraSourceProvider
        return [AsiCameraSourceProvider]

    def _get_dock_pane_class(self):
        from .dock_pane import FluorescenceStatusDockPane
        return FluorescenceStatusDockPane

    def _get_actor_topic_dict(self) -> dict:
        return ACTOR_TOPIC_DICT

    def _get_menu_additions(self) -> list:
        from pyface.action.schema.schema_addition import SchemaAddition
        from .menus import tools_menu_factory, help_menu_factory
        return [
            SchemaAddition(
                factory=tools_menu_factory,
                path="MenuBar/Tools",
            ),
            # Help > Install Fluorescence Camera Driver (Windows)... — the
            # same ZWO download the launch notice points at, reachable any
            # time (the notice can be opted out of).
            SchemaAddition(
                factory=help_menu_factory,
                path="MenuBar/Help",
            ),
        ]

    def start(self):
        super().start()
        # One-time (per user) pointer at the Windows ASI camera driver, shown
        # on plugin start so it covers both a fresh install (relaunch) and a
        # runtime hot-load via Tools > Peripherals. invoke_later: on a cold
        # boot plugins start before the GUI loop runs.
        if platform.system() == "Windows":
            from pyface.gui import GUI
            GUI.invoke_later(self._show_asi_driver_notice)

    def _show_asi_driver_notice(self):
        from microdrop_application.dialogs.pyface_wrapper import information
        from .preferences import FluorescencePreferences

        try:
            preferences = FluorescencePreferences(
                preferences=self.application.preferences_helper.preferences)
        except Exception:
            logger.warning("Preferences unavailable; showing ASI driver "
                           "notice without a don't-show-again option")
            preferences = None
        if preferences is not None and not preferences.fluorescence_show_asi_driver_notice:
            return

        result = information(
            parent=None,
            title="ASI camera driver",
            message=(
                "Using a ZWO ASI camera with the fluorescence plugin on "
                "Windows requires the ASI Camera Driver.<br><br>"
                f'Download it from <a href="{ASI_DRIVER_URL}">the ZWO '
                "website</a>, install it, then reconnect the camera."
            ),
            cancel=False,
            checkbox_text="Don't show this again",
        )
        # With checkbox_text, information() returns (result, checked).
        if preferences is not None and isinstance(result, tuple) and result[1]:
            preferences.fluorescence_show_asi_driver_notice = False

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
