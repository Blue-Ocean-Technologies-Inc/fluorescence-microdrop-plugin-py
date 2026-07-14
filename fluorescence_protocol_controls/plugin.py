"""FluorescenceProtocolControlsPlugin — contributes the fluorescence
per-step settings column to the pluggable protocol tree.

Sibling plugin to fluorescence_controls_ui (column declarations are a UI
concern; the board request handlers stay in fluorescence_controller).
Loaded with the fluorescence UI plugin group.
"""
from envisage.plugin import Plugin
from traits.api import Instance, List

from logger.logger_service import get_logger

from pluggable_protocol_tree.consts import PROTOCOL_COLUMNS
from pluggable_protocol_tree.interfaces.i_compound_column import (
    ICompoundColumn,
)

from .consts import PKG, PKG_name
from .protocol_columns.fluorescence_column import make_fluorescence_column

logger = get_logger(__name__)


class FluorescenceProtocolControlsPlugin(Plugin):
    id = PKG + ".plugin"
    name = f"{PKG_name} Plugin"

    contributed_protocol_columns = List(
        Instance(ICompoundColumn), contributes_to=PROTOCOL_COLUMNS,
    )

    def _contributed_protocol_columns_default(self):
        return [make_fluorescence_column()]
