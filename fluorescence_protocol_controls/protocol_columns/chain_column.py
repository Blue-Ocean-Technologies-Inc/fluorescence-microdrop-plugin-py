"""Fluorescence capture-chain column — per-step list of named LED/camera
captures (issue #6). Replaces the old br/fl compound column
(fluorescence_on / fluorescence_settings): a plain Column, not a
compound, whose stored value is a list of `ChainEntry` dicts (or None).

The pane (fluorescence_controls_ui) owns authoring the chain and writes
it to the row's cell via PROTOCOL_TREE_SET_CELL; this column is display
+ execution + the #541 capture-cell lock (a chain that runs owns this
step's imaging, so the shared "capture" cell is locked out — one writer
per step).

At run time (Task 7) the handler loops the ticked entries: set LED,
wait for the backend's applied-and-settled ack, grab a frame from the
plugin's own camera feed. Priority 5 — one bucket EARLIER than
capture/record/video (10), matching the old compound column's ordering.
"""
from traits.api import Any, List, Str

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger
from microdrop_application.dialogs import pyface_wrapper
from pyface.gui import GUI
from pyface.qt.QtCore import QTimer

from fluorescence_controller.consts import ALL_LEDS_OFF, FLUORESCENCE_APPLIED
from fluorescence_controls_ui.live_state import fluorescence_live_state
from pluggable_protocol_tree.models.column import (
    BaseColumnHandler, BaseColumnModel, Column,
)
from pluggable_protocol_tree.views.columns.base import BaseColumnView

from ..capture_chain import parse_chain, ticked
from ..consts import FLUORESCENCE_CHAIN_COLUMN_ID

logger = get_logger(__name__)

#: Once-per-session guard for the first-time "capture is now locked"
#: dialog (module state, not per-row — the operator only needs telling
#: once, not once per chained step).
_capture_locked_warned = False


def _warn_capture_locked_once():
    """Tell the operator, once per session, that a chained step's
    screen-capture cell is now locked out. Deferred with
    QTimer.singleShot(0, ...) — this fires from a model write that may
    itself be running inside a TraitsUI cell-editor commit handler, and
    opening a modal dialog synchronously from there crashes Qt."""
    global _capture_locked_warned
    if _capture_locked_warned:
        return
    _capture_locked_warned = True
    QTimer.singleShot(0, lambda: pyface_wrapper.information(
        None,
        "This step's screen-capture is disabled while its Fluorescence "
        "chain owns this step's imaging.",
        title="Capture Disabled",
    ))


class FluorescenceChainColumnModel(BaseColumnModel):
    """The stored value is a list of ChainEntry dicts (or None/[]); the
    JSON-native list survives serialize/deserialize identity."""

    def trait_for_row(self):
        return Any(self.default_value)

    def set_value(self, row, value):
        super().set_value(row, value)
        self._sync_capture_lock(row)

    def on_row_loaded(self, row):
        # Persistence sets cell values with setattr; rebuild the
        # runtime-derived lock from the loaded chain (issue #541 —
        # locks are never persisted).
        self._sync_capture_lock(row)

    def _sync_capture_lock(self, row):
        entries = ticked(parse_chain(getattr(row, self.col_id, None)))
        if entries:
            had_capture = bool(getattr(row, "capture", False))
            row.lock_column("capture", owner="fluorescence",
                            reason=f"Fluorescence chain ({len(entries)} "
                                   f"capture{'s' if len(entries) != 1 else ''}) "
                                   f"owns this step's imaging")
            if had_capture:
                _warn_capture_locked_once()
        else:
            row.unlock_column("capture", owner="fluorescence")


class FluorescenceChainColumnView(BaseColumnView):
    """Read-only summary: ticked count, or ticked/total when some
    entries are parked (run=False)."""

    #: The pane writes the chain via PROTOCOL_TREE_SET_CELL (bypassing
    #: setData), so declare the dependency for the tree model's per-row
    #: repaint wiring.
    depends_on_row_traits = List(Str, value=[FLUORESCENCE_CHAIN_COLUMN_ID])

    def format_display(self, value, row):
        entries = parse_chain(value)
        if not entries:
            return ""
        t, n = len(ticked(entries)), len(entries)
        return str(n) if t == n else f"{t}/{n}"

    def create_editor(self, parent, context):
        return None   # display-only; the pane owns authoring the chain


class FluorescenceChainHandler(BaseColumnHandler):
    """Priority 5 — one bucket EARLIER than capture/record/video (10),
    so the LED + camera state is applied and settled before a Step
    Start capture fires. See the old FluorescenceStepHandler
    (fluorescence_column.py, deleted) for the ack-wait rationale this
    mirrors."""
    priority = 5
    wait_for_topics = [FLUORESCENCE_APPLIED]
    default_ack_time_s = 5.0

    def on_pre_step(self, row, ctx):
        # The per-entry burst execution loop lands in Task 7.
        pass

    def on_post_protocol_end(self, ctx):
        """Lights out at the end of every run — unconditional, because the
        operator may have entered the run with the light on manually, or
        every step's chain may leave the light off (neither case leaves
        a run-time trace, and a lit LED must never outlive the run).
        Preview runs have no hardware side effects to clean up. Moved
        verbatim from the deleted FluorescenceStepHandler."""
        if getattr(ctx, "preview_mode", False):
            return
        publish_message(topic=ALL_LEDS_OFF, message="")
        # Partial snapshot: the pane's light toggle mirrors the off.
        GUI.invoke_later(setattr, fluorescence_live_state,
                         "protocol_step_settings_applied",
                         {"light_on": False})


def make_fluorescence_chain_column():
    """Factory — a fresh fluorescence capture-chain column."""
    return Column(
        model=FluorescenceChainColumnModel(
            col_id=FLUORESCENCE_CHAIN_COLUMN_ID, col_name="Fluorescence"),
        view=FluorescenceChainColumnView(),
        handler=FluorescenceChainHandler(),
    )
