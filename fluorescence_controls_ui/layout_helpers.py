# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Qt sizing fixes TraitsUI cannot express, applied to a built pane UI."""


def set_minimum_visible_rows(table_view, rows):
    """Floor ``table_view``'s height at its column header plus ``rows`` rows.

    A TableEditor's minimum size hint is a single row, so a pane short on
    height squashes the table down to one visible entry. Measured from the
    live header and row height, the floor tracks font and DPI; past it the
    table scrolls its own rows.
    """
    header_height = table_view.horizontalHeader().sizeHint().height()
    rows_height = rows * table_view.verticalHeader().defaultSectionSize()

    table_view.setMinimumHeight(
        header_height + rows_height + 2 * table_view.frameWidth()
    )
