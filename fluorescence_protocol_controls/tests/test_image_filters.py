# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for the wavelength image filter contributed to the
core image viewer."""

# Microdrop package imports.
from fluorescence_protocol_controls.image_filters import WavelengthImageFilter


def test_detect_wavelength_from_derived_labels():
    classify = WavelengthImageFilter().classify

    assert (
        classify("gfp_Green_540_nm_2_2026_07_20-17_46_24_raw.png") == "Green (540 nm)"
    )
    assert classify("Deep_Red_660_nm_1_ts.png") == "Deep Red (660 nm)"
    assert classify("free_mode_2026_07_20-17_50_08_raw.png") == ""
