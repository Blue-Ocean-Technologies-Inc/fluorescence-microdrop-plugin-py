import json
import time

from traits.api import provides, HasTraits, Instance

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message

from ..consts import FLUORESCENCE_APPLIED
from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..datamodels import (
    ProtocolSetFluorescenceData, SetLedData, SetLedFrequencyData,
)

from logger.logger_service import get_logger
logger = get_logger(__name__)


@provides(IFluorescenceControlMixinService)
class FluorescenceCommandSetterService(HasTraits):
    """Sends commands to the fluorescence LED board.

    Typed handlers validate a small JSON payload and format the matching
    plain-text command (``led_<index>_<duty>``, ``ledf_<index>_<freq>``,
    ``led_off``, ``led_on``), so callers don't have to know the wire syntax.
    ``on_send_command_request`` stays as the raw escape hatch.
    """

    proxy = Instance(FluorescenceSerialProxy)

    def on_send_command_request(self, body):
        """Raw passthrough: send a plain-text command line to the board."""
        self.proxy.send_command(body)

    def on_set_led_request(self, body):
        """Drive one LED. ``exclusive`` runs the off->on sequence atomically
        here (one handler invocation), never as two pub/sub messages. The
        transaction lock keeps the pair contiguous on the wire — handlers
        run on a multi-threaded worker pool."""
        data = SetLedData(**json.loads(body))
        with self.proxy.transaction_lock:
            if data.exclusive:
                self.proxy.send_command("led_off")
            self.proxy.send_command(f"led_{data.led}_{data.duty}")

    def on_set_led_frequency_request(self, body):
        data = SetLedFrequencyData(**json.loads(body))
        self.proxy.send_command(f"ledf_{data.led}_{data.frequency}")

    def on_all_leds_off_request(self, body):
        self.proxy.send_command("led_off")

    def on_all_leds_on_request(self, body):
        """Restore the last duty the firmware remembers (board-side state)."""
        self.proxy.send_command("led_on")

    def on_protocol_set_fluorescence_request(self, body):
        """Protocol step apply: frequency + exclusive off->on LED set (or
        all off) in ONE handler call, then the requested settle, then the
        FLUORESCENCE_APPLIED ack — the protocol's wait_for unblocks only
        once the light is stable enough to capture. On any failure the ack
        is withheld so the protocol's wait times out and the step fails
        (the magnet backend's error contract)."""
        data = ProtocolSetFluorescenceData(**json.loads(body))
        try:
            # Lock keeps the sequence contiguous on the wire; the settle
            # sleeps OUTSIDE it so the port isn't held for the wait.
            with self.proxy.transaction_lock:
                if data.light_on:
                    self.proxy.send_command(f"ledf_{data.led}_{data.frequency}")
                    self.proxy.send_command("led_off")
                    self.proxy.send_command(f"led_{data.led}_{data.duty}")
                else:
                    self.proxy.send_command("led_off")
            time.sleep(data.settle_s)
        except Exception:
            logger.exception(
                "protocol_set_fluorescence failed; ack withheld")
            return
        publish_message(topic=FLUORESCENCE_APPLIED,
                        message=str(int(data.light_on)))
