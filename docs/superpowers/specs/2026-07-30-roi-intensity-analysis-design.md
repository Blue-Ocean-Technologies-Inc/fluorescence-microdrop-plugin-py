# ROI Intensity Analysis in the Fluorescence Image Viewer — Design

Date: 2026-07-30
Status: Approved
Branch: `feat/roi-intensity-analysis`

## Goal

Embed ROI-based intensity analysis (ported from the standalone
`fluorescence-camera-ui` app) into the fluorescence image viewer
(`fluorescence_controls_ui/image_viewer/`): draw circle/rectangle ROIs on the
canvas, compute per-ROI intensity statistics across the currently filtered
image series, plot intensity vs time in a dedicated dock pane, cache results
with implicit invalidation, and export CSV to the experiment folder.

## User flow

1. User filters the series with the existing burst (image-group) and
   wavelength dropdowns. The burst filter gains an **"All"** option mirroring
   `WAVELENGTH_FILTER_ALL`, so the image scrubber can span every group.
2. New toolbuttons on the viewer's existing button row (`IconButtonEditor` /
   `IconToggleEditor` glyph buttons): **draw circle**, **draw rect**,
   **edit/move**, **delete ROI**, **clear ROIs**, **calculate & plot**,
   **export CSV**, **reset cache**.
3. Drawing or editing an ROI immediately computes its stats for the current
   image (single background call) and shows them in the viewer's info text.
4. **Calculate & plot** computes stats for every ROI across every filtered
   image (cache-aware, parallel), live-streaming results into the new
   **ROI Plot dock pane**: matplotlib canvas, one line per ROI,
   x = elapsed seconds from first capture (filename UTC timestamp, mtime
   fallback), progress readout `done/total`.
5. **Export CSV** writes results plus the ROI definitions JSON into
   `<experiment>/analysis/`.

## ROI semantics: shared set + forward overrides

- One shared ROI set applies to all images. Global image order =
  chronological order across the experiment (the existing discovery sort).
- Creating an ROI (on any image) defines its **base geometry**, applying
  everywhere.
- Editing an ROI while viewing image *P* upserts an **override anchored at
  P**, applying from P forward (drift compensation). Editing at or before the
  ROI's base anchor updates the base instead.
- Effective geometry for image *I* = override with the greatest anchor ≤ *I*,
  else base.
- Reset options: clear overrides only, or clear all ROIs.

## Caching & invalidation

In-memory dict keyed by `(image_path, image_mtime, roi_id, geometry_hash)` →
stats dict.

The geometry hash makes invalidation implicit: an ROI edit changes the
effective hash only for images its override covers — those keys miss and
recompute; everything else stays hot. "Reset cache" clears the dict. No
manual dirty-tracking. The cache is not persisted; recomputation is cheap and
cache-aware within a session.

## Compute layer (Qt-free, spawn-safe)

- `roi_compute.py` — pure functions ported from the original
  `image_tools.py` `ROIManager`: interior mask + 2 px outline-ring mask per
  ROI (circle/rect); stats = mean/std/median/min/max/count for both masks;
  image loaded 16-bit via `cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE`.
  Module-level worker `compute_image(image_path, effective_rois) ->
  {roi_id: stats}` so a Windows-spawn `ProcessPoolExecutor` can import it.
  Unit-testable with synthetic arrays.
- `roi_batch.py` — orchestration: a daemon thread (the plugin's established
  off-GUI pattern) builds the work list (filtered images × effective
  geometries), skips cache hits, fans misses out to a `ProcessPoolExecutor`,
  and pushes results onto a thread-safe queue with progress counts. Falls
  back to a `ThreadPoolExecutor` if the process pool is unavailable.
- Per the MVC directive, the model is only mutated on the GUI thread: the
  plot pane's poll `QTimer` drains the queue into the model; Traits observers
  update plot and info text.

## Model / controller / view additions

- `roi_model.py` — `Roi(HasTraits)` (id, name, kind, geometry, overrides) and
  `RoiAnalysisModel(HasTraits)` (roi list, cache, progress, plot-ready series
  results). Qt-free.
- `roi_items.py` — `QGraphicsEllipseItem` / `QGraphicsRectItem` subclasses
  with drag-move and corner-resize handles on the existing `_ImageView`
  scene; an interaction-mode enum (pan / draw-circle / draw-rect / edit)
  toggled by the toolbuttons. Item edits flow controller → model, never
  view → model directly.
- Controller additions wire the buttons, ROI-edit anchoring, instant
  single-image compute, batch start/cancel, and export.
- On image navigation the canvas redraws ROI items at their *effective*
  geometry for the shown image.
- Burst "All" filter: `BURST_FILTER_ALL` prepended to `burst_names`,
  special-cased in `_visible_paths()`, `rescan()`, and seek logic, mirroring
  the wavelength filter.

## Plot dock pane

`FluorescenceRoiPlotDockPane(TraitsDockPane)` contributed by
`FluorescenceControlsUiPlugin`, sharing the `RoiAnalysisModel` instance with
the viewer pane (same plugin, direct sharing is fine). Embedded matplotlib
`FigureCanvasQTAgg` + navigation toolbar (zoom/pan/save-PNG). Lines
appear/extend as batch results stream in.

## Persistence

- **CSV**: `<experiment>/analysis/roi_intensities_<group>_<wavelength>_<UTC>.csv`
  — one row per image (`index, time, elapsed_sec, filename, group,
  wavelength`) then per-ROI columns `<name>_mean/std/median/min/max/count`
  and `<name>_outline_*`.
- **ROI definitions**: `roi_config.json` (bases + overrides) auto-saved to
  `<experiment>/analysis/` on change and auto-loaded when the experiment is
  opened, so ROIs survive restarts.

## Error handling & edge cases

- Unreadable/corrupt image → skipped, logged, plotted as a gap; failure count
  in progress text.
- ROI partially/fully outside image bounds → mask clipped; zero-pixel mask
  yields NaN stats, plotted as a gap.
- Filter changed or ROI edited mid-batch → batch cancelled and restarted
  (work list is a snapshot; cancel flag checked between dispatches).
- Process pool unavailable → transparent thread-pool fallback.

## Testing

Unit tests only, for the pure pieces: `roi_compute` masks/stats against
synthetic arrays, override-resolution logic, cache-key behavior. Placed in
the plugin's existing non-hardware test directory. GUI is exercised manually.
