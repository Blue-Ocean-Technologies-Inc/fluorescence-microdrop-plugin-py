import threading

import serial

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from .consts import CONNECTED, DISCONNECTED, TELEMETRY, BOARD_BAUDRATE

logger = get_logger(__name__)


class FluorescenceSerialProxy:
    """Minimal headless serial proxy for the fluorescence board.

    Newline-terminated plain-text protocol like the heater board: commands go
    out as text lines; every response line is published on TELEMETRY for the
    frontend until the real framing is ported from the standalone app.
    """

    def __init__(self, port):
        self.port = port
        self._serial = serial.Serial(port, BOARD_BAUDRATE, timeout=1)
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        publish_message(message=port, topic=CONNECTED)
        logger.info(f"Fluorescence board connected on {port}")

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
        """Publish every board line as telemetry until real frames are ported."""
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
