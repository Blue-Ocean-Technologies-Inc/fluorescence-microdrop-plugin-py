from traits.api import provides, Instance

from peripheral_device_controller_base.services.peripheral_firmware_upload_service import (
    PeripheralFirmwareUploadService,
)

from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy


@provides(IFluorescenceControlMixinService)
class FluorescenceFirmwareUploadService(PeripheralFirmwareUploadService):
    """Fluorescence firmware-upload mixin.

    All the logic lives in PeripheralFirmwareUploadService (topics derived
    from the composed controller's ``_device_name``, port finding via its
    ``_default_hwids``); this subclass only provides the fluorescence
    control-mixin interface and narrows the proxy type so the plugin composes
    exactly the fluorescence mixins.
    """
    proxy = Instance(FluorescenceSerialProxy)
