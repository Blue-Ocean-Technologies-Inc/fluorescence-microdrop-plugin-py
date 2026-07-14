import json
import threading
import time

import serial

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from .consts import (
    BOARD_BAUDRATE, BOARD_ID, COMMAND_RETRY_DELAY_S, CONNECTED, DISCONNECTED,
    MAX_COMMAND_RETRIES, SERIAL_READ_TIMEOUT_S, SERIAL_WRITE_TIMEOUT_S,
    TELEMETRY,
)

logger = get_logger(__name__)

# Boards in the heater firmware family reply to ``whoami`` with a single
# WHOAMI_MARKER-prefixed line carrying {"uid", "device_id", ...}.
WHOAMI_MARKER = "\u00a7WHOAMI"


def parse_whoami_line(line) -> dict | None:
    """The identity payload from a WHOAMI frame line, or None."""
    if not line.startswith(WHOAMI_MARKER):
        return None
    brace = line.find("{")
    if brace < 0:
        return None
    try:
        return json.loads(line[brace:])
    except Exception:
        logger.error(f"Unparseable WHOAMI frame: {line!r}")
        return None


class FluorescenceSerialProxy:
    """Minimal headless serial proxy for the fluorescence LED board.

    Newline-terminated plain-text protocol: commands go out as text lines and
    every response line is published on TELEMETRY — except the WHOAMI frame
    (requested on connect), which is published as the BOARD_ID identity.
    """

    def __init__(self, port):
        self.port = port
        self._serial = serial.Serial(
            port, BOARD_BAUDRATE,
            timeout=SERIAL_READ_TIMEOUT_S,
            write_timeout=SERIAL_WRITE_TIMEOUT_S,
        )
        # One writer at a time: commands arrive on the multi-threaded
        # dramatiq worker pool, and concurrent writes on one serial handle
        # interleave bytes mid-line (observed on Windows as garbled
        # commands + write timeouts). Reentrant so a handler can hold it
        # around a multi-command sequence while send_command re-acquires.
        self.transaction_lock = threading.RLock()
        # Flush any stale bytes before we start reading (heater parity).
        try:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except Exception as e:
            logger.debug(f"Could not flush fluorescence serial buffers: {e}")
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        publish_message(message=port, topic=CONNECTED)
        logger.info(f"Fluorescence board connected on {port}")
        # Identity probe: the board answers with a WHOAMI frame.
        self.send_command("whoami")

    # ------------------------------------------------------------------ #
    # Serial I/O                                                          #
    # ------------------------------------------------------------------ #
    def send_command(self, command: str):
        """Send one newline-terminated command, retrying transient write
        failures; a persistent failure disconnects the board (the write
        buffer is not draining — wedged firmware or unplugged), so the
        monitor can rediscover it instead of every later command erroring
        forever."""
        logger.debug(f"-> {command}")
        data = f"{command}\r\n".encode()
        for attempt in range(MAX_COMMAND_RETRIES):
            try:
                with self.transaction_lock:
                    self._serial.write(data)
                return
            except (serial.SerialException, OSError) as e:
                if attempt < MAX_COMMAND_RETRIES - 1:
                    logger.warning(
                        f"Fluorescence write failed (attempt {attempt + 1}"
                        f"/{MAX_COMMAND_RETRIES}): {e}")
                    time.sleep(COMMAND_RETRY_DELAY_S)
                    continue
                logger.error(
                    f"Fluorescence write failed after {MAX_COMMAND_RETRIES} "
                    f"attempts ({command!r}): {e}; disconnecting")
                self.terminate()
                raise

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
        identity = parse_whoami_line(line)
        if identity is not None:
            publish_message(message=json.dumps(identity), topic=BOARD_ID)
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
