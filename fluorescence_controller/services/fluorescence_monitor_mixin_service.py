from traits.api import List, Str, provides

from peripheral_device_controller_base.services.peripheral_device_monitor_mixin_service import (  # noqa: E501 -- dotted module path can't be shortened
    PeripheralDeviceMonitorMixinService,
)

from ..consts import DEVICE_ID_FRAGMENT, DEVICE_NAME, FLUORESCENCE_HWID
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..interfaces.i_fluorescence_control_mixin_service import (
    IFluorescenceControlMixinService,
)

from logger.logger_service import get_logger

logger = get_logger(__name__)


@provides(IFluorescenceControlMixinService)
class FluorescenceMonitorMixinService(PeripheralDeviceMonitorMixinService):
    """Monitors for the fluorescence board connection."""

    id = Str(f"{DEVICE_NAME}_monitor_mixin_service")
    name = Str(f"{DEVICE_NAME.title()} Monitor Mixin")

    _default_hwids = List(Str, [FLUORESCENCE_HWID])

    # The heater board shares the Pico 2E8A:0005 id, so the base monitor
    # probes each candidate port's whoami device_id for this fragment before
    # claiming it.
    _device_id_fragment = Str(DEVICE_ID_FRAGMENT)

    def _make_proxy(self, port_name):
        # port_name is the base monitor's ClaimedPort: the proxy adopts its
        # probe-time serial handle instead of reopening the port.
        return FluorescenceSerialProxy(
            port=str(port_name),
            expected_device_id_fragment=DEVICE_ID_FRAGMENT,
            serial_instance=getattr(port_name, "serial", None),
        )
