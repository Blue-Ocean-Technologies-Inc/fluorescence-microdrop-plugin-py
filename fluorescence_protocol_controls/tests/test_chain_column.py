"""Hardware-free tests for the `fluorescence_chain` protocol column: the
display formula, the #541 capture-cell lock (set_value + on_row_loaded),
the once-per-session first-time dialog, the factory wiring, and the
handler's on_post_protocol_end (moved verbatim from the deleted compound
column)."""
import json

import pytest

from fluorescence_controller.consts import ALL_LEDS_OFF, FLUORESCENCE_APPLIED
from fluorescence_protocol_controls.capture_chain import ChainEntry
from fluorescence_protocol_controls.consts import FLUORESCENCE_CHAIN_COLUMN_ID
from fluorescence_protocol_controls.protocol_columns import (
    chain_column as column_module,
)
from fluorescence_protocol_controls.protocol_columns.chain_column import (
    FluorescenceChainColumnView, FluorescenceChainHandler,
    make_fluorescence_chain_column,
)
from microdrop_utils import dramatiq_pub_sub_helpers
from pluggable_protocol_tree.models.row import BaseRow, build_row_type


ENTRY_KW = dict(wavelength="Blue (460 nm)", intensity=50, frequency=40000,
                exposure_ms=10.0, gain=0)


def _entry(label, run=True):
    return ChainEntry(label=label, run=run, **ENTRY_KW)


@pytest.fixture
def row_type():
    col = make_fluorescence_chain_column()
    return build_row_type([col], base=BaseRow), col


@pytest.fixture(autouse=True)
def _reset_warned_once():
    # The once-per-session dialog flag is module state; isolate tests.
    column_module._capture_locked_warned = False
    yield
    column_module._capture_locked_warned = False


# --- display -----------------------------------------------------------

def test_display_empty_or_none_is_blank():
    view = FluorescenceChainColumnView()
    assert view.format_display(None, None) == ""
    assert view.format_display([], None) == ""


def test_display_all_ticked_shows_count():
    view = FluorescenceChainColumnView()
    value = [e.model_dump() for e in
             [_entry("a"), _entry("b"), _entry("c")]]
    assert view.format_display(value, None) == "3"


def test_display_partial_ticked_shows_fraction():
    view = FluorescenceChainColumnView()
    value = [e.model_dump() for e in
             [_entry("a"), _entry("b", run=False),
              _entry("c"), _entry("d", run=False)]]
    assert view.format_display(value, None) == "2/4"


def test_depends_on_row_traits():
    view = FluorescenceChainColumnView()
    assert list(view.depends_on_row_traits) == [FLUORESCENCE_CHAIN_COLUMN_ID]


def test_view_is_read_only():
    view = FluorescenceChainColumnView()
    assert view.create_editor(None, None) is None


# --- capture-cell locking (#541 consumer) -------------------------------

def test_set_value_with_ticked_chain_locks_capture(row_type):
    Row, col = row_type
    row = Row()
    value = [e.model_dump() for e in [_entry("a"), _entry("b")]]
    col.model.set_value(row, value)
    assert row.is_column_locked("capture") is True
    reasons = row.column_lock_reasons("capture")
    assert len(reasons) == 1
    assert "2 captures" in reasons[0]


def test_set_value_with_single_ticked_entry_reason_is_singular(row_type):
    Row, col = row_type
    row = Row()
    value = [e.model_dump() for e in [_entry("a")]]
    col.model.set_value(row, value)
    assert "1 capture" in row.column_lock_reasons("capture")[0]
    assert "1 captures" not in row.column_lock_reasons("capture")[0]


def test_set_value_all_unrun_unlocks_capture(row_type):
    Row, col = row_type
    row = Row()
    value = [e.model_dump() for e in
             [_entry("a", run=False), _entry("b", run=False)]]
    col.model.set_value(row, value)
    assert row.is_column_locked("capture") is False


def test_set_value_empty_chain_unlocks_capture(row_type):
    Row, col = row_type
    row = Row()
    # First lock it via a ticked chain, then clear it.
    col.model.set_value(row, [_entry("a").model_dump()])
    assert row.is_column_locked("capture") is True
    col.model.set_value(row, [])
    assert row.is_column_locked("capture") is False


def test_on_row_loaded_rebuilds_lock_from_raw_setattr(row_type):
    Row, col = row_type
    row = Row()
    # Persistence sets cell values with a raw setattr — no set_value hook.
    setattr(row, FLUORESCENCE_CHAIN_COLUMN_ID,
            [_entry("a").model_dump(), _entry("b").model_dump()])
    assert row.is_column_locked("capture") is False   # not yet rebuilt

    col.model.on_row_loaded(row)
    assert row.is_column_locked("capture") is True
    assert "2 captures" in row.column_lock_reasons("capture")[0]


# --- first-time capture-locked dialog (deferred, once per session) -----

def test_warn_fires_only_when_row_already_had_capture(row_type, monkeypatch):
    Row, col = row_type
    calls = []
    monkeypatch.setattr(column_module.QTimer, "singleShot",
                        lambda ms, fn: calls.append((ms, fn)))

    row_no_capture = Row()
    col.model.set_value(row_no_capture, [_entry("a").model_dump()])
    assert calls == []

    row_had_capture = Row()
    row_had_capture.capture = True
    col.model.set_value(row_had_capture, [_entry("a").model_dump()])
    assert len(calls) == 1
    assert calls[0][0] == 0


def test_warn_fires_only_once_across_two_calls(row_type, monkeypatch):
    Row, col = row_type
    calls = []
    monkeypatch.setattr(column_module.QTimer, "singleShot",
                        lambda ms, fn: calls.append((ms, fn)))

    row1 = Row()
    row1.capture = True
    col.model.set_value(row1, [_entry("a").model_dump()])

    row2 = Row()
    row2.capture = True
    col.model.set_value(row2, [_entry("b").model_dump()])

    assert len(calls) == 1


# --- factory wiring ------------------------------------------------------

def test_factory_wires_chain_column():
    column = make_fluorescence_chain_column()
    assert column.model.col_id == FLUORESCENCE_CHAIN_COLUMN_ID
    assert column.model.col_name == "Fluorescence"
    assert isinstance(column.view, FluorescenceChainColumnView)
    assert isinstance(column.handler, FluorescenceChainHandler)
    assert column.handler.priority == 5
    assert column.handler.wait_for_topics == [FLUORESCENCE_APPLIED]
    assert column.handler.default_ack_time_s == 5.0


# --- handler: on_post_protocol_end (moved verbatim) ---------------------

@pytest.fixture
def published(monkeypatch):
    calls = []

    def record(message, topic, **kw):
        calls.append((topic, message))

    monkeypatch.setattr(column_module, "publish_message", record)
    monkeypatch.setattr(dramatiq_pub_sub_helpers, "publish_message", record)
    monkeypatch.setattr(column_module.GUI, "invoke_later",
                        lambda func, *args, **kw: func(*args, **kw))
    return calls


def test_run_end_always_turns_lights_off_and_mirrors_pane(published):
    from fluorescence_controls_ui.live_state import fluorescence_live_state
    reflected = []

    def capture(event):
        reflected.append(event.new)

    fluorescence_live_state.observe(capture, "protocol_step_settings_applied")
    try:
        FluorescenceChainHandler().on_post_protocol_end(object())
        assert [topic for topic, _ in published] == [ALL_LEDS_OFF]
        assert reflected == [{"light_on": False}]
    finally:
        fluorescence_live_state.observe(
            capture, "protocol_step_settings_applied", remove=True)


def test_run_end_preview_mode_publishes_nothing(published):
    class _Ctx:
        preview_mode = True

    FluorescenceChainHandler().on_post_protocol_end(_Ctx())
    assert published == []


def test_on_pre_step_bare_row_is_a_noop():
    # A row without the chain trait (here a bare `object()`) hits the
    # empty-chain guard: `getattr(row, FLUORESCENCE_CHAIN_COLUMN_ID,
    # None)` is None, so on_pre_step returns before it ever fires
    # anything. `ctx` still needs the real StepContext shape (a
    # `.protocol` back-reference carrying `preview_mode`) since that is
    # checked first. Execution behavior (chain firing, preview-mode
    # gating, etc.) is covered in test_chain_execution.py.
    class _Protocol:
        preview_mode = False

    class _Ctx:
        protocol = _Protocol()

    FluorescenceChainHandler().on_pre_step(object(), _Ctx())
