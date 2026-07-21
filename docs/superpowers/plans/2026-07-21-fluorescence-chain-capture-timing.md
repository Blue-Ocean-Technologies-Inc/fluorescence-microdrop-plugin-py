# Fluorescence Chain Capture Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each capture-chain row fire at protocol step start, step end, or both, chosen via two Start/End toggle buttons in the LED/Camera params pane.

**Architecture:** Two booleans (`capture_start`, `capture_end`) flow through the existing chain value contract: `ChainEntry` (pydantic, stored on the protocol row) ↔ `FluorescenceChainRow` (TraitsUI table row) ↔ `FluorescenceStatusModel` panel traits (the panel doubles as the selected row's editor). `FluorescenceChainHandler` splits its burst loop into a shared helper called from `on_pre_step` (start entries) and a new `on_post_step` (end entries), using the same executor hooks the regular capture column uses.

**Tech Stack:** Python 3.11, pydantic v2, Traits/TraitsUI, pytest. Repo: `microdrop-py/src/fluorescence-microdrop-plugin-py` (work on branch `feat/6-capture-chain`).

**Spec:** `docs/superpowers/specs/2026-07-21-fluorescence-chain-capture-timing-design.md`

## Global Constraints

- **Do NOT run pytest.** The user runs tests manually. Every task writes tests; "verify" steps are the user's job. Never chain a commit behind a test run.
- Defaults are exactly `capture_start=True`, `capture_end=False` — legacy chains (dicts without the keys) must behave exactly as today (step-start only).
- Both-False is coerced to `capture_start=True` at the model layer; the UI separately prevents switching off the last-on toggle via `enabled_when`.
- Manual Run Capture / Capture Selected buttons ignore the timing fields.
- Unchanged: handler priority 5, `wait_for_topics=[FLUORESCENCE_APPLIED]`, the #541 capture-cell lock, `on_post_protocol_end` → `ALL_LEDS_OFF`, `capture_service` internals, filenames.
- Follow `microdrop-conventions` (f-strings, no new constants when existing ones suffice, no cross-plugin references).
- Commit messages: Conventional Commits, imperative ~50-char subject, end body with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- All paths below are relative to `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py\src\fluorescence-microdrop-plugin-py`.

---

### Task 1: `ChainEntry` phase fields + both-False coercion

**Files:**
- Modify: `fluorescence_protocol_controls/capture_chain.py` (ChainEntry, lines 24-55)
- Test: `fluorescence_protocol_controls/tests/test_capture_chain.py`

**Interfaces:**
- Produces: `ChainEntry.capture_start: bool = True`, `ChainEntry.capture_end: bool = False`. Both serialized by the existing `dump_chain` / accepted by `parse_chain` with no changes to those functions (pydantic defaults + the model validator do the work). Tasks 2 and 4 rely on these exact field names.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_protocol_controls/tests/test_capture_chain.py` (reuse the module's existing `_entry` helper, which passes `**overrides` through to `ChainEntry`):

```python
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
```

- [ ] **Step 2: Implement.** In `fluorescence_protocol_controls/capture_chain.py`:

Extend the pydantic import (line 10):

```python
from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_validator,
)
```

Add to `ChainEntry`, after `image_tag: str = ""` (line 44):

```python
    # Protocol phase(s) this entry fires in (the executor's on_pre_step /
    # on_post_step — the same hooks the regular capture column picks
    # between; this entry may fire in both). At least one is always on:
    # both-False input is coerced to the step-start default rather than
    # rejected, so a hand-edited protocol file still loads.
    capture_start: bool = True
    capture_end: bool = False

    @model_validator(mode="after")
    def _at_least_one_phase(self):
        if not (self.capture_start or self.capture_end):
            self.capture_start = True
        return self
```

(`parse_chain` / `dump_chain` need no changes: missing keys hit the field defaults, `model_dump` emits the new fields.)

- [ ] **Step 3: Commit**

```bash
git add fluorescence_protocol_controls/capture_chain.py fluorescence_protocol_controls/tests/test_capture_chain.py
git commit -m "feat(capture-chain): per-entry capture_start/capture_end phases"
```

---

### Task 2: Row + panel model + controller binding

**Files:**
- Modify: `fluorescence_controls_ui/chain_model.py` (FluorescenceChainRow)
- Modify: `fluorescence_controls_ui/model.py` (FluorescenceStatusModel, near the auto flags at lines 69-78)
- Modify: `fluorescence_controls_ui/controller.py` (CHAIN_ROW_PARAM_TRAITS line 37-39, `_load_selected_row` line 265, `add_capture` line 420)
- Test: `fluorescence_controls_ui/tests/test_chain_model.py`

**Interfaces:**
- Consumes: Task 1's `ChainEntry.capture_start` / `.capture_end`.
- Produces: `FluorescenceChainRow.capture_start/capture_end` Bool traits carried by `to_entry_dict()` / `from_entry()`; `FluorescenceStatusModel.capture_start/capture_end` Bool traits (Task 3's view binds these by name). Panel↔row sync and Add-button snapshot happen automatically once the trait names are in `CHAIN_ROW_PARAM_TRAITS`.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_controls_ui/tests/test_chain_model.py` (match the module's existing row-construction style; if it has a row factory helper, use it):

```python
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
```

(Import `ChainEntry` from `fluorescence_protocol_controls.capture_chain` and `FluorescenceChainRow` from `fluorescence_controls_ui.chain_model` if the module does not already.)

- [ ] **Step 2: Implement the row.** In `fluorescence_controls_ui/chain_model.py`:

Add after `image_tag = Str("")` (line 37):

```python
    # Protocol phase(s) this row fires in (mirrors ChainEntry; the panel's
    # Start/End toggles edit these via the live binding).
    capture_start = Bool(True)
    capture_end = Bool(False)
```

In `to_entry_dict()` add to the returned dict (after `"image_tag": self.image_tag,`):

```python
            "capture_start": self.capture_start,
            "capture_end": self.capture_end,
```

In `from_entry()` add to the `cls(...)` call (after `image_tag=entry.image_tag,`):

```python
            capture_start=entry.capture_start,
            capture_end=entry.capture_end,
```

- [ ] **Step 3: Implement the panel model.** In `fluorescence_controls_ui/model.py`, `FluorescenceStatusModel`, after `image_tag = Str("")` (line 78):

```python
    # Protocol phase(s) a capture fires in (per-row, edited via the panel
    # like every other param): step start, step end, or both. The view's
    # enabled_when guards keep at least one on.
    capture_start = Bool(True)
    capture_end = Bool(False)
```

(`Bool` is already imported in model.py; verify, and add it to the traits import if not.)

- [ ] **Step 4: Wire the controller.** In `fluorescence_controls_ui/controller.py`:

Extend `CHAIN_ROW_PARAM_TRAITS` (line 37-39) — this alone makes the existing `_sync_panel_to_selected_row` observer save toggle edits into the selected row and push the chain:

```python
CHAIN_ROW_PARAM_TRAITS = (
    "image_tag", "wavelength", "intensity", "frequency", "exposure", "gain",
    "auto_exposure", "auto_gain", "capture_start", "capture_end")
```

In `_load_selected_row` (line 265), add right after `self.model.image_tag = row.image_tag` (before the auto flags — the phase fields drive nothing live, so order among the early loads is free; `wavelength` must stay last):

```python
            self.model.capture_start = row.capture_start
            self.model.capture_end = row.capture_end
```

In `add_capture` (line 420), extend the `FluorescenceChainRow(...)` construction:

```python
        row = FluorescenceChainRow(
            image_tag=self.model.image_tag,
            wavelength=self.model.wavelength,
            intensity=self.model.intensity, frequency=self.model.frequency,
            exposure=self.model.exposure, gain=self.model.gain,
            auto_exposure=self.model.auto_exposure,
            auto_gain=self.model.auto_gain,
            capture_start=self.model.capture_start,
            capture_end=self.model.capture_end)
```

- [ ] **Step 5: Commit**

```bash
git add fluorescence_controls_ui/chain_model.py fluorescence_controls_ui/model.py fluorescence_controls_ui/controller.py fluorescence_controls_ui/tests/test_chain_model.py
git commit -m "feat(controls-ui): carry capture phase fields through panel/row"
```

---

### Task 3: Start/End toggle line in the params pane

**Files:**
- Modify: `fluorescence_controls_ui/view.py` (`params_group`, lines 56-76)
- Test: `fluorescence_controls_ui/tests/test_view_shape.py`

**Interfaces:**
- Consumes: Task 2's `FluorescenceStatusModel.capture_start/capture_end` trait names (the TraitsUI view context resolves `Item`/`enabled_when` names against the model).

- [ ] **Step 1: Write the failing test** — append to `fluorescence_controls_ui/tests/test_view_shape.py` (the module already defines `_all_item_names()`):

```python
def test_capture_phase_toggles_present_with_last_one_on_guards():
    names = _all_item_names()
    assert "capture_start" in names
    assert "capture_end" in names


def test_capture_phase_toggles_cannot_switch_off_the_last_phase():
    """Each toggle disables exactly when it is the sole phase on, so it
    can always be turned on but never switched off last."""
    from fluorescence_controls_ui.view import params_group

    def _find(node, name):
        from traitsui.api import Group, Item
        if isinstance(node, Item) and node.name == name:
            return node
        if isinstance(node, Group):
            for child in node.content:
                found = _find(child, name)
                if found is not None:
                    return found
        return None

    start = _find(params_group, "capture_start")
    end = _find(params_group, "capture_end")
    assert start.enabled_when == "capture_end or not capture_start"
    assert end.enabled_when == "capture_start or not capture_end"
```

- [ ] **Step 2: Implement.** In `fluorescence_controls_ui/view.py`, inside `params_group` (line 56), add after the gain `HGroup` (lines 70-73) and before `visible_when="show_params"`:

```python
    # Protocol phase(s) the selected/added chain row captures in. Both may
    # be on (capture twice per step); each toggle disables while it is the
    # sole phase on, so at least one is always on. Timing only governs
    # protocol runs — the manual Run Capture buttons ignore it.
    HGroup(
        Label("Protocol Step Time of Capture:"),
        UItem("capture_start",
              editor=InPlaceToggleEditor(on_label="Start", off_label="Start"),
              enabled_when="capture_end or not capture_start"),
        UItem("capture_end",
              editor=InPlaceToggleEditor(on_label="End", off_label="End"),
              enabled_when="capture_start or not capture_end"),
    ),
```

(`HGroup`, `UItem`, `Label`, and `InPlaceToggleEditor` are already imported in view.py.)

- [ ] **Step 3: Commit**

```bash
git add fluorescence_controls_ui/view.py fluorescence_controls_ui/tests/test_view_shape.py
git commit -m "feat(controls-ui): Start/End capture-time toggles in params pane"
```

---

### Task 4: Handler phase split (`on_pre_step` / `on_post_step`)

**Files:**
- Modify: `fluorescence_protocol_controls/protocol_columns/chain_column.py` (`FluorescenceChainHandler`, lines 114-166)
- Test: `fluorescence_protocol_controls/tests/test_chain_execution.py`

**Interfaces:**
- Consumes: Task 1's `ChainEntry.capture_start/capture_end`; the executor's existing `on_post_step(row, ctx)` hook (already a no-op on `BaseColumnHandler`, `pluggable_protocol_tree/models/column.py:128`).
- Produces: nothing downstream; this is the terminal consumer.

- [ ] **Step 1: Write the failing tests** — append to `fluorescence_protocol_controls/tests/test_chain_execution.py` (reuse the module's `_entry`, `_Ctx`, `row_type`, `fake_capture_service`, `publisher_calls` fixtures; note `_entry(label, run=True)` passes only those two — extend it to forward extra kwargs first):

Replace the module's `_entry` helper (line 37-38) with:

```python
def _entry(label, run=True, **overrides):
    return ChainEntry(label=label, run=run, **{**ENTRY_KW, **overrides})
```

Then append:

```python
# --- capture_start / capture_end phase routing --------------------------

def test_pre_step_runs_only_start_entries_post_step_only_end_entries(
        row_type, fake_capture_service, publisher_calls):
    Row, col = row_type
    row = Row()
    row.name = "Step A"
    entries = [
        _entry("start_only"),
        _entry("end_only", capture_start=False, capture_end=True),
        _entry("both", capture_start=True, capture_end=True),
        _entry("parked", run=False, capture_start=True, capture_end=True),
    ]
    col.model.set_value(row, [e.model_dump() for e in entries])

    handler = FluorescenceChainHandler()

    ctx = _Ctx()
    handler.on_pre_step(row, ctx)
    assert [e.label for e in fake_capture_service["apply"]] \
        == ["start_only", "both"]

    handler.on_post_step(row, ctx)
    assert [e.label for e in fake_capture_service["apply"]] \
        == ["start_only", "both", "end_only", "both"]


def test_post_step_with_no_end_entries_is_a_noop(
        row_type, fake_capture_service, publisher_calls):
    Row, col = row_type
    row = Row()
    col.model.set_value(row, [_entry("start_only").model_dump()])

    ctx = _Ctx()
    FluorescenceChainHandler().on_post_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []


def test_legacy_entries_without_phase_keys_run_at_pre_step_only(
        row_type, fake_capture_service, publisher_calls):
    Row, col = row_type
    row = Row()
    raw = _entry("legacy").model_dump()
    del raw["capture_start"], raw["capture_end"]
    col.model.set_value(row, [raw])

    handler = FluorescenceChainHandler()
    ctx = _Ctx()
    handler.on_pre_step(row, ctx)
    handler.on_post_step(row, ctx)

    assert [e.label for e in fake_capture_service["apply"]] == ["legacy"]
    assert len(fake_capture_service["burst_folder"]) == 1


def test_post_step_preview_mode_is_a_noop(row_type, fake_capture_service,
                                          publisher_calls):
    Row, col = row_type
    row = Row()
    col.model.set_value(row, [
        _entry("end_only", capture_start=False, capture_end=True)
        .model_dump()])

    ctx = _Ctx(preview_mode=True)
    FluorescenceChainHandler().on_post_step(row, ctx)

    assert fake_capture_service["burst_folder"] == []
    assert publisher_calls == []
    assert ctx.wait_for_calls == []
```

- [ ] **Step 2: Implement.** In `fluorescence_protocol_controls/protocol_columns/chain_column.py`, replace `FluorescenceChainHandler.on_pre_step` (lines 124-155) with the split below. The docstring's burst mechanics move to `_run_entries`; each phase filters the ticked entries by its flag. A row on both phases bursts twice — once per phase, each into its own timestamped folder (`burst_folder` is called per phase, matching the one-folder-per-burst contract).

```python
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
```

Also update the class docstring (lines 115-119) to mention both phases:

```python
    """Priority 5 — one bucket EARLIER than capture/record/video (10),
    so the LED + camera state is applied and settled before a Step
    Start capture fires; the same ordering holds in the step-end
    bucket. Each ticked entry declares its phase(s) via
    `capture_start` / `capture_end` and may fire in both. See the old
    FluorescenceStepHandler (fluorescence_column.py, deleted) for the
    ack-wait rationale this mirrors."""
```

- [ ] **Step 3: Commit**

```bash
git add fluorescence_protocol_controls/protocol_columns/chain_column.py fluorescence_protocol_controls/tests/test_chain_execution.py
git commit -m "feat(chain-column): fire entries at step start, end, or both"
```

---

## Verification (user-run)

- `pixi run python -m pytest src/fluorescence-microdrop-plugin-py` (or the user's preferred invocation) — new tests in `test_capture_chain.py`, `test_chain_model.py`, `test_view_shape.py`, `test_chain_execution.py`.
- Manual smoke: select a chain row → toggles reflect it; try to switch off the only-on toggle (must be disabled); add rows with Start/End/both; run a protocol step and confirm captures land at the chosen phases; legacy protocol file still captures at step start.
