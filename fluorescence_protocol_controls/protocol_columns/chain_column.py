"""Fluorescence capture-chain column — per-step list of named LED/camera
captures (issue #6). Replaces the old br/fl compound column (the
on/off checkbox + settings-snapshot pair, retired in v1.0.0): a plain
Column, not a compound, whose stored value is a list of `ChainEntry`
dicts (or None).

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
from pyface.qt.QtCore import QTimer

from fluorescence_controller.consts import ALL_LEDS_OFF, FLUORESCENCE_APPLIED
from fluorescence_controller.datamodels import (
    protocol_set_fluorescence_publisher,
)
from pluggable_protocol_tree.models.column import (
    BaseColumnHandler, BaseColumnModel, Column,
)
from pluggable_protocol_tree.views.columns.base import BaseColumnView

from ..capture_chain import parse_chain, ticked
from ..consts import FLUORESCENCE_CHAIN_COLUMN_ID, LED_STABILIZATION_S

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
    Start capture fires; the same ordering holds in the step-end
    bucket. Each ticked entry declares its phase(s) via
    `capture_start` / `capture_end` and may fire in both. See the old
    FluorescenceStepHandler (fluorescence_column.py, deleted) for the
    ack-wait rationale this mirrors."""
    priority = 5
    wait_for_topics = [FLUORESCENCE_APPLIED]
    default_ack_time_s = 5.0

    def on_pre_step(self, row, ctx):
        """Step-start phase: fire the ticked entries with
        `capture_start=True` (every legacy entry — the field defaults on)."""
        self._run_phase(row, ctx, lambda e: e.capture_start)

    def on_post_step(self, row, ctx):
        """Step-end phase: fire the ticked entries with
        `capture_end=True`. An entry may fire in both phases."""
        self._run_phase(row, ctx, lambda e: e.capture_end)

    def _run_phase(self, row, ctx, phase_filter):
        """Fire this step's ticked entries passing ``phase_filter``, in
        order, into one folder per phase: apply camera settings, publish
        the LED state, block on the EXECUTOR's own applied-ack mailbox
        (`ctx.wait_for` — not capture_service's Event, which is for
        pane-driven bursts only), then save the frame. Any raise
        (TimeoutError from the wait, RuntimeError from the save)
        propagates uncaught: the step fails and its ack is withheld
        (existing backend error contract,
        `fluorescence_command_setter_service.py:57`, unchanged).

        `capture_service` is imported lazily here (mirrors
        `controller.run_capture`'s pattern) so this column stays
        importable without the camera stack, and stays mockable in
        tests."""
        if getattr(ctx.protocol, "preview_mode", False):
            return
        entries = [e for e in ticked(parse_chain(
            getattr(row, FLUORESCENCE_CHAIN_COLUMN_ID, None)))
            if phase_filter(e)]
        if not entries:
            return

        from fluorescence_controls_ui import capture_service

        folder = capture_service.burst_folder(
            step_desc=row.name, dotted_id=row.dotted_path())
        for entry in entries:
            capture_service.apply_camera_settings(entry)
            protocol_set_fluorescence_publisher.publish(
                light_on=True, led=entry.led_index, duty=entry.intensity,
                frequency=entry.frequency, settle_s=LED_STABILIZATION_S)
            ctx.wait_for(FLUORESCENCE_APPLIED, timeout=self.ack_time_s)
            capture_service.save_entry_capture(entry, folder)

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


def make_fluorescence_chain_column():
    """Factory — a fresh fluorescence capture-chain column."""
    return Column(
        model=FluorescenceChainColumnModel(
            col_id=FLUORESCENCE_CHAIN_COLUMN_ID, col_name="Fluorescence"),
        view=FluorescenceChainColumnView(),
        handler=FluorescenceChainHandler(),
    )
