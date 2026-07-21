"""Hardware-free tests for the panel model rework: a single param set (no
more mode/br_*/fl_* split) plus the chain-row state that backs the capture
chain table (`chain_rows`, `free_chain`, `chain_selection`,
`attached_step_id`/`attached_group_id`).

`FluorescenceChainRow` is the Qt-free row type the table editor binds to;
it round-trips against Task 1's `ChainEntry` (`exposure` <-> `exposure_ms`).
"""
from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_protocol_controls.capture_chain import ChainEntry

from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.consts import PERSISTED_CONTROL_TRAITS
from fluorescence_controls_ui.model import FluorescenceStatusModel


# --- FluorescenceChainRow <-> ChainEntry -----------------------------------------

def test_chain_row_defaults():
    row = FluorescenceChainRow()
    assert row.label == ""
    assert row.image_tag == ""
    assert row.wavelength == LED_WAVELENGTHS[0]
    assert row.intensity == 50
    assert row.frequency == 40000
    assert row.exposure == 10.0
    assert row.gain == 0
    assert row.run is True


def test_chain_row_to_entry_dict_round_trips_through_chain_entry():
    row = FluorescenceChainRow(
        label="GFP", wavelength=LED_WAVELENGTHS[2], intensity=75,
        frequency=1000, exposure=25.5, gain=150, run=False,
    )
    entry = ChainEntry(**row.to_entry_dict())
    assert entry.label == "GFP"
    assert entry.wavelength == LED_WAVELENGTHS[2]
    assert entry.intensity == 75
    assert entry.frequency == 1000
    assert entry.exposure_ms == 25.5
    assert entry.gain == 150
    assert entry.run is False


def test_chain_row_from_entry():
    entry = ChainEntry(
        label="DAPI", wavelength=LED_WAVELENGTHS[1], intensity=60,
        frequency=2000, exposure_ms=15.0, gain=100, run=True,
    )
    row = FluorescenceChainRow.from_entry(entry)
    assert row.label == "DAPI"
    assert row.wavelength == LED_WAVELENGTHS[1]
    assert row.intensity == 60
    assert row.frequency == 2000
    assert row.exposure == 15.0
    assert row.gain == 100
    assert row.run is True


def test_chain_row_from_entry_to_entry_dict_round_trip():
    entry = ChainEntry(
        label="Cy5", wavelength=LED_WAVELENGTHS[3], intensity=40,
        frequency=500, exposure_ms=8.0, gain=20, run=True,
    )
    row = FluorescenceChainRow.from_entry(entry)
    assert row.to_entry_dict() == entry.model_dump()


def test_chain_row_image_tag_round_trips_through_chain_entry():
    row = FluorescenceChainRow(image_tag="gfp", wavelength=LED_WAVELENGTHS[0])
    entry = ChainEntry(**row.to_entry_dict())
    assert entry.image_tag == "gfp"
    back = FluorescenceChainRow.from_entry(entry)
    assert back.image_tag == "gfp"


# --- model: deleted traits ---------------------------------------------------------

def test_model_has_no_mode_or_per_mode_traits():
    model = FluorescenceStatusModel()
    assert not hasattr(model, "mode")
    assert not hasattr(model, "br_wavelength")
    assert not hasattr(model, "br_intensity")
    assert not hasattr(model, "br_frequency")
    assert not hasattr(model, "br_exposure")
    assert not hasattr(model, "br_gain")
    assert not hasattr(model, "fl_wavelength")
    assert not hasattr(model, "fl_intensity")
    assert not hasattr(model, "fl_frequency")
    assert not hasattr(model, "fl_exposure")
    assert not hasattr(model, "fl_gain")
    assert not hasattr(model, "br_led_index")
    assert not hasattr(model, "fl_led_index")
    assert not hasattr(model, "show_brightfield")
    assert not hasattr(model, "show_fluorescence")


# --- model: new single param set ----------------------------------------------------

def test_model_has_single_param_set_with_old_br_defaults():
    model = FluorescenceStatusModel()
    assert model.image_tag == ""
    assert model.wavelength == LED_WAVELENGTHS[0]
    assert model.intensity == 50
    assert model.frequency == 40000
    assert model.exposure == 10.0
    assert model.gain == 0
    assert model.led_index == 0
    assert model.show_params is True


def test_model_led_index_tracks_wavelength():
    model = FluorescenceStatusModel()
    model.wavelength = LED_WAVELENGTHS[3]
    assert model.led_index == 3


# --- model: chain state --------------------------------------------------------------

def test_model_chain_state_defaults():
    model = FluorescenceStatusModel()
    assert model.chain_rows == []
    assert model.chain_selection is None
    assert model.attached_step_id == ""
    assert model.attached_group_id == ""
    assert model.free_chain == []


def test_model_chain_rows_hold_chain_row_instances():
    model = FluorescenceStatusModel()
    row = FluorescenceChainRow(label="A")
    model.chain_rows = [row]
    model.chain_selection = row
    assert model.chain_rows[0] is row
    assert model.chain_selection is row


# --- PERSISTED_CONTROL_TRAITS ---------------------------------------------------------

def test_persisted_control_traits_is_the_new_single_set():
    assert PERSISTED_CONTROL_TRAITS == [
        "wavelength", "intensity", "frequency", "gain", "exposure",
        "device_viewer_stream", "auto_exposure", "auto_gain",
    ]


def test_auto_flags_round_trip_between_row_and_entry():
    """Per-row auto modes are part of the stored chain value now."""
    row = FluorescenceChainRow(label="A", auto_exposure=True, auto_gain=True)
    d = row.to_entry_dict()
    assert d["auto_exposure"] is True and d["auto_gain"] is True
    back = FluorescenceChainRow.from_entry(ChainEntry(**d))
    assert back.auto_exposure is True and back.auto_gain is True


def test_auto_flags_default_off():
    d = FluorescenceChainRow(label="A").to_entry_dict()
    assert d["auto_exposure"] is False and d["auto_gain"] is False


def test_row_phase_defaults_and_entry_round_trip():
    row = FluorescenceChainRow()
    assert row.capture_start is True
    assert row.capture_end is False

    d = row.to_entry_dict()
    assert d["capture_start"] is True
    assert d["capture_end"] is False

    entry = ChainEntry(**{**d, "label": "x",
                          "capture_start": False, "capture_end": True})
    back = FluorescenceChainRow.from_entry(entry)
    assert back.capture_start is False
    assert back.capture_end is True
