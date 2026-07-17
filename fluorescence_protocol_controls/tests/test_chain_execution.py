"""Hardware-free tests for `FluorescenceChainHandler.on_pre_step` (issue
#6, Task 7): the per-entry burst execution loop — apply camera settings,
publish the LED state, wait for the executor's own applied ack, save the
capture — for each ticked entry in chain order, inside one folder built
once per step. No real camera/backend anywhere: `capture_service` is
faked wholesale (it is imported lazily inside `on_pre_step`, mirroring
`controller.run_capture`'s pattern), and the publisher + `ctx.wait_for`
are recorded fakes.
"""
import sys

import pytest

import fluorescence_controls_ui
from fluorescence_controller.consts import FLUORESCENCE_APPLIED
from fluorescence_protocol_controls.capture_chain import ChainEntry
from fluorescence_protocol_controls.consts import LED_STABILIZATION_S
from fluorescence_protocol_controls.protocol_columns import (
    chain_column as column_module,
)
from fluorescence_protocol_controls.protocol_columns.chain_column import (
    FluorescenceChainHandler,
)
from microdrop_utils import dramatiq_pub_sub_helpers
from pluggable_protocol_tree.models.row import BaseRow, build_row_type

from fluorescence_protocol_controls.protocol_columns.chain_column import (
    make_fluorescence_chain_column,
)

ENTRY_KW = dict(wavelength="Blue (460 nm)", intensity=50, frequency=40000,
                exposure_ms=10.0, gain=0)

FAKE_FOLDER = "FAKE_FOLDER"


def _entry(label, run=True):
    return ChainEntry(label=label, run=run, **ENTRY_KW)


@pytest.fixture
def row_type():
    col = make_fluorescence_chain_column()
    return build_row_type([col], base=BaseRow), col


class _Protocol:
    """Fake ProtocolContext: the real `preview_mode` lives here, not on
    the StepContext (see `_Ctx`)."""

    def __init__(self, preview_mode=False):
        self.preview_mode = preview_mode


class _Ctx:
    """Fake executor context, shaped like the real `StepContext`: it has
    NO `preview_mode` of its own (that lives on `ctx.protocol` — a
    `ProtocolContext`), only `wait_for` and a `.protocol` back-reference.
    Records `wait_for` calls, raises whatever `next_error` is queued for
    the current call (or nothing)."""

    def __init__(self, preview_mode=False, errors=None):
        self.protocol = _Protocol(preview_mode=preview_mode)
        self.wait_for_calls = []
        self._errors = list(errors or [])

    def wait_for(self, topic, timeout):
        self.wait_for_calls.append((topic, timeout))
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error


@pytest.fixture
def fake_capture_service(monkeypatch):
    """Installs a recorder in place of the lazily-imported
    `fluorescence_controls_ui.capture_service`.

    The handler imports it via `from fluorescence_controls_ui import
    capture_service` (mirroring `controller.run_capture`). CPython's
    IMPORT_FROM resolves that via `getattr(package, "capture_service")`
    FIRST, only falling back to `sys.modules` on AttributeError (see
    test_capture_service.py's `_capture_service_module` fixture for the
    same lesson) — so a real prior import elsewhere in the suite could
    leave the package attribute bound to the REAL module, silently
    shadowing a `sys.modules`-only fake. Patch both, via `monkeypatch`
    (with `raising=False` so teardown deletes the attribute again if it
    did not exist before), so the fake is picked up regardless of import
    history and nothing leaks to later tests.
    """
    calls = {"apply": [], "burst_folder": [], "save": []}

    def apply_camera_settings(entry):
        calls["apply"].append(entry)

    def burst_folder(step_desc=None, dotted_id=None, step_id=None):
        calls["burst_folder"].append(
            dict(step_desc=step_desc, dotted_id=dotted_id, step_id=step_id))
        return FAKE_FOLDER

    def save_entry_capture(entry, folder):
        calls["save"].append((entry, folder))

    fake = type(sys)("fluorescence_controls_ui.capture_service")
    fake.apply_camera_settings = apply_camera_settings
    fake.burst_folder = burst_folder
    fake.save_entry_capture = save_entry_capture

    monkeypatch.setitem(
        sys.modules, "fluorescence_controls_ui.capture_service", fake)
    monkeypatch.setattr(
        fluorescence_controls_ui, "capture_service", fake, raising=False)
    return calls


@pytest.fixture
def published(monkeypatch):
    calls = []

    def record(message, topic, **kw):
        calls.append((topic, message))

    monkeypatch.setattr(column_module, "publish_message", record)
    monkeypatch.setattr(dramatiq_pub_sub_helpers, "publish_message", record)
    return calls


@pytest.fixture
def publisher_calls(monkeypatch):
    calls = []

    def fake_publish(**kw):
        calls.append(kw)

    monkeypatch.setattr(
        column_module.protocol_set_fluorescence_publisher, "publish",
        fake_publish)
    return calls


def test_fake_capture_service_actually_intercepts_the_lazy_import(
        fake_capture_service):
    # Proves the monkeypatch mechanism works BEFORE relying on it below:
    # exactly what on_pre_step's lazy import statement would resolve to.
    from fluorescence_controls_ui import capture_service
    assert capture_service is sys.modules[
        "fluorescence_controls_ui.capture_service"]
    assert capture_service.burst_folder() == FAKE_FOLDER


def test_two_ticked_entries_run_in_order_one_folder(
        row_type, fake_capture_service, publisher_calls):
    Row, col = row_type
    row = Row()
    row.name = "Step A"
    entries = [_entry("a"), _entry("b", run=False), _entry("c")]
    value = [e.model_dump() for e in entries]
    col.model.set_value(row, value)

    ctx = _Ctx()
    FluorescenceChainHandler().on_pre_step(row, ctx)

    assert len(fake_capture_service["burst_folder"]) == 1
    assert fake_capture_service["burst_folder"][0] == dict(
        step_desc="Step A", dotted_id=row.dotted_path(), step_id=None)

    assert [e.label for e in fake_capture_service["apply"]] == ["a", "c"]

    assert len(publisher_calls) == 2
    assert publisher_calls[0] == dict(
        light_on=True, led=entries[0].led_index, duty=entries[0].intensity,
        frequency=entries[0].frequency, settle_s=LED_STABILIZATION_S)
    assert publisher_calls[1] == dict(
        light_on=True, led=entries[2].led_index, duty=entries[2].intensity,
        frequency=entries[2].frequency, settle_s=LED_STABILIZATION_S)

    assert ctx.wait_for_calls == [
        (FLUORESCENCE_APPLIED, 5.0), (FLUORESCENCE_APPLIED, 5.0)]

    assert [(e.label, folder) for e, folder in fake_capture_service["save"]] \
        == [("a", FAKE_FOLDER), ("c", FAKE_FOLDER)]


def test_preview_mode_is_a_noop(row_type, fake_capture_service,
                                publisher_calls):
    Row, col = row_type
    row = Row()
    col.model.set_value(row, [e.model_dump() for e in [_entry("a")]])

    ctx = _Ctx(preview_mode=True)
    FluorescenceChainHandler().on_pre_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert fake_capture_service["apply"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []


def test_preview_mode_reads_from_ctx_protocol_not_ctx_itself(
        row_type, fake_capture_service, publisher_calls):
    """Regression pin: `on_pre_step` receives a `StepContext`, which has
    NO `preview_mode` of its own — the real flag lives on
    `ctx.protocol` (a `ProtocolContext`). A ctx object that lacks its
    own `preview_mode` attribute but carries `protocol.preview_mode =
    True` must still be treated as a preview no-op. Before the fix,
    `getattr(ctx, "preview_mode", False)` silently fell through to
    `False` here, and a preview run would fire real LED commands and
    captures."""
    Row, col = row_type
    row = Row()
    col.model.set_value(row, [e.model_dump() for e in [_entry("a")]])

    class _StepCtxNoOwnPreviewMode:
        def __init__(self, protocol):
            self.protocol = protocol
            self.wait_for_calls = []

        def wait_for(self, topic, timeout):
            self.wait_for_calls.append((topic, timeout))

    assert not hasattr(_StepCtxNoOwnPreviewMode, "preview_mode")
    ctx = _StepCtxNoOwnPreviewMode(_Protocol(preview_mode=True))
    assert not hasattr(ctx, "preview_mode")

    FluorescenceChainHandler().on_pre_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert fake_capture_service["apply"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []


def test_empty_chain_is_a_noop(row_type, fake_capture_service,
                               publisher_calls):
    Row, col = row_type
    row = Row()

    ctx = _Ctx()
    FluorescenceChainHandler().on_pre_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []


def test_all_unticked_chain_is_a_noop(row_type, fake_capture_service,
                                      publisher_calls):
    Row, col = row_type
    row = Row()
    col.model.set_value(
        row, [e.model_dump() for e in [_entry("a", run=False)]])

    ctx = _Ctx()
    FluorescenceChainHandler().on_pre_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []


def test_wait_for_timeout_propagates_and_aborts_the_loop(
        row_type, fake_capture_service, publisher_calls):
    Row, col = row_type
    row = Row()
    entries = [_entry("a"), _entry("b")]
    col.model.set_value(row, [e.model_dump() for e in entries])

    ctx = _Ctx(errors=[TimeoutError("no ack")])
    with pytest.raises(TimeoutError, match="no ack"):
        FluorescenceChainHandler().on_pre_step(row, ctx)

    # First entry's LED was applied and published, but the ack never
    # came: its save must not happen, and the second entry never starts.
    assert [e.label for e in fake_capture_service["apply"]] == ["a"]
    assert len(publisher_calls) == 1
    assert fake_capture_service["save"] == []
    assert ctx.wait_for_calls == [(FLUORESCENCE_APPLIED, 5.0)]
