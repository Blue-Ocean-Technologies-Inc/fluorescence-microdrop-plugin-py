# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

# Enthought library imports.
from traits.api import Instance, List, Str

# Microdrop package imports.
from peripheral_device_controller_base.consts import (
    DEFAULT_ALWAYS_ALLOWED_SUBTOPICS,
    FIRMWARE_UPLOAD_ALWAYS_ALLOWED_SUBTOPICS,
)
from peripheral_device_controller_base.peripheral_device_controller_base import (
    PeripheralDeviceControllerBase,
)

# Local imports.
from .consts import DEVICE_NAME
from .fluorescence_serial_proxy import FluorescenceSerialProxy

# Logger import.
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
        DEFAULT_ALWAYS_ALLOWED_SUBTOPICS + FIRMWARE_UPLOAD_ALWAYS_ALLOWED_SUBTOPICS,
    )
