# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""The fluorescence plugin's contribution to the core image viewer's
``IMAGE_FILTERS`` extension point: an LED-wavelength filter derived from
capture filenames."""

# Standard library imports.
from pathlib import Path

# Microdrop package imports.
from fluorescence_controller.consts import LED_WAVELENGTHS

# Local imports.
from .capture_chain import sanitize_label

#: sanitized-token -> display name for the six LED wavelengths; derived
#: labels embed the sanitized form (e.g. "Green_540_nm"), which is how a
#: file's wavelength is detected.
WAVELENGTH_TOKENS = {sanitize_label(name): name for name in LED_WAVELENGTHS}


class WavelengthImageFilter:
    """Classifies a capture filename by the LED wavelength it embeds."""

    name = "Wavelength"
    tooltip = "Show only captures of one LED wavelength (detected from the filenames)"

    def classify(self, path) -> str:
        """The display wavelength a capture filename embeds, or '' when
        none of the known LED wavelengths appears in it (e.g. legacy
        screen captures)."""
        name = Path(path).name

        for token, display in WAVELENGTH_TOKENS.items():
            if token in name:
                return display

        return ""
