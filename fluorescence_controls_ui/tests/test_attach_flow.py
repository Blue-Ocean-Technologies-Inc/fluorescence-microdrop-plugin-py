# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

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

# Standard library imports.
import types

# Microdrop package imports.
import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.controller import FluorescenceControlsController
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
        controller_mod,
        "protocol_tree_set_cell_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)),
    )
    return calls


def _add_step_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(
        controller_mod,
        "protocol_tree_add_step_publisher",
        types.SimpleNamespace(publish=lambda **kw: calls.append(kw)),
    )
    return calls


# --- plain selection: no free-mode captures in play -----------------------------------


def test_plain_selection_loads_step_chain(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    stored = dump_chain([ChainEntry(**_entry_dict("GFP"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: stored}
    )

    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-1"
    assert [r.label for r in model.chain_rows] == ["GFP"]
    assert set_cell == []  # loading a step never writes back


def test_switching_between_attached_steps_no_dialog(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", _dialog_should_not_be_called)
    controller, model = _controller()
    model.attached_step_id = "step-1"

    msg = ProtocolTreeRowSelectedMessage(step_id="step-2", cells={})
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-2"


# --- deselection restores free mode ---------------------------------------------------


def test_deselection_restores_free_mode():
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.attached_step_id = "step-1"
    model.chain_rows = []  # currently showing an (empty) step's chain

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
    assert model.chain_rows == []  # still free mode, now empty
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


# --- step selection with a free-mode chain: four-way dialog ---------------------------


def test_step_selection_cancel_leaves_free_chain_unattached(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: None)
    set_cell = _set_cell_recorder(monkeypatch)
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []}
    )
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
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []}
    )
    controller._on_tree_row_selected(_event(msg))

    assert len(add_step) == 1
    assert add_step[0]["after_step_id"] == "step-1"
    assert add_step[0]["cells"][FLUORESCENCE_CHAIN_COLUMN_ID][0]["label"] == "A"
    assert model.free_chain == []
    assert model.chain_rows == []  # documented deviation: stays free
    assert model.attached_step_id == ""


def test_step_selection_replace(monkeypatch):
    """The attach's push re-derives the label from the merged (here:
    replaced) position — the free-mode row's authored "A" label is
    overwritten, same as any other push."""
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Replace")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain([ChainEntry(**_entry_dict("Old"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing}
    )
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == ["Blue_460_nm_1"]
    assert model.attached_step_id == "step-1"
    assert model.free_chain == []
    assert len(set_cell) == 1
    assert set_cell[0]["value"][0]["label"] == "Blue_460_nm_1"


def test_step_selection_append_merges_in_order(monkeypatch):
    """Append's push re-derives every label from the merged position —
    the existing step's row lands at position 1, the free-mode row at
    position 2, both as the default wavelength's derived label."""
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Append")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="B")]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain([ChainEntry(**_entry_dict("A"))])
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing}
    )
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == ["Blue_460_nm_1", "Blue_460_nm_2"]
    assert model.attached_step_id == "step-1"
    assert model.free_chain == []
    assert len(set_cell) == 1


def test_step_selection_append_relabels_by_merged_position(monkeypatch):
    """Append no longer suffixes colliding labels on collision — the
    attach's push re-derives every label from its merged chain position,
    so four same-wavelength rows land as ..._1 through ..._4 in merged
    order (existing step rows first, then the free-mode rows)."""
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Append")
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [
        FluorescenceChainRow(label="C"),
        FluorescenceChainRow(label="D"),
    ]
    model.chain_rows = list(model.free_chain)

    existing = dump_chain(
        [ChainEntry(**_entry_dict("A")), ChainEntry(**_entry_dict("B"))]
    )
    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: existing}
    )
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.chain_rows] == [
        "Blue_460_nm_1",
        "Blue_460_nm_2",
        "Blue_460_nm_3",
        "Blue_460_nm_4",
    ]
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
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: stored}
    )
    controller._on_tree_row_selected(_event(msg))

    rows = model.chain_rows
    model.chain_selection = rows[1]

    echo = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(entries)}
    )
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
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(entries)}
    )
    controller._on_tree_row_selected(_event(msg))

    rows = model.chain_rows
    model.chain_selection = rows[1]

    changed = entries + [ChainEntry(**_entry_dict("C"))]
    external = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(changed)}
    )
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
    model.attached_step_id = "step-0"  # NOT free mode right now

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []}
    )
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "step-1"


# --- F1: run-checkbox toggle persists -------------------------------------------------


def test_run_toggle_on_attached_step_pushes_set_cell(monkeypatch):
    """Ticking/unticking the Run column on an ATTACHED step's chain must
    persist via set_cell, exactly like a label edit does — otherwise the
    stored cell goes stale (ticked/total display, #541 capture lock,
    executed-entry set all wrong)."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0 = FluorescenceChainRow(label="A", run=True)
    row1 = FluorescenceChainRow(label="B", run=True)
    model.chain_rows = [row0, row1]
    set_cell.clear()  # drop any publish from the assignment above

    model.chain_rows[1].run = False

    assert len(set_cell) == 1
    assert set_cell[-1]["step_id"] == "step-1"
    assert set_cell[-1]["value"][0]["run"] is True
    assert set_cell[-1]["value"][1]["run"] is False


def test_run_toggle_in_free_mode_does_not_publish_set_cell(monkeypatch):
    """In free mode there is no tree cell to write back to — the toggle
    still needs to sync into `free_chain` (via `_push_chain_to_step`'s
    free-mode branch), but must not fire a set_cell publish."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0 = FluorescenceChainRow(label="A", run=True)
    model.chain_rows = [row0]
    set_cell.clear()

    model.chain_rows[0].run = False

    assert set_cell == []
    assert model.attached_step_id == ""
    assert model.free_chain[0].run is False


# --- F2: mid-run attach dialog must not clear the free-mode chain ---------------------


def test_mid_run_selection_does_not_show_dialog_or_clear_free_chain(monkeypatch):
    """A row-selected message arriving while `protocol_running` is True
    (a user click or nav button during a run) must not pop the attach
    dialog or trigger Append/Replace/New-step (which would clear
    free_chain while Microdrop silently drops the mid-run publish)."""
    monkeypatch.setattr(controller_mod, "choose", _dialog_should_not_be_called)
    set_cell = _set_cell_recorder(monkeypatch)
    add_step = _add_step_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="A")]
    model.chain_rows = list(model.free_chain)
    model.protocol_running = True

    msg = ProtocolTreeRowSelectedMessage(
        step_id="step-1", cells={FLUORESCENCE_CHAIN_COLUMN_ID: []}
    )
    controller._on_tree_row_selected(_event(msg))

    assert [r.label for r in model.free_chain] == ["A"]
    assert set_cell == []
    assert add_step == []


# --- delete: button (selected-else-last), right-click menu, Delete key ----------------


def test_delete_capture_removes_selected_row_and_pushes(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0, row1 = FluorescenceChainRow(label="A"), FluorescenceChainRow(label="B")
    model.chain_rows = [row0, row1]
    model.chain_selection = row0
    set_cell.clear()

    controller.delete_capture()

    # The deletion's push re-derives the surviving row's label from its
    # new (only) position.
    assert [r.label for r in model.chain_rows] == ["Blue_460_nm_1"]
    assert model.chain_selection is None
    assert len(set_cell) == 1
    assert [e["label"] for e in set_cell[-1]["value"]] == ["Blue_460_nm_1"]


def test_delete_capture_without_selection_removes_last_row(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0, row1 = FluorescenceChainRow(label="A"), FluorescenceChainRow(label="B")
    model.chain_rows = [row0, row1]
    model.chain_selection = None

    controller.delete_capture()

    assert [r.label for r in model.chain_rows] == ["Blue_460_nm_1"]


def test_delete_capture_on_empty_chain_is_a_noop(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller.delete_capture()
    assert model.chain_rows == [] and set_cell == []


def test_delete_capture_in_free_mode_syncs_free_chain(monkeypatch):
    """Free-mode deletion has no cell to write; the stash must shrink."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0, row1 = FluorescenceChainRow(label="A"), FluorescenceChainRow(label="B")
    model.chain_rows = [row0, row1]
    model.free_chain = [row0, row1]

    controller.delete_capture()

    assert [r.label for r in model.free_chain] == ["Blue_460_nm_1"]
    assert set_cell == []


def test_delete_chain_row_menu_action_deletes_clicked_row(monkeypatch):
    """The right-click Menu Action dispatches (info, rows) with the
    length-1 clicked-row list — route-table handler parity."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0, row1 = FluorescenceChainRow(label="A"), FluorescenceChainRow(label="B")
    model.chain_rows = [row0, row1]

    controller.delete_chain_row(None, [row0])

    assert [r.label for r in model.chain_rows] == ["Blue_460_nm_1"]


def test_handle_delete_key_only_acts_on_a_selection(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0 = FluorescenceChainRow(label="A")
    model.chain_rows = [row0]
    model.chain_selection = None

    controller.handle_delete_key(None)  # no selection: no-op
    assert [r.label for r in model.chain_rows] == ["A"]

    model.chain_selection = row0
    controller.handle_delete_key(None)
    assert model.chain_rows == []


# --- per-row auto modes ---------------------------------------------------------------


def test_auto_flags_sync_panel_to_selected_row(monkeypatch):
    """The panel's Auto checkboxes are part of the row now: toggling one
    with a row selected saves into the row and pushes the chain."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0 = FluorescenceChainRow(label="A", auto_exposure=False)
    model.chain_rows = [row0]
    model.chain_selection = row0
    set_cell.clear()

    model.auto_exposure = True

    assert row0.auto_exposure is True
    assert set_cell and set_cell[-1]["value"][0]["auto_exposure"] is True


def test_row_click_loads_auto_flags_into_panel(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    row0 = FluorescenceChainRow(label="A", auto_exposure=True, auto_gain=True)
    model.chain_rows = [row0]
    model.auto_exposure = False
    model.auto_gain = False

    model.chain_selection = row0

    assert model.auto_exposure is True and model.auto_gain is True


def test_reorder_of_chain_rows_pushes_chain(monkeypatch):
    """The table is reorderable and chain order IS execution order: an
    in-place reorder (what TableEditor drag does) must persist. Both rows
    share the default wavelength, so the push's relabel derives purely
    from the new position: the row moved to the front becomes ..._1."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0, row1 = FluorescenceChainRow(label="A"), FluorescenceChainRow(label="B")
    model.chain_rows = [row0, row1]
    set_cell.clear()

    model.chain_rows[0:2] = [row1, row0]  # in-place reorder

    assert set_cell
    assert [e["label"] for e in set_cell[-1]["value"]] == [
        "Blue_460_nm_1",
        "Blue_460_nm_2",
    ]


def test_reorder_reindexes_labels(monkeypatch):
    """Reordering doesn't just persist order — the derived label is
    position-based, so a swap of two DIFFERENT-wavelength rows re-derives
    both labels to match their new positions."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0 = FluorescenceChainRow(wavelength=LED_WAVELENGTHS[0])  # Blue
    row1 = FluorescenceChainRow(wavelength=LED_WAVELENGTHS[2])  # Green
    model.chain_rows = [row0, row1]
    set_cell.clear()

    model.chain_rows[0:2] = [row1, row0]  # in-place reorder

    assert row1.label == "Green_540_nm_1"
    assert row0.label == "Blue_460_nm_2"
    assert set_cell


def test_image_tag_edit_updates_derived_label_and_pushes(monkeypatch):
    """A panel Image Tag edit re-saves into the selected row (same as any
    other CHAIN_ROW_PARAM_TRAITS edit) and the resulting push's relabel
    picks it up as the label's prefix."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "step-1"
    row0 = FluorescenceChainRow()
    model.chain_rows = [row0]
    model.chain_selection = row0
    set_cell.clear()

    model.image_tag = "gfp"

    assert row0.image_tag == "gfp"
    assert set_cell
    assert set_cell[-1]["value"][0]["label"] == "gfp_Blue_460_nm_1"


# --- attached-step display context (burst-folder naming) ------------------------------


def test_step_selection_stores_display_context(monkeypatch):
    """The name/id cells of the row_selected broadcast become the pane's
    burst-naming context: description + 1-indexed dotted id (the id cell
    carries the 0-indexed path — tuple in-process, list off the wire)."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1", cells={"name": "Mix", "id": (0, 1)}
            )
        )
    )
    assert model.attached_step_desc == "Mix"
    assert model.attached_step_dotted == "1.2"

    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s2", cells={"name": "Rinse", "id": [2]}
            )
        )
    )  # wire form
    assert model.attached_step_desc == "Rinse"
    assert model.attached_step_dotted == "3"


def test_free_mode_clears_display_context(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1", cells={"name": "Mix", "id": (0,)}
            )
        )
    )
    controller._on_tree_row_selected(
        _event(ProtocolTreeRowSelectedMessage(step_id=None, cells={}))
    )
    assert model.attached_step_desc == ""
    assert model.attached_step_dotted == ""


def test_replace_attach_stores_display_context(monkeypatch):
    _set_cell_recorder(monkeypatch)
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Replace")
    controller, model = _controller()
    model.chain_rows = [FluorescenceChainRow(label="A")]
    model.free_chain = list(model.chain_rows)
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1", cells={"name": "Image Step", "id": (1, 0)}
            )
        )
    )
    assert model.attached_step_desc == "Image Step"
    assert model.attached_step_dotted == "2.1"


# --- stale-echo suppression (the "slider only half-applies" race) ---------------------


def test_stale_echo_within_window_does_not_clobber_local_edits(monkeypatch):
    """Rapid local edits (a slider drag) push per tick while the tree's
    rebroadcasts trail behind; a DIFFERING echo arriving right after a
    local push is a stale self-echo and must not reload (it would revert
    the newer value and drop the row selection)."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1",
                cells={
                    "name": "Mix",
                    "id": (0,),
                    FLUORESCENCE_CHAIN_COLUMN_ID: [_entry_dict("A")],
                },
            )
        )
    )
    rows = model.chain_rows
    model.chain_selection = rows[0]
    model.intensity = 22  # local edit -> push (now)

    stale = dict(rows[0].to_entry_dict(), intensity=30)  # older mid-drag echo
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1",
                cells={
                    "name": "Mix",
                    "id": (0,),
                    FLUORESCENCE_CHAIN_COLUMN_ID: [stale],
                },
            )
        )
    )

    assert model.chain_rows is rows  # not reloaded
    assert model.chain_selection is rows[0]  # selection kept
    assert rows[0].intensity == 22  # local value wins


def test_differing_echo_after_window_reloads(monkeypatch):
    """Outside the self-edit window a differing broadcast is a genuine
    external change (e.g. a protocol file reload) and must reload."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1",
                cells={
                    "name": "Mix",
                    "id": (0,),
                    FLUORESCENCE_CHAIN_COLUMN_ID: [_entry_dict("A")],
                },
            )
        )
    )
    rows = model.chain_rows
    controller._last_local_push = 0.0  # long ago
    changed = dict(rows[0].to_entry_dict(), intensity=77)
    controller._on_tree_row_selected(
        _event(
            ProtocolTreeRowSelectedMessage(
                step_id="s1",
                cells={
                    "name": "Mix",
                    "id": (0,),
                    FLUORESCENCE_CHAIN_COLUMN_ID: [changed],
                },
            )
        )
    )
    assert model.chain_rows is not rows  # reloaded
    assert model.chain_rows[0].intensity == 77


# --- move up/down ---------------------------------------------------------------------


def test_move_capture_swaps_and_relabels_by_position(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.attached_step_id = "s1"
    a = FluorescenceChainRow(wavelength="Blue (460 nm)")
    b = FluorescenceChainRow(wavelength="Green (540 nm)")
    model.chain_rows = [a, b]
    model.chain_selection = b
    set_cell.clear()

    controller.move_capture(-1)

    assert model.chain_rows == [b, a]
    assert model.chain_selection is b
    assert [r.label for r in model.chain_rows] == ["Green_540_nm_1", "Blue_460_nm_2"]
    assert set_cell and [e["label"] for e in set_cell[-1]["value"]] == [
        "Green_540_nm_1",
        "Blue_460_nm_2",
    ]


def test_move_capture_boundary_and_no_selection_are_noops(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    a = FluorescenceChainRow(wavelength="Blue (460 nm)")
    model.chain_rows = [a]
    model.chain_selection = a
    controller.move_capture(-1)  # already first
    assert model.chain_rows == [a]
    model.chain_selection = None
    controller.move_capture(1)  # nothing selected
    assert model.chain_rows == [a]


def test_move_capture_refires_selection_for_the_table_highlight(monkeypatch):
    """The moved row must end on a REAL chain_selection change event —
    the TableEditor re-highlights only on a notification, and a same-
    object reassign is a silent no-change."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    a = FluorescenceChainRow(wavelength="Blue (460 nm)")
    b = FluorescenceChainRow(wavelength="Green (540 nm)")
    model.chain_rows = [a, b]
    model.chain_selection = b
    events = []
    model.observe(lambda e: events.append(e.new), "chain_selection")

    controller.move_capture(-1)

    assert events and events[-1] is b  # a genuine change ended on b
    assert model.chain_selection is b


# --- multi-selection: the chain is written to every selected step ---------------------


def _multi_msg(step_id, selected_step_ids, chain_labels=()):
    """row_selected for current row `step_id` with `selected_step_ids`
    selected; `cells` carry only the current row's chain, as the tree
    sends them."""
    entries = [ChainEntry(**_entry_dict(label)) for label in chain_labels]

    return ProtocolTreeRowSelectedMessage(
        step_id=step_id,
        cells={FLUORESCENCE_CHAIN_COLUMN_ID: dump_chain(entries) or None},
        selected_step_ids=list(selected_step_ids),
    )


def test_multi_selection_attach_on_first_add_writes_each_step(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = _multi_msg("s2", ["s1", "s2", "s3"])
    controller._on_tree_row_selected(_event(msg))

    controller.add_capture()

    assert [c["step_id"] for c in set_cell] == ["s1", "s2", "s3"]
    assert all(c["value"] == set_cell[0]["value"] for c in set_cell)
    assert len(set_cell[0]["value"]) == 1


def test_multi_selection_param_edit_writes_each_step_once(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = _multi_msg("s1", ["s1", "s3"], chain_labels=["A"])
    controller._on_tree_row_selected(_event(msg))
    model.chain_selection = model.chain_rows[0]
    set_cell.clear()

    model.intensity = 77

    assert [c["step_id"] for c in set_cell] == ["s1", "s3"]
    assert all(c["value"][0]["intensity"] == 77 for c in set_cell)


def test_multi_selection_delete_writes_each_step(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = _multi_msg("s1", ["s1", "s2"], chain_labels=["A"])
    controller._on_tree_row_selected(_event(msg))

    controller.delete_capture()

    assert [(c["step_id"], c["value"]) for c in set_cell] == [
        ("s1", None),
        ("s2", None),
    ]


def test_back_to_single_selection_writes_one_step(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(
        _event(_multi_msg("s1", ["s1", "s2", "s3"], chain_labels=["A"]))
    )
    controller._on_tree_row_selected(
        _event(_multi_msg("s2", ["s2"], chain_labels=["B"]))
    )
    model.chain_selection = model.chain_rows[0]
    set_cell.clear()

    model.intensity = 12

    assert [c["step_id"] for c in set_cell] == ["s2"]


def test_multi_selection_loads_the_primary_steps_chain(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = _multi_msg("s3", ["s1", "s2", "s3"], chain_labels=["Primary"])

    controller._on_tree_row_selected(_event(msg))

    assert model.attached_step_id == "s3"
    assert [r.label for r in model.chain_rows] == ["Primary"]
    assert model.target_step_ids == ["s1", "s2", "s3"]


def test_selection_change_with_same_primary_reloads(monkeypatch):
    """Adding a step to the selection is a new selection, not an echo:
    the primary's chain reloads (dropping the row selection) and the
    write targets follow."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(_event(_multi_msg("s1", ["s1"], ["A"])))
    rows = model.chain_rows
    model.chain_selection = rows[0]

    controller._on_tree_row_selected(_event(_multi_msg("s1", ["s1", "s2"], ["A"])))

    assert model.chain_selection is None
    assert model.chain_rows is not rows
    assert model.target_step_ids == ["s1", "s2"]


def test_multi_selection_echo_of_own_edit_keeps_selection(monkeypatch):
    """N writes produce one rebroadcast (for the current row) carrying the
    same selection — skipped like a single-step echo."""
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = _multi_msg("s1", ["s1", "s2"], chain_labels=["A", "B"])
    controller._on_tree_row_selected(_event(msg))
    rows = model.chain_rows
    model.chain_selection = rows[1]

    echo = _multi_msg("s1", ["s1", "s2"], chain_labels=["A", "B"])
    controller._on_tree_row_selected(_event(echo))

    assert model.chain_selection is rows[1]
    assert model.chain_rows is rows


def test_older_core_payload_without_selected_step_ids_targets_one_step(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    msg = ProtocolTreeRowSelectedMessage.deserialize(
        '{"step_id": "s1", "group_id": null, "cells": {}}'
    )
    controller._on_tree_row_selected(_event(msg))

    controller.add_capture()

    assert model.target_step_ids == ["s1"]
    assert [c["step_id"] for c in set_cell] == ["s1"]


def test_deselected_current_row_targets_the_primary_alone(monkeypatch):
    """Ctrl-click can deselect the current row while others stay
    selected; the pane still shows (and so writes only) that row."""
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(_event(_multi_msg("s3", ["s1", "s2"])))

    controller.add_capture()

    assert [c["step_id"] for c in set_cell] == ["s3"]


def test_multi_selection_append_extends_primary_chain_for_all(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Append")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="F")]
    model.chain_rows = list(model.free_chain)

    msg = _multi_msg("s1", ["s1", "s2"], chain_labels=["Old"])
    controller._on_tree_row_selected(_event(msg))

    assert [c["step_id"] for c in set_cell] == ["s1", "s2"]
    assert all(len(c["value"]) == 2 for c in set_cell)
    assert model.free_chain == []


def test_multi_selection_replace_writes_free_chain_to_all(monkeypatch):
    monkeypatch.setattr(controller_mod, "choose", lambda *a, **k: "Replace")
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    model.free_chain = [FluorescenceChainRow(label="F")]
    model.chain_rows = list(model.free_chain)

    msg = _multi_msg("s2", ["s1", "s2", "s3"], chain_labels=["Old"])
    controller._on_tree_row_selected(_event(msg))

    assert [c["step_id"] for c in set_cell] == ["s1", "s2", "s3"]
    assert all(len(c["value"]) == 1 for c in set_cell)


def test_attached_status_text(monkeypatch):
    _set_cell_recorder(monkeypatch)
    controller, model = _controller()

    assert model.attached_status_text == ""

    msg = _multi_msg("s1", ["s1", "s2", "s3"])
    msg.cells["id"] = [0, 1]
    controller._on_tree_row_selected(_event(msg))

    assert model.attached_status_text == "Attached: Step 1.2 (+2 steps)"

    single = _multi_msg("s1", ["s1"])
    single.cells["id"] = [0, 1]
    controller._on_tree_row_selected(_event(single))

    assert model.attached_status_text == "Attached: Step 1.2"

    controller._on_tree_row_selected(_event(ProtocolTreeRowSelectedMessage()))

    assert model.attached_status_text == ""


def test_protocol_step_applied_resets_targets_to_executing_step(monkeypatch):
    set_cell = _set_cell_recorder(monkeypatch)
    controller, model = _controller()
    controller._on_tree_row_selected(_event(_multi_msg("s1", ["s1", "s2"], ["A"])))

    controller._on_protocol_step_applied(
        _event({"step_uuid": "s2", "chain": [], "firing_label": ""})
    )

    assert model.attached_step_id == "s2"
    assert model.target_step_ids == ["s2"]
    assert set_cell == []
