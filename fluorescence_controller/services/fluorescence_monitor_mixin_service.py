from traits.api import provides, Str, List

from microdrop_utils.hardware_device_monitoring_helpers import find_port_by_device_id

from peripheral_device_controller_base.services.peripheral_device_monitor_mixin_service import (
    PeripheralDeviceMonitorMixinService,
)
from logger.logger_service import get_logger

from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..consts import FLUORESCENCE_HWID, DEVICE_NAME, DEVICE_ID_FRAGMENT

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
        """Locate the board by VID:PID AND whoami identity: the heater board
        shares the Pico 2E8A:0005 id, so each candidate port is probed for a
        device_id containing "fluo" before it is claimed."""
        return find_port_by_device_id(hwids, DEVICE_ID_FRAGMENT)
