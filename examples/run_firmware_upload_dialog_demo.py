"""Runnable demo: styled firmware-upload dialog, decoupled front/back.

Run: pixi run python examples/run_firmware_upload_dialog_demo.py
(from microdrop-py, with the plugin packages installed editable).

A TraitsUI config panel (Directory/File editors, glyph toggle for auto/manual
port, Material-Symbols icon buttons, live log console) embedded inside the
application's BaseMessageDialog frame, so it looks exactly like the
pyface_wrapper dialogs (header icon + title, styled Upload/Close button row).

The dialog is a pure frontend: Upload publishes a validated
UploadFirmwareData request; the GUI-free backend service
(fluorescence_controller.services.fluorescence_firmware_upload_service) runs
the in-repo uploader (fluorescence_controller.firmware_uploader, mpremote
based) and streams its progress back over FIRMWARE_UPLOAD_STARTED /
FIRMWARE_UPLOAD_LOG / FIRMWARE_UPLOAD_FINISHED, which a dramatiq listener
feeds into the log console. Auto-port is resolved backend-side (a connected
proxy's stored port, else whoami/VID probing). Only the firmware SOURCE tree
stays external — DEFAULT_FIRMWARE_DIR points at the standalone repo's
firmware folder.

MVC split (per project conventions):
  - FirmwareUploadModel      Qt-free HasTraits (options + log text + payload)
  - LogViewEditor            custom TraitsUI editor (append-only console)
  - FirmwareUploadDialogController  view layer: builds the dialog and
    publishes the upload/cancel requests. The dramatiq listener thread only
    ferries each backend publish into FirmwareUploadLiveState; the
    controller's dispatch="ui" observer applies it to the model on the GUI
    thread (fluorescence pane pattern — the model is only ever mutated
    there).

main() is an in-process demo harness: Redis + workers + message router + the
composed fluorescence backend + this dialog, mirroring the
dropbot_protocol_controls demo pattern. To exercise the proxy-port path,
publish START_DEVICE_MONITORING (e.g. from the pane) before uploading.
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QPlainTextEdit, QSizePolicy,
)

from traits.api import (
    Any, Bool, Button, Directory, Event, File, HasTraits, Instance, Int,
    List, Str, observe,
)
from traitsui.api import (
    BasicEditorFactory, HGroup, HSplit, Item, Label, UItem, VGroup, View,
    spring,
)
from traitsui.qt.editor import Editor as QtEditor

import serial.tools.list_ports

from microdrop_application.dialogs.base_message_dialog import BaseMessageDialog
from microdrop_application.dialogs.pyface_wrapper import YES, confirm, error
from microdrop_style.colors import PRIMARY_COLOR, WHITE
from microdrop_style.icons.icons import (
    ICON_AUTOMATION, ICON_DELETE, ICON_REFRESH,
)
from microdrop_utils.dramatiq_controller_base import (
    generate_class_method_dramatiq_listener_actor,
)
from microdrop_utils.dramatiq_pub_sub_helpers import (
    MessageRouterActor, publish_message,
)
from microdrop_utils.traitsui_qt_helpers import (
    HoverScrollEnumEditor, IconButtonEditor, IconToggleEditor,
    stretch_group_layouts_horizontally,
)

from fluorescence_controller.consts import (
    ACTOR_TOPIC_DICT, CANCEL_FIRMWARE_UPLOAD, FIRMWARE_UPLOAD_FINISHED,
    FIRMWARE_UPLOAD_LOG, FIRMWARE_UPLOAD_STARTED,
    FLUORESCENCE_BOARD_DEVICE_ID, PICO_USB_VENDOR_ID,
)
from fluorescence_controller.datamodels import upload_firmware_publisher
from fluorescence_controller.fluorescence_controller_base import (
    FluorescenceControllerBase,
)
from fluorescence_controller.services.fluorescence_firmware_upload_service import (
    FluorescenceFirmwareUploadService,
)
from fluorescence_controller.services.fluorescence_monitor_mixin_service import (
    FluorescenceMonitorMixinService,
)

from logger.logger_service import get_logger
logger = get_logger(__name__)

# Dev-machine default for the firmware SOURCE tree (the standalone repo's
# firmware folder — deliberately not shipped with this plugin); the dialog's
# Firmware folder field is editable, so other machines just browse to theirs.
DEFAULT_FIRMWARE_DIR = Path(r"C:\Users\Info\PycharmProjects\fluorescence-camera-ui\firmware")

# Separates "COM7" from its human-readable description in the port dropdown.
PORT_ENTRY_SEPARATOR = " — "

LOG_CONSOLE_FONT_FAMILY = "Consolas"

# Material Symbols ligature (would live in microdrop_style/icons/icons.py if
# this graduates from a demo into the app).
ICON_USB = "usb"

# Dramatiq listener receiving the backend's firmware-upload signals.
DEMO_LISTENER_NAME = "firmware_upload_demo_listener"


# --------------------------------------------------------------------------
# Model (Qt-free)
# --------------------------------------------------------------------------

class FirmwareUploadModel(HasTraits):
    """Options for one firmware-upload request, plus the live log."""

    firmware_dir = Directory()
    single_file = File()

    #: True: the backend resolves the port (a connected proxy's stored port,
    #: else the script's whoami / VID probing). False: send the selection below.
    auto_port = Bool(True)
    available_ports = List(Str)
    selected_port_entry = Str()
    refresh_ports = Button()

    device_id = Str(FLUORESCENCE_BOARD_DEVICE_ID)

    update_config = Bool(False)           # --update-config
    skip_filesystem_format = Bool(False)  # --no-format
    reset_after_upload = Bool(True)       # omit --no-reset
    dry_run = Bool(False)                 # --dry-run

    #: Kill the upload if it runs longer than this many seconds (0 = never);
    #: enforced by the backend service, sent along in the request.
    upload_timeout_s = Int(0)

    uploading = Bool(False)
    upload_log = Str()
    clear_log = Button()

    # Section collapse states (fluo controls pane pattern: an arrow-glyph
    # header toggles each `show_*`, the bordered group is visible_when it).
    show_source = Bool(True)
    show_port = Bool(True)
    show_options = Bool(True)

    def _firmware_dir_default(self):
        return str(DEFAULT_FIRMWARE_DIR)

    def _available_ports_default(self):
        return self._scan_port_entries()

    def _selected_port_entry_default(self):
        return self.available_ports[0] if self.available_ports else ""

    @staticmethod
    def _scan_port_entries():
        """Dropdown entries for every serial port, Pico-vendor ports first."""
        ports = sorted(
            serial.tools.list_ports.comports(),
            key=lambda p: (p.vid != PICO_USB_VENDOR_ID, str(p.device)),
        )
        return [f"{p.device}{PORT_ENTRY_SEPARATOR}{p.description}" for p in ports]

    @observe("refresh_ports")
    def _on_refresh_ports(self, event):
        entries = self._scan_port_entries()
        self.available_ports = entries
        if self.selected_port_entry not in entries:
            self.selected_port_entry = entries[0] if entries else ""
        listing = "\n".join(f"    {entry}" for entry in entries) or "    (none)"
        self.upload_log += f"Found {len(entries)} serial port(s):\n{listing}\n"

    @observe("clear_log")
    def _on_clear_log(self, event):
        self.upload_log = ""

    def selected_port_device(self):
        return self.selected_port_entry.split(PORT_ENTRY_SEPARATOR)[0]

    def validation_problems(self):
        """Human-readable reasons the upload can't start (empty when OK)."""
        problems = []
        if self.single_file:
            if not Path(self.single_file).is_file():
                problems.append(f"Single file not found: {self.single_file}")
        elif not Path(self.firmware_dir).is_dir():
            problems.append(f"Firmware folder not found: {self.firmware_dir}")
        if not self.auto_port and not self.selected_port_entry:
            problems.append("Manual port mode is on but no port is selected.")
        return problems

    def upload_request_kwargs(self):
        """Keyword payload for upload_firmware_publisher.publish reflecting
        the current options (empty port = backend auto-resolution)."""
        return dict(
            firmware_dir=self.firmware_dir,
            single_file=self.single_file,
            port="" if self.auto_port else self.selected_port_device(),
            device_id=self.device_id,
            update_config=self.update_config,
            skip_filesystem_format=self.skip_filesystem_format,
            reset_after_upload=self.reset_after_upload,
            dry_run=self.dry_run,
            upload_timeout_s=self.upload_timeout_s,
        )


# --------------------------------------------------------------------------
# Log console editor (append-only, auto-scrolling)
# --------------------------------------------------------------------------

class _LogViewEditor(QtEditor):
    """Read-only console over a Str trait: appends only the new tail on each
    change (the upload log grows by appending), auto-scrolls to the bottom,
    and resets wholesale when the trait shrinks (e.g. Clear log)."""

    def init(self, parent):
        self.control = QPlainTextEdit()
        self.control.setReadOnly(True)
        self.control.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont(LOG_CONSOLE_FONT_FAMILY)
        font.setPointSize(self.factory.point_size)
        self.control.setFont(font)
        self.control.setMinimumHeight(self.factory.min_height)
        self.control.setMinimumWidth(self.factory.min_width)
        self.control.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                border-radius: 6px;
                padding: 6px;
                selection-background-color: {PRIMARY_COLOR};
            }}
            /* This widget-level QSS forces non-native scrollbars, so restyle
               them to match the console (dark twin of the panel's light
               scrollbar rules). */
            QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                border-radius: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #4A4A4A;
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #5C5C5C;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 12px;
                border-radius: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: #4A4A4A;
                border-radius: 6px;
                min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: #5C5C5C;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                width: 0px;
                height: 0px;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{
                background: none;
            }}
        """)
        self._shown_text = ""
        self.update_editor()

    def update_editor(self):
        text = self.value or ""
        if text == self._shown_text:
            return
        if text.startswith(self._shown_text):
            cursor = self.control.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text[len(self._shown_text):])
        else:
            self.control.setPlainText(text)
        self._shown_text = text
        scrollbar = self.control.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class LogViewEditor(BasicEditorFactory):
    """Factory for the dark console log view over a Str trait."""

    klass = _LogViewEditor

    min_height = Int(220)
    min_width = Int(300)
    point_size = Int(9)


# --------------------------------------------------------------------------
# View
# --------------------------------------------------------------------------

def _collapse_header(trait, label):
    """A section header row: a Material arrow glyph that expands / collapses
    the section by toggling ``trait``, followed by the section's label (same
    structure as the fluorescence controls pane)."""
    return HGroup(
        UItem(trait, editor=IconToggleEditor()),
        Label(label),
    )


# Left: collapsible config sections. Right: the log console, permanently
# visible on the other side of a draggable splitter.
firmware_upload_view = View(
    HSplit(
        VGroup(
            _collapse_header("show_source", "Firmware source"),
            VGroup(
                Item("firmware_dir", label="Firmware folder",
                     tooltip="Directory tree pushed to the board"),
                Item("single_file", label="Single file",
                     tooltip="Optional: upload only this file instead of "
                             "the whole firmware folder"),
                visible_when="show_source",
                show_border=True,
                enabled_when="not uploading",
            ),
            _collapse_header("show_port", "Device & port"),
            VGroup(
                HGroup(
                    Item("auto_port", label="Auto-detect port",
                         editor=IconToggleEditor(
                             on_glyph=ICON_AUTOMATION, off_glyph=ICON_USB,
                             tooltip="On: the backend finds the board itself "
                                     "(a connected proxy's port, else "
                                     "whoami / Pico VID probing). "
                                     "Off: use the port selected here.")),
                    Item("selected_port_entry", label="Port",
                         editor=HoverScrollEnumEditor(
                             values_name="available_ports"),
                         enabled_when="not auto_port", springy=True),
                    UItem("refresh_ports", editor=IconButtonEditor(
                        glyph=ICON_REFRESH, tooltip="Re-scan serial ports")),
                ),
                Item("device_id", label="Device ID",
                     tooltip="Only flash the board whose whoami reply "
                             "matches this id. Leave empty to flash the "
                             "first board that identifies."),
                visible_when="show_port",
                show_border=True,
                enabled_when="not uploading",
            ),
            _collapse_header("show_options", "Options"),
            VGroup(
                Item("update_config", label="Upload config.json",
                     tooltip="Overwrite the board's config.json with the repo "
                             "copy. Off: the board keeps its own, backed up "
                             "and restored around the reflash."),
                Item("skip_filesystem_format", label="Skip format",
                     tooltip="Don't wipe the board's filesystem first"),
                Item("reset_after_upload", label="Reset after upload",
                     tooltip="Reset the board when the upload finishes"),
                Item("dry_run", label="Dry run",
                     tooltip="Only log what would happen"),
                Item("upload_timeout_s", label="Timeout (s)",
                     tooltip="Kill the upload if it runs longer than this many "
                             "seconds (0 = no timeout)"),
                visible_when="show_options",
                show_border=True,
                enabled_when="not uploading",
            ),
            # Only this column scrolls (vertically) when the dialog is short —
            # the log console on the right has its own scrollbars.
            scrollable=True,
        ),
        VGroup(
            HGroup(
                Label("Upload log"),
                spring,
                UItem("clear_log", editor=IconButtonEditor(
                    glyph=ICON_DELETE, tooltip="Clear the log")),
            ),
            UItem("upload_log", editor=LogViewEditor()),
            show_border=True,
            springy=True,
        ),
    ),
    # Resizable so sections take their natural height instead of being
    # crushed to their minimums; scrolling is per-side — the left column has
    # scrollable=True, the log console scrolls by itself.
    resizable=True,
)


# --------------------------------------------------------------------------
# Dialog controller (view layer — Qt allowed)
# --------------------------------------------------------------------------

def build_panel_stylesheet(dialog):
    """Scoped stylesheet for the embedded TraitsUI panel.

    BaseMessageDialog styles only its own widgets: its bare ``QPushButton``
    rule cascades primary-color/white onto the panel's Browse buttons, while
    the panel's labels/checkboxes/line edits get no rule at all and fall back
    to the system palette (white text in Windows dark mode on the dialog's
    always-light background). Pin every widget class here, in the dialog's own
    theme colors, so the panel matches the dialog in both system modes.
    QToolButton glyph buttons keep their Material Symbols font (no font-family
    rule on them); the log console carries its own stylesheet and wins anyway.
    """
    dialog_color = dialog.TYPE_COLORS.get(dialog.dialog_type, PRIMARY_COLOR)
    accent_bg = dialog._lighten_color(dialog_color, dialog.LIGHT_ACCENT_FACTOR)
    text_font = dialog.text_font_family
    return f"""
        #firmwareUploadPanel {{
            background: transparent;
        }}
        #firmwareUploadPanel QScrollArea {{
            background: transparent;
            border: none;
        }}
        #firmwareUploadPanel QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}
        /* Any QSS on a scroll area drops its scrollbars to the ancient
           non-native look — restyle them like the dialog's own scroll areas
           (slim, rounded, no arrow buttons). */
        #firmwareUploadPanel QScrollBar:vertical {{
            background: transparent;
            width: 12px;
            border-radius: 6px;
            margin: 0px;
        }}
        #firmwareUploadPanel QScrollBar::handle:vertical {{
            background-color: #C0C0C0;
            border-radius: 6px;
            min-height: 20px;
        }}
        #firmwareUploadPanel QScrollBar::handle:vertical:hover {{
            background-color: #A0A0A0;
        }}
        #firmwareUploadPanel QScrollBar:horizontal {{
            background: transparent;
            height: 12px;
            border-radius: 6px;
            margin: 0px;
        }}
        #firmwareUploadPanel QScrollBar::handle:horizontal {{
            background-color: #C0C0C0;
            border-radius: 6px;
            min-width: 20px;
        }}
        #firmwareUploadPanel QScrollBar::handle:horizontal:hover {{
            background-color: #A0A0A0;
        }}
        #firmwareUploadPanel QScrollBar::add-line, #firmwareUploadPanel QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}
        #firmwareUploadPanel QScrollBar::add-page, #firmwareUploadPanel QScrollBar::sub-page {{
            background: none;
        }}
        #firmwareUploadPanel::handle:horizontal {{
            width: 5px;
            background-color: {dialog.BORDER_COLOR};
            border-radius: 2px;
            margin: 8px 0px;
        }}
        #firmwareUploadPanel QLabel {{
            color: {dialog.TEXT_COLOR};
            background: transparent;
            font-family: "{text_font}";
            font-size: 12px;
        }}
        #firmwareUploadPanel QGroupBox {{
            color: {dialog.TEXT_COLOR};
            background: transparent;
            border: 1px solid {dialog.BORDER_COLOR};
            border-radius: 8px;
            margin-top: 12px;
            font-family: "{text_font}";
            font-size: 12px;
            font-weight: 600;
        }}
        #firmwareUploadPanel QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0px 4px;
            color: {dialog_color};
            background-color: {accent_bg};
        }}
        #firmwareUploadPanel QCheckBox {{
            color: {dialog.TEXT_COLOR};
            background: transparent;
            font-family: "{text_font}";
            font-size: 12px;
        }}
        #firmwareUploadPanel QCheckBox::indicator {{
            width: 15px;
            height: 15px;
            border: 1px solid {dialog.BORDER_COLOR};
            border-radius: 4px;
            background-color: {dialog.DIALOG_BG_COLOR};
        }}
        #firmwareUploadPanel QCheckBox::indicator:checked {{
            background-color: {dialog_color};
            border-color: {dialog_color};
        }}
        #firmwareUploadPanel QLineEdit {{
            color: {dialog.TEXT_COLOR};
            background-color: {dialog.DIALOG_BG_COLOR};
            border: 1px solid {dialog.BORDER_COLOR};
            border-radius: 4px;
            padding: 3px 6px;
            font-family: "{text_font}";
            font-size: 12px;
            selection-background-color: {dialog_color};
            selection-color: {WHITE};
        }}
        #firmwareUploadPanel QComboBox {{
            color: {dialog.TEXT_COLOR};
            background-color: {dialog.DIALOG_BG_COLOR};
            border: 1px solid {dialog.BORDER_COLOR};
            border-radius: 4px;
            padding: 3px 6px;
            font-family: "{text_font}";
            font-size: 12px;
        }}
        #firmwareUploadPanel QComboBox QAbstractItemView {{
            color: {dialog.TEXT_COLOR};
            background-color: {dialog.DIALOG_BG_COLOR};
            selection-background-color: {dialog_color};
            selection-color: {WHITE};
        }}
        #firmwareUploadPanel QPushButton {{
            color: {dialog.EXIT_BUTTON_TEXT_COLOR};
            background-color: {dialog.EXIT_BUTTON_COLOR};
            border: 1px solid {dialog.BORDER_COLOR};
            border-radius: 6px;
            padding: 4px 12px;
            font-family: "{text_font}";
            font-size: 12px;
        }}
        #firmwareUploadPanel QPushButton:hover {{
            background-color: {dialog._darken_color(dialog.EXIT_BUTTON_COLOR, 0.05)};
        }}
        #firmwareUploadPanel QToolButton {{
            color: {dialog.TEXT_COLOR};
            background: transparent;
            border: none;
            border-radius: 4px;
            padding: 2px;
        }}
        #firmwareUploadPanel QToolButton:hover {{
            background-color: rgba(0, 0, 0, 0.08);
        }}
        #firmwareUploadPanel QToolButton:checked {{
            color: {WHITE};
            background-color: {dialog_color};
        }}
    """

class FirmwareUploadLiveState(HasTraits):
    """Thread hand-off for backend publishes (fluorescence pane pattern):
    the dramatiq listener thread writes each (topic, message) tuple here and
    the controller's dispatch="ui" observer applies it to the model on the
    GUI thread. An Event trait fires on every write — a plain trait's
    equality check would swallow consecutive identical log lines."""

    backend_message = Event()


class FirmwareUploadDialogController(HasTraits):
    """Builds the styled dialog, publishes upload/cancel requests to the
    backend, and applies the backend's firmware-upload signals to the model
    on the GUI thread via a dispatch="ui" observer on live_state."""

    model = Instance(FirmwareUploadModel, ())
    live_state = Instance(FirmwareUploadLiveState, ())

    dialog = Any()
    traits_ui = Any()
    listener_actor = Any()

    # ---- dialog assembly -------------------------------------------------

    def open(self):
        self.dialog = BaseMessageDialog(
            title="Upload Firmware",
            message="Flash the MicroPython firmware to a connected Pico "
                    "board. Configure the source, port, and options below, "
                    "then press Upload.",
            dialog_type=BaseMessageDialog.TYPE_QUESTION,
            buttons={
                "Close": {"action": self._request_close, "role": "exit"},
                "Upload": {"action": self._start_upload},
            },
            resizable=True,
        )
        # Wide two-pane layout: give the config column and the log console
        # room side by side (the base dialog would otherwise cap at 1000x800
        # and open much narrower).
        self.dialog.setMinimumSize(QSize(980, 620))
        self.dialog.setMaximumSize(QSize(1700, 1200))
        # Keep the intro message compact so the config panel gets the space.
        self.dialog.message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.traits_ui = self.model.edit_traits(
            view=firmware_upload_view, kind="subpanel", parent=self.dialog)
        # The built control is the HSplit's QSplitter; the left column's own
        # QScrollArea is made transparent by the panel stylesheet.
        panel = self.traits_ui.control
        panel.setObjectName("firmwareUploadPanel")
        panel.setStyleSheet(build_panel_stylesheet(self.dialog))
        stretch_group_layouts_horizontally(panel)
        self.dialog.add_content_widget(panel)

        # Backend signals land on the listener's worker thread, which only
        # writes live_state; the dispatch="ui" observer below applies them
        # to the model on the GUI thread.
        self.listener_actor = generate_class_method_dramatiq_listener_actor(
            listener_name=DEMO_LISTENER_NAME,
            class_method=self._on_backend_message)

        self.dialog.finished.connect(self._on_dialog_closed)
        self.dialog.show()

    def _request_close(self):
        if self.model.uploading:
            if confirm(self.dialog,
                       "An upload is still running — abort it and close?",
                       title="Upload in progress") != YES:
                return
            publish_message(message="", topic=CANCEL_FIRMWARE_UPLOAD)
        self.dialog.close_with_result(BaseMessageDialog.RESULT_CANCEL)

    def _on_dialog_closed(self, *args):
        if self.traits_ui is not None:
            self.traits_ui.dispose()
            self.traits_ui = None

    # ---- upload run ------------------------------------------------------

    def _start_upload(self):
        if self.model.uploading:
            return
        problems = self.model.validation_problems()
        if problems:
            error(self.dialog,
                  "Fix the following before uploading:",
                  title="Cannot upload",
                  detail="\n".join(problems), detail_collapsible=False)
            return
        # Optimistically lock the controls; the backend's STARTED/FINISHED
        # signals confirm and release.
        self.model.uploading = True
        try:
            upload_firmware_publisher.publish(
                **self.model.upload_request_kwargs())
        except Exception as e:
            logger.warning(f"Failed to publish upload request: {e}")
            self.model.upload_log += f"Failed to publish upload request: {e}\n"
            self.model.uploading = False

    def _on_backend_message(self, timestamped_message, topic):
        """Dramatiq listener (worker thread): ferry each backend publish to
        the GUI thread via live_state — never touch the model here."""
        self.live_state.backend_message = (topic, str(timestamped_message))

    @observe("live_state:backend_message", dispatch="ui")
    def _apply_backend_message(self, event):
        """Apply one backend publish to the model (GUI thread)."""
        topic, message = event.new
        if topic == FIRMWARE_UPLOAD_LOG:
            self.model.upload_log += f"{message}\n"
        elif topic == FIRMWARE_UPLOAD_STARTED:
            self.model.uploading = True
            self.model.upload_log += f"{message}\n"
        elif topic == FIRMWARE_UPLOAD_FINISHED:
            self.model.uploading = False
            self.model.upload_log += f"{self._finished_verdict(message)}\n"

    @staticmethod
    def _finished_verdict(message):
        """Human-readable verdict from a FIRMWARE_UPLOAD_FINISHED payload."""
        try:
            payload = json.loads(message)
        except Exception:
            logger.error(f"Unparseable upload-finished payload: {message!r}")
            return f"\nUpload finished (unparseable result: {message!r})."
        if "error" in payload:
            return f"\nUpload CRASHED: {payload['error']}"
        return ("\nUpload finished successfully." if payload.get("success")
                else "\nUpload FAILED (see the log above).")

    @observe("model:uploading")
    def _on_uploading_changed(self, event):
        upload_button = self.dialog.get_button("Upload") if self.dialog else None
        if upload_button is not None:
            upload_button.setEnabled(not event.new)


def main():
    """In-process demo harness (dropbot_protocol_controls demo pattern):
    message router + the composed fluorescence backend + this dialog, so the
    decoupled front/back ends run end-to-end without the full app."""
    app = QApplication.instance() or QApplication(sys.argv)

    from microdrop_style.helpers import style_app
    style_app(app)

    router = MessageRouterActor()

    # Compose the backend exactly like the plugin does (mixin services onto
    # the controller base); keep the reference alive for the app's lifetime.
    demo_backend_class = type(
        "DemoFluorescenceBackend",
        (FluorescenceFirmwareUploadService, FluorescenceMonitorMixinService,
         FluorescenceControllerBase), {})
    backend = demo_backend_class()

    for backend_listener_name, topics in ACTOR_TOPIC_DICT.items():
        for topic in topics:
            router.message_router_data.add_subscriber_to_topic(
                topic, backend_listener_name)
    for topic in (FIRMWARE_UPLOAD_STARTED, FIRMWARE_UPLOAD_LOG,
                  FIRMWARE_UPLOAD_FINISHED):
        router.message_router_data.add_subscriber_to_topic(
            topic, DEMO_LISTENER_NAME)

    controller = FirmwareUploadDialogController()
    controller.open()
    app.exec()
    backend.cleanup()


if __name__ == "__main__":
    from microdrop_utils.broker_server_helpers import (
        dramatiq_workers_context, redis_server_context,
    )

    with redis_server_context():
        with dramatiq_workers_context():
            main()
