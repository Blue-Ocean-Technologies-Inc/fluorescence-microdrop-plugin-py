# ROI Analysis Persistence and Plot Styling — Design

Date: 2026-07-31
Status: approved (Approach 2: per-experiment session + self-deriving plot pane)
Builds on: `2026-07-30-roi-intensity-analysis-design.md` (branch
`feat/roi-intensity-analysis`, HEAD `7ef1d90`)

## Problem

The ROI analysis feature computes and caches intensity stats, but the
computed values live only in memory: re-entering an experiment restores
the ROIs (from `roi_config.json`) yet shows an empty plot until the user
presses Calculate again. The plot pane is also fed by the viewer
controller (`_rebuild_plot_series` pushes `plot_series` into the shared
model), instead of deriving its own picture from observed state. And the
plot itself is fixed: hard-coded mean, matplotlib default colors, one
readout line of instant stats that each new ROI overwrites.

## Goals

1. Computed stats persist per experiment and load automatically — the
   plot appears as soon as the user returns to an experiment, for the
   current filters, with no Calculate press.
2. The plot dock pane becomes an independent observer: it watches
   (session, filters, styles, chosen stat) and derives its series
   itself. Same shared model across the board; observer pattern, no
   pushed series.
3. Users can rename ROIs (legend follows), style each ROI line
   (color, line style, marker, size), set axis limits, choose the
   plotted stat (including background-corrected mean), and export a
   publication-quality figure (format + DPI).
4. A per-ROI value table below the plot replaces the single-slot
   instant-stats readout.

## Non-goals

- No per-filter result files: cached stats are keyed by
  (image, ROI, geometry) and are filter-independent; filtering is a
  view-time derivation. The timestamped CSV remains a user-facing
  export only, unchanged.
- No cross-plugin/actor decoupling — both panes live in this plugin
  and share one in-process model.
- No changes to the compute layer (`roi_compute`, batch runner
  semantics) beyond where results are stored, plus pool warm-up.

## Decisions (user-confirmed)

| Question | Decision |
| --- | --- |
| Scope | One design, phased build: persistence/observer rework first, then table + styling. One feature branch continuing from `feat/roi-intensity-analysis`. |
| Canonical store | JSON stats store (`analysis/roi_stats.json`); CSV stays export-only; `roi_config.json` gains names/styles/figure settings. |
| Table values | Current viewer image's stats per ROI, live-updating (scrubbing, instant calcs). |
| Style persistence | Per experiment, saved with the session (no global defaults layer). |
| Plotted stat | Dropdown: mean (default), background-corrected mean (interior mean − outline-ring mean), median, min, max, outline mean. Persists per experiment. |

## Architecture

### AnalysisSession (new, Qt-free HasTraits)

Everything belonging to one experiment, swapped wholesale on experiment
change:

- `directory = Str()` — captures dir this session was loaded from ("" =
  no experiment).
- `rois = List(Instance(Roi))` — moves here from `RoiAnalysisModel`.
- `stats = Dict()` — the computed-stats store; same key tuple as today
  `(str(path), mtime, roi_id, kind, tuple(geometry))` → stats dict.
- `stats_revision = Int()` — bumped after every drain absorption and
  after load; Dict item writes do not notify, observers watch this.
- `plot_stat = Enum("mean", "bg_corrected", "median", "min", "max",
  "outline_mean")` — default `"mean"`.
- `figure = Instance(FigureSettings)` — `x_auto/y_auto = Bool(True)`,
  `x_min/x_max/y_min/y_max = Float`, `export_format`
  (png/svg/pdf/tiff, default png), `export_dpi` (150/300/600, default
  300).

`Roi` gains `style = Instance(RoiStyle)`: `color` (hex Str, default
assigned from a palette cycle at creation), `line_style`
Enum(solid/dashed/dotted/dashdot), `marker` Enum(none, ".", "o", "s",
"^", "x"), `marker_size` Float.

### RoiAnalysisModel (existing singleton, slimmed)

Keeps tool state only: `interaction_mode`, `selected_roi_id`, button
events, canvas events, `progress_text`, batch counters. Gains:

- `session = Instance(AnalysisSession)` — never None; empty session
  when no experiment.
- `filtered_paths = List(Str)` and `current_image_path = Str()` —
  thin mirrors maintained by the analysis controller (it already holds
  the viewer model; it observes `paths` and `current_path` and copies
  them over) so the plot pane and table need no reference to the
  viewer model.

Removed: `rois`, `cache`, `plot_series`, `plot_revision` in phase 1;
`roi_info_text` in phase 2 when the table replaces it. All existing
consumers (canvas layer, controller, view bindings) re-point to
`model.session.*` or the mirrors.

### Controller (session lifecycle + compute, slimmed)

- `browsed_directory` change: save outgoing session (config + stats) →
  build new session from disk → assign `model.session` (one trait
  swap; every observer reacts).
- Batch/instant drains write into `session.stats` and bump
  `stats_revision`. `_rebuild_plot_series` is deleted.
- `_missing_work`, CSV export, reset/delete/clear read the session.
- Reset dialog semantics unchanged (cache only vs cache + drift
  overrides), now also deleting/rewriting the persisted stats file.
- Pool warm-up: `_shared_executor()` is invoked once at dock-pane
  startup (off the GUI thread) so the first batch skips Windows spawn
  latency.

### Plot dock pane (self-deriving observer)

Observes: `session` (swap), `session:stats_revision`,
`session:rois.items` (+ per-ROI name/style traits),
`session:plot_stat`, `session:figure:+`, `filtered_paths.items`. Any
notification schedules a coalesced redraw via a single-shot timer (a
drain burst paints once). The 500 ms poll timer is removed.

Series derivation (in the pane, pure function of observed state): for
each ROI × filtered path, look up stats by key; x = capture time
elapsed from the first filtered image; y = chosen stat
(`bg_corrected` = mean − outline_mean, NaN if either missing); NaN
gaps preserved. Legend = ROI names; artist styling from `RoiStyle`.

## Persistence

Files live in `<experiment>/analysis/` (existing helper):

- **`roi_config.json`** (extended, versioned): per-ROI `name`, `kind`,
  `geometry`, `base_anchor`, `overrides`, `style{...}`; session-level
  `plot_stat` and `figure{...}`.
- **`roi_stats.json`** (new, versioned): `{"version": 1, "entries":
  [{"path", "mtime", "roi_id", "kind", "geometry", "stats"}]}` — a
  lossless dump of the store. Load rebuilds the dict; entries that no
  longer match anything (moved ROI, changed file) are simply never
  looked up, so invalidation stays automatic. Unknown versions load as
  empty with a warning.

Save policy: debounced (~2 s single-shot GUI-thread timer) after
drain absorptions, ROI/name/style/figure edits; immediate save on
batch finish and on experiment switch before the swap. Corrupt or
missing files → empty store + logged warning; save failures surface in
`progress_text`.

## ROI table + figure controls (phase 2, in the plot dock pane)

Plain Qt (matching the pane's construction), below the canvas:

- **Table**, one row per ROI: editable Name; color swatch button
  (QColorDialog); line-style combo; marker combo; size spinbox; then
  read-only live stats for `current_image_path` (mean, bg-corrected,
  median, min, max, count) sourced from the session store — updates on
  scrub and when instant results land. Replaces the single-slot
  `roi_info_text`.
- Rename propagates everywhere by construction (canvas label, legend,
  config, future CSV headers all read `roi.name`). Names are
  free-form; CSV export already sanitizes.
- **Controls row**: plot-stat dropdown; axis X/Y min/max fields each
  with an Auto checkbox; export format combo, DPI combo, and a Save…
  button (pyface file dialog defaulting into the experiment's
  `analysis/` folder) rendering via `figure.savefig` at the chosen
  DPI/format.

## Phasing

- **Phase 1 — persistence + observer rework:** AnalysisSession +
  FigureSettings/RoiStyle traits (styles stored but defaults only),
  both persistence files, session lifecycle, mirrors, plot-pane
  observer rework (mean only), pool warm-up. Delivers "the plot is
  there when I come back."
- **Phase 2 — table + styling + export:** ROI table with rename and
  live stats, style editing, stat selector, axis controls,
  publication export.

## Error handling

- Corrupt/missing persistence files: load empty, log warning, never
  block the pane.
- Save failure: warning in `progress_text`, retry on next debounce.
- Stat missing from a stored entry (older store): NaN point.
- Session swap mid-batch: existing cancel-on-switch behavior is kept;
  stale results die with the old queue.

## Testing (kept light per project convention)

- Session save/load round-trip (config + stats, versioned, corrupt
  file tolerance).
- Series derivation: filter subsetting, elapsed axis, bg-corrected
  math, NaN gaps.
- Style/name persistence round-trip.
- GUI behavior verified manually by the user.
