import json

from traits.api import provides, HasTraits, Instance

from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..datamodels import SetLedData, SetLedFrequencyData

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
        here (one handler invocation), never as two pub/sub messages."""
        data = SetLedData(**json.loads(body))
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
