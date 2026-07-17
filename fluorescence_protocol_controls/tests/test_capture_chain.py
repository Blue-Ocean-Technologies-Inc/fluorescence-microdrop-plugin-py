"""Hardware-free tests for the capture-chain value contract: the
`ChainEntry` model, tolerant parse/dump round trip, the ticked-rows
filter, and the label sanitize/uniqueness helpers."""
import pytest
from pydantic import ValidationError

from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_protocol_controls.capture_chain import (
    ChainEntry, dump_chain, parse_chain, sanitize_label, ticked,
    unique_label,
)


def _entry(**overrides):
    values = dict(
        label="GFP", wavelength=LED_WAVELENGTHS[0], intensity=50,
        frequency=1000, exposure_ms=10.0, gain=100, run=True,
    )
    values.update(overrides)
    return ChainEntry(**values)


# --- ChainEntry ---------------------------------------------------------

def test_led_index_matches_led_wavelengths_index():
    for wavelength in LED_WAVELENGTHS:
        entry = _entry(wavelength=wavelength)
        assert entry.led_index == LED_WAVELENGTHS.index(wavelength)


def test_out_of_bounds_field_raises_validation_error():
    with pytest.raises(ValidationError):
        _entry(intensity=-1)


# --- parse_chain / dump_chain round trip --------------------------------

def test_round_trip_parse_dump():
    entries = [_entry(label="GFP"), _entry(label="mCherry", run=False)]
    restored = parse_chain(dump_chain(entries))
    assert restored == entries


def test_parse_chain_none_and_empty_list():
    assert parse_chain(None) == []
    assert parse_chain([]) == []


def test_parse_chain_skips_invalid_entries_keeps_valid_siblings():
    good = _entry(label="GFP").model_dump()
    bad_wavelength = _entry(label="Bad").model_dump()
    bad_wavelength["wavelength"] = "not-a-wavelength"
    bad_intensity = _entry(label="Negative").model_dump()
    bad_intensity["intensity"] = -5

    restored = parse_chain([good, bad_wavelength, bad_intensity])
    assert [e.label for e in restored] == ["GFP"]


# --- ticked --------------------------------------------------------------

def test_ticked_filters_to_run_true():
    entries = [_entry(label="A", run=True), _entry(label="B", run=False),
               _entry(label="C", run=True)]
    assert [e.label for e in ticked(entries)] == ["A", "C"]


# --- sanitize_label --------------------------------------------------------

def test_sanitize_label_strips_and_replaces_spaces():
    assert sanitize_label("GFP #1 (a)") == "GFP_1_a"


def test_sanitize_label_empty_result_falls_back_to_capture():
    assert sanitize_label("###") == "capture"


# --- unique_label ----------------------------------------------------------

def test_unique_label_no_collision_returns_as_is():
    assert unique_label("GFP", set()) == "GFP"


def test_unique_label_suffixes_first_free_number():
    assert unique_label("GFP", {"GFP", "GFP_2"}) == "GFP_3"
