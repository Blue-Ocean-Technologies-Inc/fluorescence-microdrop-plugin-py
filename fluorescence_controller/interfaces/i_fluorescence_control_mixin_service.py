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
from traits.api import Instance

# Microdrop package imports.
from peripheral_device_controller_base.interfaces.i_peripheral_device_control_mixin_service import (  # noqa: E501 -- dotted module path can't be shortened
    IPeripheralDeviceControlMixinService,
)

# Local imports.
from ..fluorescence_serial_proxy import FluorescenceSerialProxy


class IFluorescenceControlMixinService(IPeripheralDeviceControlMixinService):
    """Interface for the fluorescence control mixins. Narrows ``proxy`` to the
    fluorescence serial proxy so the plugin only composes its own mixins."""

    proxy = Instance(FluorescenceSerialProxy)
