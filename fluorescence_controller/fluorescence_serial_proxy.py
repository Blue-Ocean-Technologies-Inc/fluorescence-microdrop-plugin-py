import json
import re
import threading

import serial

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from .consts import CONNECTED, DISCONNECTED, TELEMETRY, BOARD_ID, BOARD_BAUDRATE

logger = get_logger(__name__)

# The led_help response block: header/footer dash lines bracket the command
# list plus an "LED Index Mapping:" section of "  <index>: <name>" rows.
HELP_HEADER = "-" * 20 + " Help " + "-" * 20
HELP_FOOTER = "-" * 40
HELP_LED_ROW_RE = re.compile(r"^\s*(\d+):\s*(\S+)\s*$")
BOARD_NAME = "LED Controller"


def parse_led_help_block(lines) -> dict:
    """Board identity from a captured led_help block: the firmware has no
    whoami over serial, but its help response lists the LED index mapping —
    enough to name the board and enumerate its channels."""
    leds = []
    for line in lines:
        match = HELP_LED_ROW_RE.match(line)
        if match:
            leds.append(match.group(2))
    return {"name": BOARD_NAME, "leds": leds}


class FluorescenceSerialProxy:
    """Minimal headless serial proxy for the fluorescence LED board.

    Newline-terminated plain-text protocol: commands go out as text lines and
    every response line is published on TELEMETRY — except the led_help block
    requested on connect, which is captured whole and published as the
    BOARD_ID identity instead of spamming the log.
    """

    def __init__(self, port):
        self.port = port
        self._serial = serial.Serial(port, BOARD_BAUDRATE, timeout=1)
        self._stop = threading.Event()
        self._help_lines = None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        publish_message(message=port, topic=CONNECTED)
        logger.info(f"Fluorescence board connected on {port}")
        # Identity probe: the help response carries the LED index mapping.
        self.send_command("led_help")

    # ------------------------------------------------------------------ #
    # Serial I/O                                                          #
    # ------------------------------------------------------------------ #
    def send_command(self, command: str):
        logger.debug(f"-> {command}")
        self._serial.write(f"{command}\r\n".encode())

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                line = self._serial.readline().decode(errors="replace").strip()
            except (serial.SerialException, OSError):
                logger.info("Fluorescence serial read failed; disconnecting")
                self.terminate()
                break
            if line:
                self._handle_line(line)

    def _handle_line(self, line: str):
        # Capture a led_help block whole -> BOARD_ID; everything else is a
        # plain telemetry/ack line.
        if line == HELP_HEADER:
            self._help_lines = []
            return
        if self._help_lines is not None:
            if line == HELP_FOOTER:
                publish_message(message=json.dumps(parse_led_help_block(self._help_lines)),
                                topic=BOARD_ID)
                self._help_lines = None
            else:
                self._help_lines.append(line)
            return
        publish_message(message=line, topic=TELEMETRY)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #
    def terminate(self):
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._serial.close()
        except Exception:
            pass
        publish_message(message=self.port, topic=DISCONNECTED)
