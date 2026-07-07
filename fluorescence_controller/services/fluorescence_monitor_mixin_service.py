from serial.tools.list_ports import grep
from traits.api import provides, Str, List

from peripheral_device_controller_base.services.peripheral_device_monitor_mixin_service import (
    PeripheralDeviceMonitorMixinService,
)
from logger.logger_service import get_logger

from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..consts import FLUORESCENCE_HWID, DEVICE_NAME

logger = get_logger(__name__)


@provides(IFluorescenceControlMixinService)
class FluorescenceMonitorMixinService(PeripheralDeviceMonitorMixinService):
    """Monitors for the fluorescence board connection."""
    id = Str(f"{DEVICE_NAME}_monitor_mixin_service")
    name = Str(f'{DEVICE_NAME.title()} Monitor Mixin')

    _default_hwids = List(Str, [FLUORESCENCE_HWID])

    def _make_proxy(self, port_name):
        return FluorescenceSerialProxy(port=port_name)

    def _find_port(self, hwids):
        """Locate the board's serial port by matching its VID:PID directly
        (the RP2040 CDC port does not always carry a "USB Serial" description,
        so the shared description-grep helper can miss it)."""
        for hwid in hwids:
            for port in grep(hwid):
                logger.info(f"Fluorescence board found on port {port.device} ({port.description})")
                return str(port.device)
        raise Exception(f"No fluorescence board for hwids {hwids} found")
