# Fluorescence Capture Chain (issue #6, major 1.0.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the br/fl/dual mode gate with a single param panel plus a per-step chain of named captures, per the approved design `docs/superpowers/specs/2026-07-16-fluorescence-capture-chain-design.md` and GitHub issue #6.

**Architecture:** The chain is a plain list-of-dicts stored in a NEW protocol column (`fluorescence_chain`); the pane live-tracks the selected step via `PROTOCOL_TREE_ROW_SELECTED` and writes back via `PROTOCOL_TREE_SET_CELL` (both existing Microdrop contracts built for exactly this). Free-mode chains attach via the `choose()` four-way dialog (#542) and, for "New step", the new `PROTOCOL_TREE_ADD_STEP` topic. The chain column locks the shared `capture` cell via #541 locks (rebuilt on load via the new `on_row_loaded` hook). Execution loops ticked entries: set LED → `ctx.wait_for(FLUORESCENCE_APPLIED)` → grab a fresh raw frame from the plugin's own ASI feed → save into one folder per burst.

**Tech Stack:** Traits/TraitsUI, Pydantic v2, PySide6 via pyface.qt, pytest (hardware-free, monkeypatched `publish_message` — repo convention).

## Global Constraints

- **Repo:** the NESTED git repo `C:\Users\Info\PycharmProjects\pixi-microdrop\microdrop-py\src\fluorescence-microdrop-plugin-py`. All git commands run with THAT as cwd. Branch `feat/6-capture-chain` from `main`. First commit: the untracked `docs/` (design spec + this plan) as `docs: add capture-chain design + implementation plan`.
- **Depends on Microdrop state:** the submodule working tree must be on `integration/541-542` WITH the `feat/ppt-fluorescence-support-topics` branch merged in (locks, `choose()`, `PROTOCOL_TREE_ADD_STEP`, `group_id` on row_selected, `on_row_loaded`). Verify before Task 1: `git -C .. log --oneline -1` shows the integration head and `python -c "from pluggable_protocol_tree.consts import PROTOCOL_TREE_ADD_STEP"` (via pixi, cwd=src) succeeds. STOP and report if not.
- **Tests:** hardware-free, no conftest, monkeypatch `publish_message` on the module under test (existing convention). Invocation: `cd "C:/Users/Info/PycharmProjects/pixi-microdrop/microdrop-py" && QT_QPA_PLATFORM=offscreen pixi run bash -c "cd src && python -m pytest 'fluorescence-microdrop-plugin-py/<path>' -q"`. FIRST verify this form by running the existing `fluorescence_protocol_controls/tests/test_fluorescence_column.py` once; if imports fail, try `cd src/fluorescence-microdrop-plugin-py && python -m pytest <path> -q` and use whichever passes for all subsequent runs. Targeted files only; never a full suite.
- Conventional Commits; commit per task; NEVER push, NEVER open a PR without user approval.
- f-strings only; dialogs ONLY via `microdrop_application.dialogs.pyface_wrapper` (`choose`, `information`); model classes stay Qt-free (MVC rule); model mutated only on the GUI thread.
- Voltage/frequency style rule: `intensity` (%), `frequency` (Hz), `gain` are Int end-to-end; `exposure` is ms (float display) in the pane, µs (int) at `asi_camera_settings`.
- Exact existing values to preserve: `LED_WAVELENGTHS` 6-tuple (`fluorescence_controller/consts.py:37-40`), `LED_STABILIZATION_S = 0.2`, `FLUORESCENCE_APPLIED = "Fluorescence/signals/fluorescence_applied"`, publisher `protocol_set_fluorescence_publisher.publish(*, light_on, led, duty, frequency, settle_s)`, `CAPTURES_DIR_NAME = "captures"`, `RAW_CAPTURES_SUBDIR = "16bit_raw"` (device_viewer.consts).
- Version bump to **1.0.0** happens ONLY in Task 9, in BOTH `[project]` and `[tool.pixi.package]` of `pyproject.toml`.
- Old ids retire: the `fluorescence` compound base id, `fluorescence_on`, `fluorescence_settings` must not survive anywhere (Task 9 greps them out). NEVER reuse `fluorescence_settings` as the new column id.

---

### Task 1: Chain value contract (`capture_chain.py`)

**Files:**
- Create: `fluorescence_protocol_controls/capture_chain.py`
- Modify: `fluorescence_protocol_controls/consts.py` (add new id; old ids stay until Task 9)
- Test: `fluorescence_protocol_controls/tests/test_capture_chain.py`

**Interfaces (everything later tasks call):**
- `FLUORESCENCE_CHAIN_COLUMN_ID = "fluorescence_chain"` (consts.py)
- `ChainEntry(BaseModel)`: `label: str`, `wavelength: str` (must be in `LED_WAVELENGTHS`), `intensity: int` (0-100), `frequency: int` (20-100000), `exposure_ms: float` (1-60000), `gain: int` (0-600), `run: bool = True`; `led_index` property (`LED_WAVELENGTHS.index(self.wavelength)`).
- `parse_chain(value) -> list[ChainEntry]` — tolerant: `None`/`[]` → `[]`; entries failing validation are skipped with a warning (stale files never crash a load).
- `dump_chain(entries: list[ChainEntry]) -> list[dict]` — `[e.model_dump() for e in entries]`.
- `ticked(entries) -> list[ChainEntry]` — `[e for e in entries if e.run]`.
- `sanitize_label(label: str) -> str` — keep alnum + space/dash/underscore, then spaces → `_` (the existing device_viewer scheme); empty result → `"capture"`.
- `unique_label(label: str, existing: set[str]) -> str` — returns `label` or `label_2`, `label_3`, … (first free suffix).

- [ ] **Step 1: Write the failing tests** — `test_capture_chain.py`: round-trip `parse_chain(dump_chain(...))`; `parse_chain(None) == []`; invalid entry (bad wavelength / negative intensity) skipped while valid siblings survive; `ticked` filters; `sanitize_label("GFP #1 (a)") == "GFP_1_a"`; `unique_label("GFP", {"GFP", "GFP_2"}) == "GFP_3"`; `unique_label("GFP", set()) == "GFP"`; `ChainEntry(...).led_index` matches `LED_WAVELENGTHS.index`. Bounds enforced by pydantic `Field(ge=..., le=...)` — assert one `ValidationError`.
- [ ] **Step 2: Run to verify failure** (ImportError).
- [ ] **Step 3: Implement** exactly the interface above. Use pydantic v2 (`model_dump`, `field_validator` for wavelength membership), `ConfigDict(extra="ignore")` so future keys load, module `logger = get_logger(__name__)` warning per skipped entry. Bounds via the imported consts (`LED_DUTY_MIN/MAX`, `LED_FREQUENCY_MIN/MAX`, `EXPOSURE_MS_MIN/MAX` from `fluorescence_controls_ui.consts`, `ASI_GAIN_MIN/MAX` from `fluorescence_controls_ui.cameras.consts`) — never literal copies.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** `feat(protocol): capture-chain value contract` (body: what the chain is; why tolerant parsing).

### Task 2: The `fluorescence_chain` protocol column (replaces the compound)

**Files:**
- Create: `fluorescence_protocol_controls/protocol_columns/chain_column.py`
- Delete: `fluorescence_protocol_controls/protocol_columns/fluorescence_column.py`, `fluorescence_protocol_controls/step_settings.py`
- Modify: `fluorescence_protocol_controls/plugin.py`
- Test: `fluorescence_protocol_controls/tests/test_chain_column.py` (new); delete `tests/test_fluorescence_column.py`

**Interfaces:**
- `make_fluorescence_chain_column() -> Column` (plain `Column`, NOT compound): model `FluorescenceChainColumnModel(BaseColumnModel)` with `col_id=FLUORESCENCE_CHAIN_COLUMN_ID, col_name="Fluorescence"`, `trait_for_row() -> Any(None)`; view `FluorescenceChainColumnView(BaseColumnView)` read-only (`create_editor -> None`), `depends_on_row_traits = List(Str, value=[FLUORESCENCE_CHAIN_COLUMN_ID])`; handler `FluorescenceChainHandler` — in THIS task only the class shell with `priority = 5`, `wait_for_topics = [FLUORESCENCE_APPLIED]`, `default_ack_time_s = 5.0` and a no-op `on_pre_step` marked for Task 7.
- Display: `""` when chain empty/None; `f"{t}/{n}"` when ticked ≠ total; `str(n)` when equal.
- **Capture-cell locking (the #541 consumer):** model overrides

```python
    def set_value(self, row, value):
        super().set_value(row, value)
        self._sync_capture_lock(row)

    def on_row_loaded(self, row):
        # persistence sets cell values with setattr; rebuild the
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
```

  with `_warn_capture_locked_once()` a module function: once per session (module-level bool), defer the modal out of the current handler with `QTimer.singleShot(0, ...)` (TraitsUI/commit-handler crash trap) showing `pyface_wrapper.information(...)` explaining the step's screen-capture is disabled while the chain owns imaging.
- `plugin.py`: `contributed_protocol_columns = List(Instance(IColumn), contributes_to=PROTOCOL_COLUMNS)` (import `IColumn` from `pluggable_protocol_tree.interfaces.i_column`) returning `[make_fluorescence_chain_column()]`.

- [ ] **Step 1: Write the failing tests** — `test_chain_column.py` (mirror the deleted file's conventions: `_Row` fakes are NOT enough here — locking needs a real `BaseRow`; use `build_row_type([col], base=BaseRow)`):
  - display: `format_display(None,row)==""`, 3 ticked of 3 → `"3"`, 2 of 4 → `"2/4"`.
  - `depends_on_row_traits == [FLUORESCENCE_CHAIN_COLUMN_ID]`.
  - `set_value` with a ticked chain locks `capture` (owner-keyed: `row.is_column_locked("capture")`); with all `run=False` or `[]` unlocks; reason mentions the count.
  - `on_row_loaded` after a raw `setattr` rebuilds the lock.
  - factory wiring: col_id/col_name/handler priority/wait_for_topics/default_ack_time_s.
  - monkeypatch `chain_column.QTimer.singleShot` to a recorder; assert the once-flag fires the deferred dialog only when the row already had `capture=True`, and only once across two calls.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement**; delete the two old files; rewrite `plugin.py`'s default. Keep `on_post_protocol_end` publishing `ALL_LEDS_OFF` exactly as the old handler did (move it verbatim onto `FluorescenceChainHandler`, including the preview guard and the `fluorescence_live_state.protocol_step_settings_applied = {"light_on": False}` mirror — trim that mirror to just the dict it still needs after Task 3's model rework; if live_state's consumer is gone by then, Task 9 sweeps it).
- [ ] **Step 4: Run to verify pass** (new file; plus `python -c "import fluorescence_protocol_controls.plugin"` smoke via pixi).
- [ ] **Step 5: Commit** `feat(protocol)!: fluorescence_chain column replaces br/fl compound` (body: new id rationale — old ids retire so old protocols can't half-load; capture lock = one writer per step; BREAKING CHANGE footer).

### Task 3: Panel model — single param set + chain state

**Files:**
- Modify: `fluorescence_controls_ui/model.py`, `fluorescence_controls_ui/consts.py`, `fluorescence_controls_ui/preferences.py`
- Create: `fluorescence_controls_ui/chain_model.py`
- Test: `fluorescence_controls_ui/tests/test_chain_model.py` (new) + update `tests/test_control_persistence.py`

**Interfaces:**
- `chain_model.FluorescenceChainRow(HasTraits)` (Qt-free): `label = Str()`, `wavelength = Enum(*LED_WAVELENGTHS)`, `intensity = Range(LED_DUTY_MIN, LED_DUTY_MAX, value=50)`, `frequency = Range(LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=40000)`, `exposure = Range(float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=10.0)` (ms), `gain = Range(ASI_GAIN_MIN, ASI_GAIN_MAX, value=0)`, `run = Bool(True)`; `to_entry_dict()` / `from_entry(cls, entry: ChainEntry)` converting to/from Task 1's keys (`exposure` ↔ `exposure_ms`).
- Model (`FluorescenceStatusModel`) DELETES: `mode`, every `br_*`/`fl_*` trait, `show_brightfield`/`show_fluorescence`, `_collapse_unused_mode_sections`, `br_led_index`/`fl_led_index`. ADDS the single set with the SAME defaults as the old `br_*` row (`intensity 50, frequency 40000, exposure 10.0, gain 0`): `label = Str("")`, `wavelength = Enum(*LED_WAVELENGTHS)`, `intensity`, `frequency`, `exposure`, `gain` (same trait shapes as the old br_ ones, `RangeWithViewHints` for exposure), `led_index` property, `show_params = Bool(True)`; chain state: `chain_rows = List(Instance(FluorescenceChainRow))`, `chain_selection = Instance(FluorescenceChainRow)` (TableEditor `selected=` binds an object, not an index), `attached_step_id = Str("")` ("" = free mode), `attached_group_id = Str("")`, `free_chain = List(Instance(FluorescenceChainRow))` (the unattached stash shown whenever `attached_step_id == ""`).
- `PERSISTED_CONTROL_TRAITS = ["wavelength", "intensity", "frequency", "gain", "exposure", "device_viewer_stream", "auto_exposure", "auto_gain"]` (consts.py:48 replaced). `preferences.py`: delete `mode` + all `fluorescence_br_*`/`fluorescence_fl_*` helper traits; add the single-name equivalents matching the new list (same `fluorescence_` prefix scheme the file already uses). `label` is NOT persisted (defaults from wavelength at Add time).

- [ ] **Step 1: Failing tests** — `test_chain_model.py`: `FluorescenceChainRow` ↔ `ChainEntry` round-trip incl. `exposure`↔`exposure_ms`; defaults; model has no `mode`/`br_wavelength`/`fl_gain` attribute (`hasattr` False), has the new set; `PERSISTED_CONTROL_TRAITS` exact new list. Update `test_control_persistence.py`'s round-trip to the new trait names (it currently iterates the old list — the shape of the test stays, the names change; `light_on` still never persists).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Keep `traits_init` pull + `_push_preferences`/`_pull_preferences` mechanics identical, just over the new list.
- [ ] **Step 4: Run to verify pass** (both test files).
- [ ] **Step 5: Commit** `feat(controls-ui)!: single param set + chain rows on the model` (BREAKING CHANGE footer: PERSISTED_CONTROL_TRAITS loses mode and br_*/fl_*).

### Task 4: Controller — live rules, chain ops, attach flow

**Files:**
- Modify: `fluorescence_controls_ui/controller.py`, `fluorescence_controls_ui/message_handler.py`, `fluorescence_controls_ui/live_state.py` (only if a ferry event needs renaming — prefer reuse)
- Test: `fluorescence_controls_ui/tests/test_led_controls.py` (rewrite affected tests) + `tests/test_attach_flow.py` (new)

**Interfaces:**
- `_live()` replaces `_br_live`/`_fl_live`: `stream_active and light_on and not protocol_running` (mode clause dropped — the ONE existing rule, unchanged otherwise).
- `_active_led_payload()` → `{"led": self.model.led_index, "duty": self.model.intensity}` (+`exclusive`).
- Live-edit observers: single set (`intensity`→SET_LED, `frequency`→SET_LED_FREQUENCY, `wavelength`→exclusive SET_LED), each gated on `_live()`; camera push mirrors `exposure` (ms→µs `int(self.model.exposure * 1000)`) and `gain` into `asi_camera_settings`, gated off during `protocol_running` — all exactly the current br_ bodies with the prefix dropped (controller.py:174-244).
- `_adopt_auto_value` writes `self.model.exposure` / `self.model.gain` (no prefix resolution; delete `_camera_mode_is_fl`).
- **Panel ↔ chain row live binding:** observer on the six param traits: when `model.chain_selection` is set and a `_loading_row` guard is False, copy panel values into the selected row, then `_push_chain_to_step()`. Observer on `model.chain_selection`: set `_loading_row`, copy row → panel traits, clear guard; LED follows via the existing live-edit observers firing on those writes (that IS the row-click-drives-LED rule).
- `_push_chain_to_step()`: if `attached_step_id`, `protocol_tree_set_cell_publisher.publish(step_id=..., col_id=FLUORESCENCE_CHAIN_COLUMN_ID, value=dump_chain([r.to_entry... for r in model.chain_rows]) or None)` (empty chain → `None` so the cell blanks). Import the publisher from `pluggable_protocol_tree.consts`.
- **Add**: build `FluorescenceChainRow` from panel values, `label = sanitize_label(model.label or model.wavelength)` then `unique_label(...)` against current chain labels, append, select it, push.
- **Label rename collisions**: observer on `chain_rows.items.label` re-uniquifies (suffix) — guard reentrancy.
- **Row selection message flow** (`message_handler.py` already receives `PROTOCOL_TREE_ROW_SELECTED`): parse with `ProtocolTreeRowSelectedMessage.deserialize`; ferry to the GUI thread via a new `live_state.tree_row_selected = Event()` carrying the parsed message (same pattern as the existing events). Controller observer `_on_tree_row_selected(event)`:

```python
    free = list(self.model.free_chain) if self.model.attached_step_id == "" \
        else []
    msg = event.new
    if msg.step_id:
        if free:
            n = len(free)
            choice = choose(
                None,
                f"The free-mode chain holds {n} capture"
                f"{'s' if n != 1 else ''}. Attach to the selected step?",
                title="Attach Capture Chain",
                choices=["Append", "Replace", "New step"])
            if choice is None:
                return                       # chain stays unattached
            if choice == "New step":
                protocol_tree_add_step_publisher.publish(
                    after_step_id=msg.step_id,
                    cells={FLUORESCENCE_CHAIN_COLUMN_ID:
                           dump_chain([r.to_entry_dict() for r in free])},
                    name="Step (capture chain)")
                self._clear_free_chain()
                return                       # pane returns to empty free mode
            existing = parse_chain(msg.cells.get(FLUORESCENCE_CHAIN_COLUMN_ID))
            if choice == "Append":
                merged = existing + self._suffixed(free, existing)
            else:                            # Replace
                merged = [r.to_entry(...) for r in free]
            self._attach_to_step(msg.step_id, merged)   # sets model state + set_cell publish
            self._clear_free_chain()
            return
        self._load_step_chain(msg.step_id, msg.cells)   # plain selection
    elif msg.group_id:
        if free:
            choice = choose(None, ..., title="Attach Capture Chain",
                            choices=["New step"])       # group: only New step
            if choice == "New step":
                protocol_tree_add_step_publisher.publish(
                    group_id=msg.group_id, cells={...}, name="Step (capture chain)")
                self._clear_free_chain()
                return
        self._enter_free_mode()
    else:
        self._enter_free_mode()
```

  (`_enter_free_mode` restores `free_chain` into `chain_rows` and clears `attached_step_id`; `_load_step_chain` stashes nothing — free chain was empty. Attach dialogs run in a Traits `dispatch="ui"` observer, NOT inside a table commit — safe to be modal directly.) **Documented deviation:** after "New step" the pane returns to the empty free-mode chain instead of auto-switching to the not-yet-known new step's uuid; the user's next click on it loads the chain. Note this in the PR body.
- **Run Capture**: `run_capture()` → Task 6's `run_burst(...)` on the current chain's ticked rows; free mode → free-mode folder; attached → the step's folder name needs dotted id, which row_selected does not carry — pass `step_desc=None, step_id=self.model.attached_step_id` and let Task 6 fall back to `step_<uuid8>_<utc>` for pane-initiated bursts (documented deviation: dotted ids only available during protocol execution). Disabled while `protocol_running` (view gates it too).

- [ ] **Step 1: Failing tests** — rewrite `test_led_controls.py` publish assertions to the single set (`published` fixture pattern stays); new `test_attach_flow.py` drives `_on_tree_row_selected` directly with constructed `ProtocolTreeRowSelectedMessage` objects, monkeypatching `controller_mod.choose` (returns "Append"/"Replace"/"New step"/None) and `controller_mod.protocol_tree_set_cell_publisher` / `protocol_tree_add_step_publisher` with recorders: assert merged chains, label suffixing on Append collisions, Cancel leaves free chain intact and does not publish, group offers add_step with `group_id`, plain selection loads the step chain, deselection restores free mode.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** (complete the sketch — every helper named above becomes a real method; no other new names).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** `feat(controls-ui): live single-set LED rules + chain attach flow`.

### Task 5: View — param panel + chain table

**Files:**
- Modify: `fluorescence_controls_ui/view.py`, `fluorescence_controls_ui/dock_pane.py`
- Test: `fluorescence_controls_ui/tests/test_view_shape.py` (new, construction-only)

**Interfaces:** `params_group` replaces `brightfield_group`/`fluorescence_group`/mode row: `label`, `wavelength`, `intensity`, `frequency`, `exposure` (`enabled_when="not auto_exposure"`) + `auto_exposure`, `gain` (`enabled_when="not auto_gain"`) + `auto_gain`, `visible_when="show_params"`. `chain_group`: HGroup(`add_capture` button, `run_capture` button `enabled_when="connected and not protocol_running"`) above a `TableEditor` on `chain_rows` with columns Label (`ObjectColumn(name="label")`, editable) and Run (`CheckboxColumn(name="run")`), `selected="chain_selection"`, row factory disabled (Add button owns creation). Buttons are TraitsUI `Action`s/`Button` traits handled by the controller (`add_capture_fired` → controller.add; match how the existing view wires `light_on`/`stream_active` interactions). The mode EnumEditor row is deleted; `control_group`'s light/stream toggles stay.

⚠ TableEditor trap (project memory): never open a modal or revert a trait inside a cell-editor commit — label re-uniquify runs in a trait observer (Task 4) which is fine, but ANY dialog from table interaction must go through `QTimer.singleShot`.

- [ ] **Step 1: Failing test** — `test_view_shape.py`: import view module; assert `UnifiedView` content contains no `mode`/`br_`/`fl_` item ids (walk `Group.content` recursively collecting `Item.name`s) and does contain the six param names + `chain_rows`; instantiate `FluorescenceStatusModel()` and `edit_traits`? NO — construction-only, offscreen widget instantiation is Task 10 manual. Keep it to the Item-name walk (pure, no Qt).
- [ ] **Step 2-4: fail → implement → pass.**
- [ ] **Step 5: Commit** `feat(controls-ui)!: single param panel + chain table view`.

### Task 6: Burst capture service + feed registry

**Files:**
- Modify: `fluorescence_controls_ui/cameras/provider.py`
- Create: `fluorescence_controls_ui/capture_service.py`
- Modify: `fluorescence_controls_ui/message_handler.py` (notify applied)
- Test: `fluorescence_controls_ui/tests/test_capture_service.py`

**Interfaces:**
- provider: module-level `_ACTIVE_FEED = None`; `AsiCameraFeed.__init__` sets it to `self`, `close()` clears it if still self; `current_feed()` accessor. Feed gains `frame_seq = 0` (incremented in `_on_thread_frame` before storing `_last_raw`) and

```python
    def wait_for_frame_after(self, seq: int, timeout: float) -> bool:
        """Block (worker thread) until a frame newer than ``seq`` lands."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.frame_seq > seq and self._last_raw is not None:
                return True
            time.sleep(0.02)
        return False
```

- `capture_service.py`:
  - `notify_applied()` / `_APPLIED = threading.Event()`; `wait_applied(timeout) -> bool` (clear-before-publish pattern: `arm_applied()` clears). `message_handler.py`'s listener calls `capture_service.notify_applied()` on `FLUORESCENCE_APPLIED`.
  - `burst_folder(step_desc: str | None, dotted_id: str | None, step_id: str | None = None) -> Path`: `<get_current_experiment_directory()>/captures/<name>_<utc>` where name = `f"{sanitize_label(step_desc)}_{dotted_id}"` when both given, `f"step_{step_id[:8]}"` when only uuid, else `"free_mode"`; utc = `time.strftime("%Y_%m_%d-%H_%M_%S", time.gmtime())`; mkdir parents + `16bit_raw` subdir.
  - `apply_camera_settings(entry)`: marshal `asi_camera_settings.exposure = int(entry.exposure_ms * 1000); asi_camera_settings.gain = entry.gain` via `GUI.invoke_later` (verbatim pattern from the old `_apply_camera_settings`, fluorescence_column.py history — the deleted file; recover the exact marshalling from git show if needed).
  - `save_entry_capture(entry, folder) -> Path`: `feed = current_feed()` (raise `RuntimeError("no active camera feed")` if None); `seq = feed.frame_seq`; `wait_for_frame_after(seq, timeout=entry.exposure_ms / 1000.0 * 2 + 2.0)` else raise; take `raw = feed._last_raw`; save `raw_to_qimage(raw)` → `folder / "16bit_raw" / f"{sanitize_label(entry.label)}_raw.png"`; save the 8-bit display conversion → `folder / f"{sanitize_label(entry.label)}.png"` using the SAME conversion chain `provider._on_thread_frame` uses for previews (`to_display_8bit` + the existing QImage constructor helper — copy those exact lines, do not invent a new conversion); return the display path.
  - `run_burst(entries, *, step_desc=None, dotted_id=None, step_id=None, applied_timeout=5.0) -> Path` (pane-initiated path): folder = `burst_folder(...)`; for each `e in ticked(entries)`: `apply_camera_settings(e)`; `arm_applied()`; `protocol_set_fluorescence_publisher.publish(light_on=True, led=e.led_index, duty=e.intensity, frequency=e.frequency, settle_s=LED_STABILIZATION_S)`; `wait_applied(applied_timeout)` else raise `TimeoutError(f"LED apply not acknowledged for {e.label!r}")`; `save_entry_capture(e, folder)`. Finally-block: `publish_message(topic=ALL_LEDS_OFF, message="")`. Returns the folder. MUST be called off the GUI thread (the controller wraps it in a `threading.Thread` + completion dialog via `GUI.invoke_later` — wire that thin wrapper in the controller as part of this task: `run_capture()` from Task 4 delegates here).
- [ ] **Step 1: Failing tests** — fake feed object (`frame_seq`, `_last_raw` 16-bit numpy, `wait_for_frame_after` real method under test on a real `AsiCameraFeed.__new__`-free fake — test the REAL `wait_for_frame_after` by binding it to a stub with the two attributes); `burst_folder` naming for all three cases (monkeypatch `get_current_experiment_directory` → tmp_path, freeze `time.gmtime` via monkeypatch for a stable utc); `run_burst` happy path with monkeypatched publisher recorder + auto-set `_APPLIED` + fake feed → files exist with expected names, publisher called per ticked entry only, ALL_LEDS_OFF fired in finally; timeout path raises and still fires ALL_LEDS_OFF.
- [ ] **Step 2-4: fail → implement → pass.**
- [ ] **Step 5: Commit** `feat(controls-ui): burst capture service + active-feed registry`.

### Task 7: Protocol execution — the chain handler body

**Files:**
- Modify: `fluorescence_protocol_controls/protocol_columns/chain_column.py` (fill `FluorescenceChainHandler.on_pre_step`)
- Test: `fluorescence_protocol_controls/tests/test_chain_execution.py`

**Interfaces:** for each ticked entry, in order: `capture_service.apply_camera_settings(e)` → publish `protocol_set_fluorescence_publisher.publish(light_on=True, led=e.led_index, duty=e.intensity, frequency=e.frequency, settle_s=LED_STABILIZATION_S)` → `ctx.wait_for(FLUORESCENCE_APPLIED, timeout=self.ack_time_s)` (the executor's mailbox — NOT capture_service's Event) → `capture_service.save_entry_capture(e, folder)`. Folder built once per step: `capture_service.burst_folder(step_desc=row.name, dotted_id=row.dotted_path())`. Preview mode: no-op (same guard the old handler used). Empty ticked chain: no-op. Any raise (TimeoutError from wait_for, RuntimeError from save) propagates — the step times out/fails, the ack is effectively withheld (existing backend error contract at `fluorescence_command_setter_service.py:57` unchanged).

- [ ] **Step 1: Failing tests** — mirror the deleted `test_fluorescence_column.py` execution conventions (`_Ctx` fake recording `wait_for` calls, `published` fixture on the column module, monkeypatch `chain_column.capture_service` with a recorder object): 3-entry chain with 2 ticked → exactly 2 publishes, 2 `wait_for(FLUORESCENCE_APPLIED, 5.0)`, 2 saves, in chain order, one folder; preview → nothing; unticked/empty → nothing; `wait_for` raising TimeoutError propagates and no save happens for that entry.
- [ ] **Step 2-4: fail → implement → pass.**
- [ ] **Step 5: Commit** `feat(protocol): per-entry burst execution with withheld-ack failures`.

### Task 8: Image viewer — recursive discovery

**Files:**
- Modify: `fluorescence_controls_ui/image_viewer/discovery.py` + its dock-pane call site (grep `current_raw_captures_directory` usages)
- Test: update `fluorescence_controls_ui/tests/test_image_viewer.py`

**Interfaces:** `current_captures_directory()` replaces `current_raw_captures_directory()` — returns `<exp>/captures` (same try/except shape). `discover_captures(directory)` goes recursive and raw-only:

```python
    paths = {path
             for pattern in IMAGE_PATTERNS
             for path in Path(directory).rglob(pattern)
             if path.parent.name == RAW_CAPTURES_SUBDIR}
```

(sorted key unchanged). Old flat layout (`captures/16bit_raw/x.png`) still matches — parent name is the filter, not depth. Update every caller of the renamed function.

- [ ] **Step 1: Failing tests** — nested burst dirs `captures/Mix_1.2_<utc>/16bit_raw/GFP_raw.png` + old flat `captures/16bit_raw/old_raw.png` both found; display PNGs at burst root NOT returned; renamed function returns `<exp>/captures`.
- [ ] **Step 2-4: fail → implement → pass.**
- [ ] **Step 5: Commit** `feat(controls-ui): recursive raw-capture discovery for burst folders`.

### Task 9: Breaking sweep + version 1.0.0

**Files:**
- Modify: `pyproject.toml` (BOTH version fields → `1.0.0`), `fluorescence_protocol_controls/consts.py` (delete `FLUORESCENCE_COMPOUND_BASE_ID`, `FLUORESCENCE_ON_COLUMN_ID`, `FLUORESCENCE_SETTINGS_COLUMN_ID`, `STEP_SETTING_TRAITS`), `CHANGELOG.md` (1.0.0 section: breaking changes list from the design doc), plus whatever the greps below surface (e.g. `live_state.py` snapshot events with no remaining consumer, `dock_pane.py` references).
- Test: full-repo greps are the test.

- [ ] **Step 1: Sweep** — `git grep -nE "fluorescence_settings|fluorescence_on|FLUORESCENCE_COMPOUND|STEP_SETTING_TRAITS|br_wavelength|fl_wavelength|br_exposure|fl_exposure|\bmode\b.*br.*fl|step_settings"` (excluding `docs/` and `CHANGELOG.md`) must come back empty of live code; fix every hit (delete dead ferries in `live_state.py` if nothing consumes them — check `tracked_step_uuid`/`step_snapshot_selected`/`protocol_step_settings_applied` consumers first; keep any that Task 4 still uses).
- [ ] **Step 2: Version + changelog** — both `pyproject.toml` fields `1.0.0`; CHANGELOG 1.0.0 entry naming: mode/br_*/fl_* removed from prefs, old step settings dropped (users rebuild chains), old column id retired, new `fluorescence_chain` column, capture lock, burst folders.
- [ ] **Step 3: Targeted re-runs** — every test file this plan created/modified, one command, all green.
- [ ] **Step 4: Commit** `feat!: release capture-chain rework as 1.0.0` (BREAKING CHANGE footer with the same list).

### Task 10 (USER — do not dispatch): manual GUI verification

Launch via run-microdrop with the fluorescence board + ASI camera attached: author a free-mode chain, Run Capture, attach via all four dialog outcomes, verify capture-cell grey-out + tooltip on chained steps, run a protocol with a 2-capture chain, inspect `captures/<step>_<id>_<utc>/` contents, image viewer shows nested raws, photobleaching strobe check while clicking down a chain.

## Self-Review Notes

- Every design-doc section maps: panel (T3/T5), panel↔row live (T4), chain table (T5), free-mode attach incl. group + cancel (T4, needs #542 `choose`), column display `2/4` (T2), execution loop + withheld ack (T7), plugin-owned capture path + one-folder-per-burst + `16bit_raw` (T6), recursive viewer (T8), capture lock incl. lock-on-load + first-time dialog (T2, needs #541 + `on_row_loaded`), breaking changes + dual version fields (T9).
- **Documented deviations (surface in the PR):** (1) after "New step" the pane returns to empty free mode rather than auto-following the new step (its uuid is not known to the pane); (2) pane-initiated bursts on an attached step name the folder `step_<uuid8>_<utc>` (dotted id is an execution-time concept); (3) the viewer stays raw-only (parent-dir filter) rather than showing display duplicates.
- Interface consistency: `ChainEntry`/`parse_chain`/`dump_chain`/`ticked`/`sanitize_label`/`unique_label` (T1) are the only chain vocabulary used by T2/T4/T6/T7; `FLUORESCENCE_CHAIN_COLUMN_ID` everywhere; `run_burst` vs handler loop share `apply_camera_settings`/`save_entry_capture`/`burst_folder`.
- Deliberately NOT done (YAGNI, per design doc): shared capture pipeline burst support, BLE, ROI analysis, migration of old `fluorescence_settings` values.
