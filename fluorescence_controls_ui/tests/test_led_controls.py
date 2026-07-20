"""Hardware-free tests for the LED controls (frontend side).

Reworked for the single param set (issue #6, no more br/fl/dual mode
split): the light toggle drives ONE LED set, live edits publish only
while the stream is on, the light is on, and idle, and wavelength
switches are ONE exclusive set_led request (the backend runs the legacy
off->on sequence atomically). `publish_message` is monkeypatched at the
controller module.

Also covers the panel<->chain-row live binding (row click loads the row
into the panel and drives the LED; a panel edit re-saves into the
selected row and pushes the chain), Add (labels DERIVED from
image_tag/wavelength/position on push, never authored), and Run
Capture's lazy `capture_service` import (Task 6's module, which does not
exist yet).
"""
import json
import sys
import types

import pytest
from apptools.preferences.api import Preferences

import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences
from fluorescence_controller.consts import (
    SET_LED, SET_LED_FREQUENCY, ALL_LEDS_OFF, LED_WAVELENGTHS,
)


@pytest.fixture
def published(monkeypatch):
    sink = []
    monkeypatch.setattr(
        controller_mod, "publish_message",
        lambda message, topic=None, **k: sink.append((topic, json.loads(message))),
    )
    return sink


def _controller():
    # In-memory preferences (test_control_persistence.py's convention):
    # the model's preferences default to the process-wide "microdrop.
    # peripheral_settings" node, which would otherwise leak wavelength/
    # intensity/etc. edits across tests (and even across pytest runs).
    model = FluorescenceStatusModel(
        preferences=FluorescencePreferences(preferences=Preferences()))
    return FluorescenceControlsController(model=model), model


def _live_controller():
    """A controller/model pair with the stream already on (the master
    gate live edits need to publish)."""
    controller, model = _controller()
    model.stream_active = True
    return controller, model


# --- defaults ---------------------------------------------------------------------

def test_defaults_match_standalone_config():
    _, model = _controller()
    assert not hasattr(model, "mode")
    assert model.light_on is False
    assert model.wavelength == LED_WAVELENGTHS[0]
    assert (model.intensity, model.frequency) == (50, 40000)
    assert model.led_index == 0


# --- master light toggle ------------------------------------------------------------

def test_light_on_drives_the_led(published):
    controller, model = _live_controller()
    published.clear()          # drop the stream-start SET_LED_FREQUENCY
    model.light_on = True
    assert published == [(SET_LED, {"led": 0, "duty": 50})]


def test_light_off_is_all_leds_off(published):
    controller, model = _live_controller()
    model.light_on = True
    published.clear()
    model.light_on = False
    assert published == [(ALL_LEDS_OFF, {})]


def test_light_on_stages_while_stream_off(published):
    controller, model = _controller()
    warned = []
    model.observe(lambda event: warned.append(True), "stream_off_edit_warning")
    model.light_on = True
    assert published == []
    assert warned          # user warned the edit is staged


# --- live edits gate on stream + light + idle ----------------------------------------

def test_intensity_edit_publishes_live_when_lit(published):
    controller, model = _live_controller()
    model.light_on = True
    published.clear()
    model.intensity = 55
    assert published == [(SET_LED, {"led": 0, "duty": 55})]


def test_intensity_edit_staged_while_light_off(published):
    controller, model = _live_controller()
    published.clear()          # drop the stream-start SET_LED_FREQUENCY
    model.intensity = 55
    assert published == []


def test_intensity_edit_staged_while_stream_off(published):
    controller, model = _controller()
    model.intensity = 55
    assert published == []


def test_frequency_edit_publishes_live(published):
    controller, model = _live_controller()
    model.light_on = True
    published.clear()
    model.frequency = 500
    assert published == [(SET_LED_FREQUENCY, {"led": 0, "frequency": 500})]


def test_live_edits_gated_off_during_protocol_run(published):
    controller, model = _live_controller()
    model.light_on = True
    model.protocol_running = True
    published.clear()
    model.intensity = 60
    model.frequency = 700
    assert published == []


# --- wavelength switch = ONE exclusive request ----------------------------------------

def test_wavelength_switch_is_single_exclusive_request(published):
    controller, model = _live_controller()
    model.light_on = True
    published.clear()
    model.wavelength = LED_WAVELENGTHS[4]      # Red (630 nm)
    assert published == [(SET_LED, {"led": 4, "duty": 50, "exclusive": True})]


def test_wavelength_switch_staged_while_off(published):
    controller, model = _controller()
    model.wavelength = LED_WAVELENGTHS[1]
    assert published == []


# --- board identity -----------------------------------------------------------------

def test_board_id_signal_fills_board_readout():
    from fluorescence_controls_ui.message_handler import FluorescenceMessageHandler
    model = FluorescenceStatusModel()
    handler = FluorescenceMessageHandler(model=model, name="fluorescence_controls_ui_listener")
    handler._on_board_id_triggered(json.dumps(
        {"uid": "a1b2c3d4", "device_id": "fluo_board"}))
    assert model.board_id_text == "fluo_board"


# --- chain ops: Add -----------------------------------------------------------------

def test_add_capture_appends_row_from_panel_values():
    controller, model = _controller()
    model.image_tag = "GFP"
    model.wavelength = LED_WAVELENGTHS[2]
    model.intensity = 75
    model.auto_exposure = True
    model.auto_gain = True
    controller.add_capture()
    assert len(model.chain_rows) == 1
    row = model.chain_rows[0]
    assert row.image_tag == "GFP"
    assert row.wavelength == LED_WAVELENGTHS[2]
    assert row.intensity == 75
    assert row.auto_exposure is True
    assert row.auto_gain is True
    # add_capture's push derives the label from tag/wavelength/position.
    assert row.label == "GFP_Green_540_nm_1"
    assert model.chain_selection is row


def test_add_capture_defaults_label_from_wavelength():
    controller, model = _controller()
    controller.add_capture()
    assert model.chain_rows[0].label == "Blue_460_nm_1"


def test_add_capture_uniquifies_colliding_labels():
    """Two adds of the same wavelength no longer collide-suffix — each
    push re-derives the label from the row's chain position."""
    controller, model = _controller()
    controller.add_capture()
    controller.add_capture()
    assert [r.label for r in model.chain_rows] == [
        "Blue_460_nm_1", "Blue_460_nm_2"]


def test_add_capture_in_free_mode_stashes_into_free_chain():
    controller, model = _controller()
    controller.add_capture()
    assert model.attached_step_id == ""
    assert [r.label for r in model.free_chain] == [
        r.label for r in model.chain_rows]


def test_add_capture_while_attached_pushes_set_cell(monkeypatch):
    from fluorescence_protocol_controls.consts import FLUORESCENCE_CHAIN_COLUMN_ID
    calls = []
    monkeypatch.setattr(
        controller_mod, "protocol_tree_set_cell_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)))
    controller, model = _controller()
    model.attached_step_id = "step-1"
    controller.add_capture()
    assert len(calls) == 1
    assert calls[0]["step_id"] == "step-1"
    assert calls[0]["col_id"] == FLUORESCENCE_CHAIN_COLUMN_ID
    assert len(calls[0]["value"]) == 1
    assert calls[0]["value"][0]["label"] == model.chain_rows[0].label


# --- panel <-> chain-row live binding ---------------------------------------------------

def test_row_selection_loads_panel_and_drives_led(published):
    controller, model = _live_controller()
    row = FluorescenceChainRow(
        image_tag="Cy5", wavelength=LED_WAVELENGTHS[3], intensity=80,
        frequency=1234, exposure=5.0, gain=10)
    model.chain_rows = [row]
    model.light_on = True
    published.clear()

    model.chain_selection = row

    assert model.image_tag == "Cy5"
    assert model.wavelength == LED_WAVELENGTHS[3]
    assert model.intensity == 80
    # The row's already-updated duty rides the exclusive wavelength publish.
    assert (SET_LED, {"led": 3, "duty": 80, "exclusive": True}) in published


def test_panel_edit_writes_back_into_selected_row_and_pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller_mod, "protocol_tree_set_cell_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)))
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row = FluorescenceChainRow(label="A")
    model.chain_rows = [row]
    model.chain_selection = row
    calls.clear()

    model.intensity = 42

    assert row.intensity == 42
    assert len(calls) == 1


def test_panel_edit_without_selection_does_not_touch_any_row():
    controller, model = _controller()
    row = FluorescenceChainRow(label="A", intensity=10)
    model.chain_rows = [row]
    model.intensity = 99
    assert row.intensity == 10


# --- Run Capture: lazy capture_service import --------------------------------------------

class _SyncThread:
    """Runs the target synchronously — keeps the Run Capture tests
    deterministic without real threading."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture
def sync_thread(monkeypatch):
    monkeypatch.setattr(
        controller_mod, "threading",
        types.SimpleNamespace(Thread=_SyncThread))


@pytest.fixture
def fake_capture_service(monkeypatch):
    module = types.ModuleType("fluorescence_controls_ui.capture_service")
    calls = []

    def run_burst(entries, *, step_desc=None, dotted_id=None):
        calls.append({"entries": entries, "step_desc": step_desc,
                      "dotted_id": dotted_id})

    module.run_burst = run_burst
    monkeypatch.setitem(
        sys.modules, "fluorescence_controls_ui.capture_service", module)
    return calls


def test_run_capture_calls_run_burst_on_ticked_entries(sync_thread, fake_capture_service):
    controller, model = _controller()
    model.chain_rows = [
        FluorescenceChainRow(label="A", run=True),
        FluorescenceChainRow(label="B", run=False),
    ]
    controller.run_capture()
    assert len(fake_capture_service) == 1
    assert [e.label for e in fake_capture_service[0]["entries"]] == ["A"]
    assert fake_capture_service[0]["step_desc"] is None      # free mode
    assert fake_capture_service[0]["dotted_id"] is None


def test_run_capture_noop_when_no_ticked_entries(fake_capture_service):
    controller, model = _controller()
    model.chain_rows = [FluorescenceChainRow(label="A", run=False)]
    controller.run_capture()
    assert fake_capture_service == []


def test_run_capture_disabled_during_protocol_run(fake_capture_service):
    controller, model = _controller()
    model.chain_rows = [FluorescenceChainRow(label="A", run=True)]
    model.protocol_running = True
    controller.run_capture()
    assert fake_capture_service == []


def test_run_capture_on_attached_step_passes_desc_and_dotted(
        sync_thread, fake_capture_service):
    """Attached bursts are named like protocol-run bursts: the step's
    description + 1-indexed dotted id (from row_selected's name/id
    cells), never the uuid."""
    controller, model = _controller()
    model.attached_step_id = "some-uuid"
    model.attached_step_desc = "Mix"
    model.attached_step_dotted = "1.2"
    model.chain_rows = [FluorescenceChainRow(label="A", run=True)]
    controller.run_capture()
    assert fake_capture_service[0]["step_desc"] == "Mix"
    assert fake_capture_service[0]["dotted_id"] == "1.2"
