"""Qt-free model for the firmware-upload dialog: the request options, the
live log text, and the payload builder for the validated publisher."""

from pathlib import Path

import serial.tools.list_ports

from traits.api import (
    Bool, Button, Directory, File, HasTraits, Int, List, Str, observe,
)

from fluorescence_controller.consts import (
    FLUORESCENCE_BOARD_DEVICE_ID, PICO_USB_VENDOR_ID,
)

from .consts import DEFAULT_FIRMWARE_DIR, PORT_ENTRY_SEPARATOR


class FirmwareUploadModel(HasTraits):
    """Options for one firmware-upload request, plus the live log."""

    firmware_dir = Directory()
    single_file = File()

    #: True: the backend resolves the port (a connected proxy's stored port,
    #: else whoami / VID probing). False: send the selection below.
    auto_port = Bool(True)
    available_ports = List(Str)
    selected_port_entry = Str()
    refresh_ports = Button()

    device_id = Str(FLUORESCENCE_BOARD_DEVICE_ID)

    update_config = Bool(False)
    skip_filesystem_format = Bool(False)
    reset_after_upload = Bool(True)
    dry_run = Bool(False)

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
        return [f"{p.device}{PORT_ENTRY_SEPARATOR}{p.description}"
                for p in ports]

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
