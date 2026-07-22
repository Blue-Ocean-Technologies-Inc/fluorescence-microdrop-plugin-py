from traits.api import Instance, List, Str

from peripheral_device_controller_base.consts import (
    DEFAULT_ALWAYS_ALLOWED_SUBTOPICS, FIRMWARE_UPLOAD_ALWAYS_ALLOWED_SUBTOPICS,
)
from peripheral_device_controller_base.peripheral_device_controller_base import PeripheralDeviceControllerBase

from .fluorescence_serial_proxy import FluorescenceSerialProxy
from .consts import DEVICE_NAME

from logger.logger_service import get_logger
logger = get_logger(__name__, level="INFO")


class FluorescenceControllerBase(PeripheralDeviceControllerBase):
    """Backend controller for the fluorescence peripheral.

    All listener/routing/connection machinery is inherited from
    ``PeripheralDeviceControllerBase``; this subclass only pins the device
    identity and narrows the proxy trait type.
    """
    _device_name = Str(DEVICE_NAME)
    listener_name = Str("fluorescence_controller_listener")
    proxy = Instance(FluorescenceSerialProxy)
    # Firmware upload/cancel must run while disconnected: flashing IS the
    # recovery path for a board whose firmware can't connect, and the upload
    # service itself releases the proxy (disconnecting) before flashing.
    _always_allowed_subtopics = List(
        Str,
        DEFAULT_ALWAYS_ALLOWED_SUBTOPICS
        + FIRMWARE_UPLOAD_ALWAYS_ALLOWED_SUBTOPICS,
    )
