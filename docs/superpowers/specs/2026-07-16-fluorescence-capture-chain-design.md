# Fluorescence capture chain — design

**Date:** 2026-07-16
**Status:** approved, pending implementation plan
**Scope:** two repos, three issues

- **Microdrop#541** (`pluggable_protocol_tree`): generic per-row column locks. Blocks the rework.
- **Microdrop#542** (`pyface_wrapper`): expose a multi-choice dialog. Blocks the attach prompt.
- **fluorescence#6** (major release, `1.0.0`): panel rework + per-step capture chain.

---

## Motivation

The fluorescence controls pane is organised around a `br` / `fl` / `dual` mode
selector. Mode is not a value preset — it is a **gate**. The model carries two
parallel param sets (`br_*` and `fl_*`: wavelength, intensity, frequency,
exposure, gain), the view enables or disables each group with `enabled_when`, and
`controller._active_led_payload()` sends the *brightfield* set for both `br` and
`dual`.

This is rigid in the way that matters: an experiment that wants three channels
(say GFP, mCherry, brightfield) cannot express it. There are exactly two slots,
and one of them is spoken for.

The replacement is a **single** param panel plus a **per-step chain** of named
captures. A step's chain is a list; the protocol column shows its size, exactly
as the electrodes column shows `str(len(value or []))`. This makes the
fluorescence column symmetric with the rest of the tree rather than a special
case, and it removes the duplicated `br_*`/`fl_*` axis entirely.

---

## Issue A — generic per-row column locks (Microdrop)

### Problem

No mechanism exists for one column to disable another column's cell on a given
row. `MvcTreeModel.flags()` (`views/qt_tree_model.py:168-172`) is an
unconditional delegation to the single owning column:

```python
def flags(self, index):
    if not index.isValid():
        return Qt.NoItemFlags
    col = self._manager.columns[index.column()]
    return col.view.get_flags(index.internalPointer())
```

There is no hook, filter, or chain where another column can intervene; no
per-row extras dict; no row-level trait the framework consults.

This is a pre-existing gap, not only a fluorescence one.
`builtins/repeat_duration_column.py:85` shows a confirm dialog promising *"Route
Reps will become read-only while Route Reps Dur is in control."* That never
happens — `RepsSpinBoxColumnView.get_flags`
(`builtins/repetitions_column.py:36-37`) unconditionally returns
`... | Qt.ItemIsEditable`. The arbitration is instead enforced reactively in
`on_interact` by prompting and rejecting the edit. The feature was specified,
shipped a dialog, and was never implemented for want of this mechanism.

### Design

**Storage.** `BaseRow` gains owner-keyed lock storage, conceptually:

```
column_locks: {col_id: {owner: reason}}
```

A column locks another column's cell by `(col_id, owner, reason)` and releases
only its own lock. The cell stays locked while any owner still holds one. This
matters: a bare `Set(Str)` of locked ids would let one releasing owner wrongly
re-enable a cell another owner still wants locked.

The `reason` string renders as the cell tooltip, so the explanation travels with
the lock instead of being hardcoded at the call site.

**Enforcement.** `flags()` grows to roughly:

```python
def flags(self, index):
    if not index.isValid():
        return Qt.NoItemFlags
    col = self._manager.columns[index.column()]
    row = index.internalPointer()
    flags = col.view.get_flags(row)
    if row.is_column_locked(col.model.col_id):
        flags &= ~(Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
    return flags
```

Clearing **both** flags is required. Checkboxes are never `ItemIsEditable` —
they are `ItemIsUserCheckable` (`views/columns/checkbox.py:26-30`), so clearing
only `ItemIsEditable` on the `capture` checkbox would do nothing at all.
Clearing both also satisfies the existing `BackgroundRole` grey read-only fill
(`qt_tree_model.py:131-134`), which tests for the absence of both — so the
visual comes for free.

**Repaint.** `get_flags` is pull-only; Qt will not re-query it until something
emits `dataChanged`. The model therefore observes the lock storage in
`_wire_row_observers` (`qt_tree_model.py:286`) and emits `dataChanged` itself.
Auto-wiring centrally, rather than requiring each gated column to declare
`depends_on_row_traits`, is deliberate: it is the difference between fixing the
class of bug and reproducing it.

**Persistence — locks are NOT persisted.** They are runtime-derived state,
rebuilt from their source (e.g. the fluorescence chain) on load.
`services/persistence.py::_collect_row_flags` is untouched.

The trap this avoids: a protocol authored with the fluorescence plugin loaded,
then opened *without* it, would have a permanently disabled capture column and
nothing alive to release the lock. The user could neither tick capture nor find
out why. What persists is the chain; the lock is a consequence of it.

### Definition of done

1. Owner-keyed lock storage + lock/unlock/query API on `BaseRow`.
2. `flags()` honours locks centrally, clearing `ItemIsEditable | ItemIsUserCheckable`.
3. Lock reasons surface as the cell tooltip.
4. Repaint auto-wired in `_wire_row_observers`.
5. Locks are not serialized.
6. **Debt paid:** `repeat_duration_controls` adopts the mechanism, making its
   dialog's promise true.
7. **Latent bug retired:** `CaptureAtComboBoxView` gates on `row.capture` but
   never declares `depends_on_row_traits = ["capture"]`, so its grey-out only
   refreshes on an incidental repaint. Central auto-wiring fixes this.

---

## Issue B — fluorescence panel + capture chain (major release)

### Panel

One param set. `mode` and every `br_*` / `fl_*` pair are deleted.

| field | notes |
|---|---|
| `label` | editable, defaults to the wavelength name, feeds the filename |
| `wavelength` | `Enum(*LED_WAVELENGTHS)`, 6 entries, Blue 460 → Deep Red 660 |
| `intensity` | % |
| `frequency` | Hz (LED PWM) |
| `exposure` | ms in the pane (µs in `cameras/camera_settings.py` — converter required) |
| `gain` | |

`auto_exposure` / `auto_gain` survive as **live-preview helpers only**. Flip auto
on, let it settle, read the number it found, flip it off — the row stores that
concrete value. Rows are therefore always deterministic, so replaying a protocol
reproduces the images. A row that said "auto-expose me" would store an exposure
that is a lie, and two identical-looking rows could produce different images.

### Panel ↔ row

Selecting a row loads it into the panel. Panel edits write **live** into the
selected row — no commit button.

The LED follows the panel under the **existing** rule, unchanged:
`light_on and stream_active and not protocol_running`
(`controller._br_live` / `_fl_live` collapse into one).

Known consequence: clicking down a four-row chain strobes the sample through
four wavelengths. Accepted; flagged in case photobleaching makes it not.

### Chain table

The selected step's chain, loaded when a step is clicked in the protocol tree —
symmetric with electrodes, where each step owns its own list. With no step
selected it shows the unattached free-mode chain (see below).

Columns are **Label** and **Run** only. No param columns; all param editing
happens in the panel above. **Add** and **Run Capture** sit above the table,
mirroring the route view's `run_controls`
(`device_viewer/views/route_selection_view/route_selection_view.py:164`).

Only **ticked** rows capture. Parking a row in the chain without running it is
supported.

**Label defaults and uniqueness.** A new row's label defaults to its wavelength
name (e.g. `Green 530`). Labels become filenames within a burst folder, so they
must be unique *within a chain*: a collision is resolved by suffixing `_2`, `_3`
… at Add time. Editing a label into a collision is rejected the same way. Labels
need not be unique across steps — each burst has its own folder.

**Add** copies the panel's current values into a new row and selects it.
**Run Capture** runs the current chain's ticked rows immediately, independent of
any protocol run, and is disabled while `protocol_running`.

### Free mode and attaching a chain to a step

Chains are authored in **free mode** and attached to a step afterwards — the
same shape as routes, which are drawn free and then landed on a step via
`commit_to_step_btn` / `routes_commit_enabled`
(`route_selection_view.py:201-207`).

With no step selected, the pane holds an unattached **free-mode chain**. Add and
Run Capture work on it normally; a free-mode burst writes to
`captures/free_mode_<utc>/<label>.png`, matching the existing scheme's
`free_mode_<timestamp>` fallback for a missing `step_id`
(`widget.py:906-913`).

Clicking a **step** while the free-mode chain is non-empty raises a dialog
naming the conflict and offering four outcomes:

| choice | effect |
|---|---|
| Append | free-mode rows are appended to the step's existing chain; label collisions suffix `_2`, `_3` … |
| Replace | the step's chain is discarded and replaced by the free-mode rows |
| New step | a new step is created **immediately after the clicked row**, carrying the free-mode rows |
| Cancel | nothing moves; the free-mode chain stays unattached |

On Append / Replace / New step the free-mode chain is cleared and the pane
switches to showing the target step's chain.

Clicking a **group** offers only **New step**, appended as the group's last
child — groups hold no chain, so there is nothing to append to or replace.

If the free-mode chain is empty, clicking a step or group raises no dialog and
simply loads that step's chain (or nothing, for a group).

**Implementation note.** This dialog is four-way, and
`pyface_wrapper.confirm()` maps every outcome down to `YES` / `NO` / `CANCEL`.

The infrastructure is already there, though: `BaseMessageDialog.__init__` takes
`buttons: Optional[Dict[str, Any]]` (an arbitrary label → `{action, role}` map),
already reserves `RESULT_CUSTOM_1/2/3 = 10/11/12` — *"Custom result codes start
from 10"* — and already sorts `role="exit"` buttons leftward. Only the wrapper's
public surface lacks a way in. Tracked as **Microdrop#542**, which is about
exposing what exists rather than building new dialog machinery.

Do **not** reach for a raw `QMessageBox`, nor instantiate `BaseMessageDialog`
directly to bypass the wrapper.

### Protocol column

**New column id.** The old `fluorescence_settings` id retires rather than being
reinterpreted — reusing it would let old protocols half-load into a new-shaped
value, which is worse than a clean break.

Renders `ticked/total` when they differ (`2/4`), plain count when they don't
(`2`). This departs from the electrodes column's bare `str(len(...))` because
ticked ≠ total is expressible here and a bare count would be misleading.

### Execution

For each ticked row, in order:

1. set LED → wait `FLUORESCENCE_APPLIED`
2. grab and save the frame

The protocol ACK fires **only when the loop ends**. Failures withhold the ack so
the step times out and fails, per the existing backend error contract
(`services/fluorescence_command_setter_service.py:57`).

### Capture path — the plugin writes its own files

The plugin already owns the ASI camera stack (`cameras/zwoasi.py`,
`asi_thread.py`, `provider.py`), and grabs/saves frames itself.

**Why not extend the shared pipeline:** it would span two repos. The shared
pipeline is genuinely not burst-capable today —
`video_protocol_controls/protocol_columns/capture_column.py` runs
`wait_for_topics = []` and `ack_time_s = 0` (fire-and-forget, no ack at all);
`DEVICE_VIEWER_MEDIA_CAPTURED` is declared and re-exported but **never published
in production**; and `_generate_media_filename`
(`device_viewer/views/camera_control_view/widget.py:906`) timestamps at
one-second resolution with no counter, so a burst would silently overwrite
itself into a single file. Making it burst-capable is real work in Microdrop and
is explicitly **not** in scope.

### Filename layout — one folder per burst

```
<EXPERIMENTS_DIR>/<experiment_directory>/captures/
    <step_desc>_<dotted_id>_<utc>/        # a step's burst
        GFP.png
        mCherry.png
        BF.png
        16bit_raw/
            GFP_raw.png
            mCherry_raw.png
            BF_raw.png
    free_mode_<utc>/                      # an unattached burst
        Green_530.png
        16bit_raw/
            Green_530_raw.png
```

A burst is one browsable unit and the filenames are short. `dotted_id` is
`row.dotted_path()` (`pluggable_protocol_tree/models/row.py:48-51`), the
1-indexed `1.2.3` display id. Labels are sanitized as the existing scheme does
(alnum + space/dash/underscore, spaces → `_`).

The plugin's own `image_viewer/discovery.py` needs a **recursive** glob to find
nested captures. This stays self-contained — the image viewer is in this repo.

### Capture column locking

When a step's chain has ≥1 ticked row, the fluorescence column locks that step's
`capture` cell via Issue A's mechanism, owner `fluorescence`, reason naming the
chain. A dialog informs the user the first time this happens on a step that
already had capture ticked.

This is what keeps the two capture paths from both writing the same step, and
therefore what makes "the plugin writes its own files" safe: only one writer per
step, so no ambiguity about which naming scheme produced a file.

Dialogs go through `microdrop_application.dialogs.pyface_wrapper` — never raw
`QMessageBox` or `pyface.api`.

Locking is applied whenever the step's chain changes, **not** at execution time:
the cell must *look* disabled in the tree while the user is editing, long before
anything runs.

### Breaking changes

Major version bump. Note the version lives in **two** places in `pyproject.toml`
(`[project]` and `[tool.pixi.package]`).

- `PERSISTED_CONTROL_TRAITS` loses `mode` and every `br_*` / `fl_*` pair.
- Old `fluorescence_settings` step settings are dropped; users rebuild chains.
- The old column id retires.

Chosen over migrating on load: the `dual` → single-param-set mapping is lossy,
and a major release is the honest place to break.

---

## Open / deferred

- Photobleaching from row-selection strobing — accepted, revisit if it bites.
- The shared capture pipeline stays fire-and-forget; its burst-incapability and
  the never-published `DEVICE_VIEWER_MEDIA_CAPTURED` remain unaddressed.
- BLE transport, ROI/Excel analysis — unchanged, still deferred.
- VID:PID clash with the heater board (both `2E8A:0005`) — unchanged.
