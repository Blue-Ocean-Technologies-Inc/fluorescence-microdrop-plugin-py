# Fluorescence Chain Capture Timing — Design

**Date:** 2026-07-21
**Status:** Approved
**Scope:** fluorescence-microdrop-plugin-py (`fluorescence_protocol_controls`, `fluorescence_controls_ui`)

## Goal

Let the operator choose, per capture-chain row, whether that row's capture fires
at protocol **step start**, **step end**, or **both**. Today the
`FluorescenceChainHandler` hardcodes step start (`on_pre_step`), while the
regular image capture (`video_protocol_controls` capture column) already offers
a Step Start / Step End choice via the same executor hook mechanism
(`on_pre_step` / `on_post_step`). This feature builds on that mechanism and
goes one step further by allowing both phases at once.

## Data model

`fluorescence_protocol_controls/capture_chain.py` — `ChainEntry` gains two
booleans:

| Field | Default | Meaning |
|---|---|---|
| `capture_start` | `True` | Row fires in the executor's `on_pre_step` phase |
| `capture_end` | `False` | Row fires in the executor's `on_post_step` phase |

- `dump_chain` serializes both fields.
- `parse_chain` defaults missing keys to `capture_start=True, capture_end=False`
  — chains saved before this change load and behave exactly as today
  (step-start only).
- Sanitize on parse: an entry with both fields `False` is coerced to
  `capture_start=True`. The invariant "at least one phase on" is otherwise
  enforced in the UI.

`fluorescence_controls_ui`'s `FluorescenceChainRow` gains matching Bool traits,
carried through the existing panel↔row binding and row↔entry round-trip.

## UI

In the **LED / Camera Params** section (`fluorescence_controls_ui/view.py`,
`params_group`), directly beneath the Gain row, one new line:

```
Protocol Step Time of Capture:   [ Start ]  [ End ]
```

- An `HGroup` of a `Label` and two `InPlaceToggleEditor` buttons (the Light
  On/Off widget), constant labels "Start" / "End"; the checked-state styling
  conveys on/off.
- At-least-one-on invariant, enforced declaratively — a toggle disables only
  when it is the sole phase on, so it can never be switched off last:
  - Start button: `enabled_when="capture_end or not capture_start"`
  - End button: `enabled_when="capture_start or not capture_end"`
- Because the params panel doubles as the editor for the selected chain row,
  existing rows' timing is editable by selecting the row; the Add button
  snapshots the toggles into new rows like every other param.
- No new chain-table column; the table is unchanged.
- The manual **Run Capture** / **Capture Selected** buttons ignore the timing
  fields — timing only governs protocol execution.

## Execution

`fluorescence_protocol_controls/protocol_columns/chain_column.py` —
`FluorescenceChainHandler`:

- The current `on_pre_step` body is extracted into a shared helper
  `_run_entries(ctx, row, entries)`.
- `on_pre_step` runs the ticked entries with `capture_start=True`.
- New `on_post_step` runs the ticked entries with `capture_end=True`.
- A row with both on captures twice in that step (once per phase).

Unchanged: handler priority 5, `wait_for_topics=[FLUORESCENCE_APPLIED]`,
per-column ack timeout, the #541 capture-cell mutual-exclusion lock,
`on_post_protocol_end` → `ALL_LEDS_OFF`, burst internals (`capture_service`),
and capture filenames. The end phase's burst folder does carry an `_end`
suffix on its `step_desc` (`capture_service` itself is unchanged), so a
both-phases step that completes within one wall-clock second cannot have
its end-phase captures overwrite its start-phase captures.

## Out of scope

- No new global preference (new rows always default to Step Start).
- No timing summary in the protocol-tree chain cell.
- No changes to the regular capture column or `pluggable_protocol_tree`.

## Testing

Unit-testable seams (user runs tests manually):
- `parse_chain` / `dump_chain` round-trip with the new fields, legacy-dict
  defaulting, and the both-False coercion.
- Handler phase filtering: given a mixed chain, `on_pre_step` receives only
  start entries, `on_post_step` only end entries.
