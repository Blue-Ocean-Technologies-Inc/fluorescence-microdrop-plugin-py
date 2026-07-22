from traits.api import Instance, observe
from pyface.qt.QtCore import Qt

from template_status_and_controls.base_dock_pane import (
    BaseStatusDockPane, build_status_icon_tooltip, status_bar_icon_font)
from microdrop_application.dialogs.pyface_wrapper import information
from microdrop_style.icons.icons import ICON_EMOJI_OBJECTS
from microdrop_utils.pyside_helpers import ClickableLabel
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from .consts import PKG, PKG_name, listener_name, START_DEVICE_MONITORING
from .model import FluorescenceStatusModel
from .controller import FluorescenceControlsController
from .preferences import FluorescencePreferences
from .view import UnifiedView
from .message_handler import FluorescenceMessageHandler

logger = get_logger(__name__)


class FluorescenceStatusDockPane(BaseStatusDockPane):
    """Dock pane for fluorescence LED status display and controls.

    The status bar shows the lightbulb icon (clickable, triggers a
    connection scan — same as Tools ▸ Peripherals ▸ Fluorescence ▸
    Search Connection)."""

    id = PKG + ".status_controls.dock_pane"
    name = f"{PKG_name} Dock Pane"

    view = UnifiedView
    status_bar_icon_glyph = ICON_EMOJI_OBJECTS

    def _status_bar_plugin_id_default(self):
        # The pane id carries an extra ".status_controls" segment (to
        # distinguish it from the image viewer pane), so the base class's
        # "<pkg>.plugin" convention would derive a nonexistent plugin id
        # and the status-bar icon would be silently skipped.
        return PKG + ".plugin"

    # ------------------------------------------------------------------ #
    # BaseStatusDockPane factory hooks                                     #
    # ------------------------------------------------------------------ #
    def _create_model(self):
        return FluorescenceStatusModel()

    def _create_controller(self):
        controller = FluorescenceControlsController(self.model)
        # Mirror the restored exposure/gain and the device-viewer stream
        # checkbox into the shared ASI camera settings once — the
        # controller's observers only fire on later edits, and the restored
        # values may differ from the camera-settings defaults.
        controller._push_camera_settings(None)
        controller._push_device_viewer_stream(None)
        controller._push_auto_flags(None)
        return controller

    def _create_message_handler(self) -> FluorescenceMessageHandler:
        return FluorescenceMessageHandler(model=self.model, name=listener_name)

    def _create_status_bar_icon(self):
        # Clickable: triggers a board connection scan, so the user can
        # reconnect straight from the icon. The click is ignored while a
        # scan is already active (see model.searching).
        icon = ClickableLabel(self.status_bar_icon_glyph)
        icon.setFont(status_bar_icon_font())
        icon.setStyleSheet(f"color: {self.model.DISCONNECTED_COLOR}")
        icon.clicked.connect(self._search_fluorescence_connection)
        return icon

    def _build_status_bar_tooltip(self) -> str:
        # The base tooltip describes DropBot chip states, which the LED
        # board doesn't have — just disconnected/connected.
        return build_status_icon_tooltip(
            "Fluorescence Status:",
            [
                (self.model.DISCONNECTED_COLOR, "Disconnected"),
                (self.model.CONNECTED_COLOR, "Connected"),
            ],
            hint="Searching for device…" if self.model.searching
                 else "Click to search for a connection.",
        )

    # ------------------------------------------------------------------ #
    # Status-icon "search connection" click (gated on an active scan)      #
    # ------------------------------------------------------------------ #
    def _search_fluorescence_connection(self):
        """Ask the backend to start a connection scan, unless one is already
        running. The backend acknowledges by publishing its searching state,
        which disables the icon (see _sync_search_affordance)."""
        if self.model.searching:
            logger.debug("Fluorescence search already active; ignoring status-icon click")
            return
        publish_message(topic=START_DEVICE_MONITORING, message="")

    # ------------------------------------------------------------------ #
    # "Applies when the stream starts" warning (lighting edit, stream off) #
    # ------------------------------------------------------------------ #
    @observe("model:stream_off_edit_warning", dispatch="ui")
    def _warn_edit_stream_off(self, event):
        """One-time staged-edit note (heater pane parity); the
        don't-show-again checkbox persists to preferences."""
        preferences = self.model.preferences
        if not preferences.fluorescence_show_stream_off_warning:
            return
        result = information(
            parent=None,
            title="Stream is off",
            message="The lighting change will apply when you start the stream.",
            cancel=False,
            checkbox_text="Don't show this again",
        )
        # With checkbox_text, information() returns (result, checked).
        if isinstance(result, tuple) and result[1]:
            preferences.fluorescence_show_stream_off_warning = False

    @observe("model:searching", dispatch="ui")
    def _sync_search_affordance(self, event=None):
        """Pointing-hand cursor only when a click would do something — i.e.
        when no scan is currently active — and flip the tooltip to match."""
        if self.status_bar_icon is not None:
            self.status_bar_icon.setCursor(
                Qt.CursorShape.ArrowCursor if self.model.searching
                else Qt.CursorShape.PointingHandCursor)
        self._refresh_status_bar_tooltip()
