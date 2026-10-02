# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for Multi-Channel capture-chain entries (#31): the
entry contract (validation, compatibility with entries saved before mixes,
round trip), the derived mix label and image-filter token, and the
column's summary."""

# Standard library imports.
import json

# Third-party imports.
import pytest
from pydantic import ValidationError

# Microdrop package imports.
from fluorescence_controller.consts import LED_WAVELENGTHS, MULTI_CHANNEL
from fluorescence_protocol_controls.capture_chain import (
    ChainEntry,
    chain_label,
    dump_chain,
    mix_label,
    parse_chain,
)
from fluorescence_protocol_controls.image_filters import WavelengthImageFilter
from fluorescence_protocol_controls.protocol_columns.chain_column import (
    make_fluorescence_chain_column,
)
from pluggable_protocol_tree.models.row import BaseRow, build_row_type

#: Blue 100 %, Green 60 %, Red 25 %.
MIX = {0: 100, 2: 60, 4: 25}


def _entry(**overrides):
    values = dict(
        label="mix",
        wavelength=MULTI_CHANNEL,
        intensity=80,
        frequency=40000,
        exposure_ms=10.0,
        gain=0,
        proportions=MIX,
    )
    values.update(overrides)

    return ChainEntry(**values)


# --- entry contract ---------------------------------------------------------------


def test_mix_entry_needs_proportions():
    with pytest.raises(ValidationError):
        _entry(proportions=None)

    with pytest.raises(ValidationError):
        _entry(proportions={})


@pytest.mark.parametrize("proportions", [{0: 101}, {0: -1}, {6: 50}, {-1: 50}])
def test_mix_proportions_are_bounded(proportions):
    with pytest.raises(ValidationError):
        _entry(proportions=proportions)


def test_single_wavelength_entry_drops_stray_proportions():
    entry = _entry(wavelength=LED_WAVELENGTHS[1])

    assert entry.proportions is None
    assert entry.led_request() == {"led": 1, "duty": 80}


def test_entry_saved_before_mixes_loads_as_single_wavelength():
    legacy = {
        "label": "Green_540_nm_1",
        "wavelength": LED_WAVELENGTHS[2],
        "intensity": 50,
        "frequency": 40000,
        "exposure_ms": 10.0,
        "gain": 0,
        "run": True,
    }

    [entry] = parse_chain([legacy])

    assert not entry.multi_channel
    assert entry.proportions is None
    assert entry.led_request() == {"led": 2, "duty": 50}


def test_mix_entry_round_trips_through_a_protocol_file():
    stored = json.loads(json.dumps(dump_chain([_entry()])))  # int keys -> str

    [entry] = parse_chain(stored)

    assert entry == _entry()
    assert entry.proportions == MIX


def test_mix_led_request_lists_every_channel_at_the_intensity():
    assert _entry().led_request() == {
        "intensities": {0: 80, 1: 0, 2: 48, 3: 0, 4: 20, 5: 0}
    }


# --- label + image filter -----------------------------------------------------------


def test_mix_label_names_the_lit_channels():
    assert mix_label(MIX) == "Multi B100 G60 R25"
    assert mix_label({1: 0, 5: 40}) == "Multi DR40"
    assert mix_label({}) == "Multi"


def test_chain_label_spells_out_a_mix():
    assert chain_label("", MULTI_CHANNEL, 2, MIX) == "Multi_B100_G60_R25_2"
    assert chain_label("gfp", MULTI_CHANNEL, 1, MIX) == "gfp_Multi_B100_G60_R25_1"


def test_image_filter_classifies_mix_captures():
    classify = WavelengthImageFilter().classify

    assert classify("Multi_B100_G60_R25_2_2026_10_02-17_00_00.png") == MULTI_CHANNEL
    assert classify("Green_540_nm_1_ts.png") == "Green (540 nm)"


# --- column ---------------------------------------------------------------------------


@pytest.fixture
def row_type():
    col = make_fluorescence_chain_column()

    return build_row_type([col], base=BaseRow), col


def test_column_tooltip_lists_entries_with_the_mix(row_type):
    Row, col = row_type
    row = Row()
    entries = [
        _entry(label=chain_label("", MULTI_CHANNEL, 1, MIX)),
        _entry(label="Blue_460_nm_2", wavelength=LED_WAVELENGTHS[0], run=False),
    ]
    col.model.set_value(row, dump_chain(entries))

    assert col.view.format_display(dump_chain(entries), row) == "1/2"
    assert col.view.get_tooltip(row) == "Multi_B100_G60_R25_1\nBlue_460_nm_2 (parked)"
