from traits.api import Instance

from peripheral_device_controller_base.interfaces.i_peripheral_device_control_mixin_service import (
    IPeripheralDeviceControlMixinService,
)
from ..fluorescence_serial_proxy import FluorescenceSerialProxy


class IFluorescenceControlMixinService(IPeripheralDeviceControlMixinService):
    """Interface for the fluorescence control mixins. Narrows ``proxy`` to the
    fluorescence serial proxy so the plugin only composes its own mixins."""

    proxy = Instance(FluorescenceSerialProxy)
