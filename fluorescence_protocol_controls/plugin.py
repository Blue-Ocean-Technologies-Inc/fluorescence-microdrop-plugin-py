# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""FluorescenceProtocolControlsPlugin — contributes the fluorescence
per-step settings column to the pluggable protocol tree.

Sibling plugin to fluorescence_controls_ui (column declarations are a UI
concern; the board request handlers stay in fluorescence_controller).
Loaded with the fluorescence UI plugin group.
"""

# Enthought library imports.
from envisage.plugin import Plugin
from traits.api import Instance, List

# Microdrop package imports.
from pluggable_protocol_tree.consts import PROTOCOL_COLUMNS
from pluggable_protocol_tree.interfaces.i_column import IColumn

# Local imports.
from .consts import PKG, PKG_name
from .protocol_columns.chain_column import make_fluorescence_chain_column

# Logger import.
from logger.logger_service import get_logger

logger = get_logger(__name__)


class FluorescenceProtocolControlsPlugin(Plugin):
    id = PKG + ".plugin"
    name = f"{PKG_name} Plugin"

    contributed_protocol_columns = List(
        Instance(IColumn),
        contributes_to=PROTOCOL_COLUMNS,
    )

    def _contributed_protocol_columns_default(self):
        return [make_fluorescence_chain_column()]
