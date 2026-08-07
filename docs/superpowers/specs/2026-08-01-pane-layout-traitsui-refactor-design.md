# Pane Layout Rework + TraitsUI-First Refactor — Design

Date: 2026-08-01
Branch: `feat/roi-intensity-analysis` (stacks on the ROI persistence/styling work)
Status: approved (layout Option A chosen via mockup review)

## Problem

1. **The ROI plot dock pane is horizontally locked.** Its single controls row
   (stat combo + X/Y auto checkboxes + 4 spinboxes + dpi combo + format combo
   + save button) dictates a very large minimum width; the dock pane refuses
   to shrink below it and nothing scrolls.
2. **The plot pane's controls are hand-built Qt** with ~100 lines of manual
   bidirectional syncing (`_sync_controls`, `_axis_syncers`, named handlers)
   that TraitsUI would provide for free — against the project's
   TraitsUI-first convention.
3. **The Fluorescence Images pane stacks everything vertically** (nav row,
   five collapsible sections, image, status), so with the sections open the
   image is squeezed and nothing can be shown "all at once". The user wants
   the device-viewer sidebar pattern: selectors collapsible to one side,
   image dominating, analysis tools as a compact vertical toolbar.

## Design

### Part 1 — Plot pane: shrinkable with scrollbars

- Wrap the plot pane's entire content (controls, canvas+table splitter,
  progress label) in a `QScrollArea` with `widgetResizable=True`,
  scrollbars as-needed in both directions.
- The canvas gets a minimum size (~300x200) so it never degenerates; when
  the dock pane shrinks below the content minimum, scrollbars appear
  instead of the pane locking.
- Split the controls into two rows so the un-scrolled minimum width is much
  narrower: row 1 = plot stat + X/Y axis controls; row 2 = export dpi +
  format + Save plot.

### Part 2 — Plot pane: TraitsUI controls

- Replace the hand-built Qt controls with a TraitsUI View bound to the
  session's real traits:
  - `plot_stat` — EnumEditor over `PLOT_STATS` showing `PLOT_STAT_LABELS`.
  - `figure.x_auto` / `figure.x_min` / `figure.x_max` (min/max
    `enabled_when="not x_auto"`); same for Y.
  - `figure.export_dpi`, `figure.export_format` — already Enum traits, so
    default editors give the combos for free.
- The View is defined against `AnalysisSession`/`FigureSettings`
  (two-object context or dotted Items — implementer's choice), and the pane
  **rebuilds the controls subpanel on session swap** (observe `session` →
  dispose old `ui`, `edit_traits(kind="subpanel")` against the new session,
  swap the widget in the layout). Rationale: TraitsUI dotted-name Items
  resolve intermediate objects at UI-build time and are not trusted to
  re-bind when `session` is replaced wholesale; a rebuild is deterministic,
  cheap (a small controls row, swapped only on experiment change), and
  deletes all manual syncing.
- "Save plot…" becomes a `Button` trait on `RoiAnalysisModel` (tool state,
  next to the other action buttons); the dock pane observes it and calls
  `_save_figure(self.canvas)` since only the pane owns the canvas.
- **Deleted**: `_sync_controls`, `_axis_syncers`, `_on_plot_stat_changed`,
  the combo/checkbox/spinbox construction code and their observer
  registrations/removals in `destroy()`.
- **Stays Qt deliberately** ("unless absolutely needed"):
  - the matplotlib canvas — inherently a Qt widget;
  - the ROI stats table — TraitsUI `TableEditor` is the component with the
    known cell-editor-commit crash class (see
    `traitsui-table-modal-defer`), and the per-row color/line/marker/size
    editors would force custom columns straight back into it;
  - the structural shell (scroll area, splitter, layouts) — pyface
    `DockPane.create_contents` is widget assembly by contract.

### Part 3 — Fluorescence Images pane: sidebar layout (Option A)

Restructured entirely within TraitsUI in `view.py` — no Qt shell:

```
+--+-----------+--------------------------+---+
| <| SIDEBAR   | nav row     3/12  info   | o |   o = analysis icon
|  | (scroll,  +--------------------------+ # |       buttons, one
|  | hideable) |                          | e |       per row
|  |>Experiments      IMAGE PREVIEW       | d |
|  |  combo    |      (zoom / pan)        | x |
|  |  seek ----|                          | c |
|  |>Image Grps|                          | s |
|  |>Images    +--------------------------+ r |
|  |>Contrast  | (x, y) = 1234   progress |   |
+--+-----------+--------------------------+---+
```

- **Top-level**: `HGroup( chevron column, HSplit(sidebar, viewer column),
  analysis column )`.
- **Chevron column**: a thin `UItem` on a new `show_sidebar = Bool(True)`
  model trait with `IconToggleEditor` (chevron-left/right glyphs) — hides
  the whole sidebar in one click, device-viewer style.
- **Sidebar** (`visible_when="show_sidebar"`, `scrollable=True`): the
  existing Experiments / Image Groups / Images / Contrast sections with
  their per-section collapse headers, unchanged behavior and tooltips.
- **Viewer column**: the existing nav/buttons row (folder, home, fit,
  prev, play, next, position, info) above the canvas `UItem` (springy);
  below the canvas a single status row combining `pixel_text` and
  `object.roi_analysis.progress_text`.
- **Analysis column**: the 8 analysis icon buttons as a vertical `VGroup`
  on the far right edge; the old horizontal `analysis_group` (and its
  collapse header + `show_analysis` gating) is retired — the toolbar is
  always visible, which is the point of the reorganization.
- Models/controllers/persistence untouched apart from the `show_sidebar`
  trait. The canvas editor and its observer strings are not modified.

## Error handling

No new failure modes: no I/O, no threading, no new observers on
long-lived singletons beyond the pane-scoped ones already following the
`detach()`/`destroy()` lifecycle. The rebuilt controls `ui` is disposed
before replacement (leak-free), and `destroy()` disposes the final one.

## Testing

- Existing suites must stay at baseline (185 passed + 2 known pre-existing
  failures).
- Offscreen smoke: import + construct the plot pane widgets; build the
  TraitsUI controls subpanel against a session, swap sessions, verify the
  editors now edit the new session's traits.
- The layout itself is verified manually in the GUI (user preference:
  no over-investment in view tests).

## Out of scope

- Converting the ROI stats table to a TraitsUI TableEditor.
- Persisting sidebar visibility / splitter position across restarts.
- Any behavioral change to selectors, playback, analysis actions.
