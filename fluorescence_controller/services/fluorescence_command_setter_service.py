from traits.api import provides, HasTraits, Instance

from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy

from logger.logger_service import get_logger
logger = get_logger(__name__)


@provides(IFluorescenceControlMixinService)
class FluorescenceCommandSetterService(HasTraits):
    """Sends commands to the fluorescence board.

    ``on_send_command_request`` is the generic raw-command escape hatch
    (forwards the message content verbatim). Typed handlers for the board's
    real command set get added here as the standalone app logic is ported.
    """

    proxy = Instance(FluorescenceSerialProxy)

    def on_send_command_request(self, body):
        """Raw passthrough: send a plain-text command line to the board."""
        self.proxy.send_command(body)
