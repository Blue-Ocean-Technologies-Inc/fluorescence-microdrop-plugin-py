"""Hardware-free tests for the capture-chain value contract: the
`ChainEntry` model, tolerant parse/dump round trip, the ticked-rows
filter, and the label sanitize/uniqueness helpers."""
import pytest
from pydantic import ValidationError

from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_protocol_controls.capture_chain import (
    ChainEntry, dump_chain, parse_chain, sanitize_label, ticked,
    chain_label,
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


# --- chain_label -----------------------------------------------------------

def test_chain_label_without_tag_is_wavelength_index():
    assert chain_label("", "Green (540 nm)", 2) == "Green_540_nm_2"


def test_chain_label_with_tag_prefixes_it():
    assert chain_label("gfp", "Green (540 nm)", 1) == "gfp_Green_540_nm_1"


def test_chain_label_sanitizes_the_tag():
    assert chain_label("my #tag!", "Blue (460 nm)", 3) == "my_tag_Blue_460_nm_3"


def test_chains_saved_before_auto_flags_load_with_auto_off():
    """Back-compat: pre-auto chain dicts (no auto_* keys) parse with the
    flags defaulted off."""
    old = {"label": "GFP", "wavelength": LED_WAVELENGTHS[2], "intensity": 50,
           "frequency": 40000, "exposure_ms": 10.0, "gain": 0, "run": True}
    [entry] = parse_chain([old])
    assert entry.auto_exposure is False and entry.auto_gain is False


# --- capture_start / capture_end phase fields ---------------------------

def test_phase_fields_default_to_step_start_only():
    entry = _entry()
    assert entry.capture_start is True
    assert entry.capture_end is False


def test_legacy_dict_without_phase_keys_parses_to_step_start_only():
    raw = _entry().model_dump()
    del raw["capture_start"], raw["capture_end"]
    [restored] = parse_chain([raw])
    assert restored.capture_start is True
    assert restored.capture_end is False


def test_phase_fields_round_trip():
    entries = [_entry(label="both", capture_start=True, capture_end=True),
               _entry(label="end_only", capture_start=False,
                      capture_end=True)]
    restored = parse_chain(dump_chain(entries))
    assert [(e.capture_start, e.capture_end) for e in restored] \
        == [(True, True), (False, True)]


def test_both_phases_false_is_coerced_to_step_start():
    entry = _entry(capture_start=False, capture_end=False)
    assert entry.capture_start is True
    assert entry.capture_end is False
