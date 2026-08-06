from traits.api import provides, Str, List

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

    # The heater board shares the Pico 2E8A:0005 id, so the base monitor
    # probes each candidate port's whoami device_id for this fragment before
    # claiming it.
    _device_id_fragment = Str(DEVICE_ID_FRAGMENT)

    def _make_proxy(self, port_name):
        return FluorescenceSerialProxy(
            port=port_name, expected_device_id_fragment=DEVICE_ID_FRAGMENT)
