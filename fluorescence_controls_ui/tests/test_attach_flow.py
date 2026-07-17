"""Hardware-free tests for the capture-chain free-mode attach flow
(issue #6): `_on_tree_row_selected` is driven directly with constructed
`ProtocolTreeRowSelectedMessage` objects (the ferry from message_handler.py
through live_state.tree_row_selected is exercised elsewhere — this is the
controller's reaction, dispatch="ui" already assumed).

`controller_mod.choose` / `protocol_tree_set_cell_publisher` /
`protocol_tree_add_step_publisher` are monkeypatched at the controller
module — the existing repo convention (see test_led_controls.py's
`published` fixture).
"""
import types

import pytest

import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_protocol_controls.capture_chain import ChainEntry, dump_chain
from fluorescence_protocol_controls.consts import FLUORESCENCE_CHAIN_COLUMN_ID
from pluggable_protocol_tree.models.cell_sync import (
    ProtocolTreeRowSelectedMessage,
)


def _controller():
    model = FluorescenceStatusModel()
    return FluorescenceControlsController(model=model), model


def _event(msg):
    return types.SimpleNamespace(new=msg)


def _entry_dict(label, wavelength="Blue (460 nm)"):
    return FluorescenceChainRow(label=label, wavelength=wavelength).to_entry_dict()


def _dialog_should_not_be_called(*args, **kwargs):
    raise AssertionError("choose() must not be called here")


def _set_cell_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller_mod, "protocol_tree_set_cell_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)))
    return calls


def _add_step_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller_mod, "protocol_tree_add_step_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)))
    return calls


# --- plain selection: no free-mode captures in play -----------------------------------

def test_plain_selection_loads_step_chain(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    stored = dump_chain([ChainEntry(**_entry_dict("GFP"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: stored})

    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-1"
    assert [r.label for r in model.chain_rows] == ["GFP"]
    assert set_cell == []          # loading a step never writes back


def test_switching_between_attached_steps_no_dialog(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", _dialog_should_not_be_called)
    controller, model = _controller()
    model.attached_step_id = "step-1"

    msg = ProtocolTreeRowSelectedMessage(step_id="step-2", cells={})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-2"


# --- deselection restores free mode ----------------------------------------------------

def test_deselection_restores_free_mode():
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.attached_step_id = "step-1"
    model.chain_rows = []          # currently showing an (empty) step's chain

    msg = ProtocolTreeRowSelectedMessage(step_id=None, group_id=None, cells={})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == ""
    assert [r.label for r in model.chain_rows] == ["A"]


# --- group selection ------------------------------------------------------------------

def test_group_selection_with_no_free_chain_enters_free_mode(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", _dialog_should_not_be_called)
    controller, model = _controller()

    msg = ProtocolTreeRowSelectedMessage(group_id="grp-1", cells={})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == ""


def test_group_selection_with_free_chain_offers_new_step_only(monkeypatch):
    seen = {}

    def fake_choose(parent, message, title=None, choices=(), **kw):
        seen["choices"] = list(choices)
        return "New step"

    monkeypatch.setattr(controller_mod, "choose", fake_choose)
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    msg = ProtocolTreeRowSelectedMessage(group_id="grp-1", cells={})
    controller._on_tree_row_selected(_event(msg))

    assert seen["choices"] == ["New step"]
    assert len(add_step) == 1
    assert add_step[0]["group_id"] == "grp-1"
    assert add_step[0]["cells"][FLUORESCENCE_CHAIN_COLUMN_ID][0]["label"] == "A"
    assert model.free_chain == []
    assert model.chain_rows == []          # still free mode, now empty
    assert model.attached_step_id == ""


def test_group_selection_cancel_leaves_free_chain_intact(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: None)
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    msg = ProtocolTreeRowSelectedMessage(group_id="grp-1", cells={})
    controller._on_tree_row_selected(_event(msg))

    assert add_step == []
    assert [r.label for r in model.free_chain] == ["A"]
    assert [r.label for r in model.chain_rows] == ["A"]
    assert model.attached_step_id == ""


# --- step selection with a free-mode chain: four-way dialog ----------------------------

def test_step_selection_cancel_leaves_free_chain_unattached(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: None)
    set_cell = _set_cell_recorder(monkeypatch)
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == ""
    assert set_cell == []
    assert add_step == []
    assert [r.label for r in model.free_chain] == ["A"]
    assert [r.label for r in model.chain_rows] == ["A"]


def test_step_selection_new_step(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "New step")
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []})
    controller._on_tree_row_selected(_event(msg))

    assert len(add_step) == 1
    assert add_step[0]["after_step_id"] == "step-1"
    assert add_step[0]["cells"][FLUORESCENCE_CHAIN_COLUMN_ID][0]["label"] == "A"
    assert model.free_chain == []
    assert model.chain_rows == []          # documented deviation: stays free
    assert model.attached_step_id == ""


def test_step_selection_replace(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Replace")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain([ChainEntry(**_entry_dict("Old"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing})
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == ["A"]
    assert model.attached_step_id == "step-1"
    assert model.free_chain == []
    assert len(set_cell) == 1
    assert set_cell[0]["value"][0]["label"] == "A"


def test_step_selection_append_merges_in_order(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Append")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="B")]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain([ChainEntry(**_entry_dict("A"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing})
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == ["A", "B"]
    assert model.attached_step_id == "step-1"
    assert model.free_chain == []
    assert len(set_cell) == 1


def test_step_selection_append_suffixes_colliding_labels(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Append")
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="GFP")]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain([ChainEntry(**_entry_dict("GFP"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing})
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == ["GFP", "GFP_2"]
    assert model.attached_step_id == "step-1"


def test_row_selected_echo_of_own_edit_keeps_selection(monkeypatch):
    """A panel edit on the attached row publishes set_cell; the tree
    applies it and rebroadcasts PROTOCOL_TREE_ROW_SELECTED for the still-
    selected step (cell-edit rebroadcast). That echo carries the exact
    chain already in `chain_rows` and must not disturb the selection."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    entries = [ChainEntry(**_entry_dict("A")), ChainEntry(**_entry_dict("B"))]
    stored = dump_chain(entries)
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: stored})
    controller._on_tree_row_selected(_event(msg))

    rows = model.chain_rows
    model.chain_selection = rows[1]

    echo = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(entries)})
    controller._on_tree_row_selected(_event(echo))

    assert model.chain_selection is rows[1]
    assert model.chain_rows is rows
    assert list(model.chain_rows) == list(rows)


def test_row_selected_same_step_with_external_change_reloads(monkeypatch):
    """A genuinely different chain for the same step (not our own edit's
    echo) must still reload."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    entries = [ChainEntry(**_entry_dict("A")), ChainEntry(**_entry_dict("B"))]
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1",
        cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(entries)})
    controller._on_tree_row_selected(_event(msg))

    rows = model.chain_rows
    model.chain_selection = rows[1]

    changed = entries + [ChainEntry(**_entry_dict("C"))]
    external = ProtocolTreeRowSelectedMessage(
        step_id="step-1",
        cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(changed)})
    controller._on_tree_row_selected(_event(external))

    assert model.chain_selection is None
    assert [r.label for r in model.chain_rows] == ["A", "B", "C"]
    assert model.chain_rows is not rows


def test_dialog_only_shown_when_free_mode_currently_active(monkeypatch):
    """`free` is computed from `attached_step_id == ""` — a non-empty
    `free_chain` stash left over from an earlier session must not trigger
    the dialog while the pane is currently viewing an attached step."""
    monkeypatch.setattr(controller_mod, "choose", _dialog_should_not_be_called)
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="stale")]
    model.attached_step_id = "step-0"          # NOT free mode right now

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-1"
