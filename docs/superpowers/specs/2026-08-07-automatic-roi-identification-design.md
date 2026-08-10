# Automatic ROI Identification (SAM) — Design

Resolves issue #11. Adapts the standalone `droplet_roi` prototype
(`~/PycharmProjects/labelme/droplet_roi`, PySide6 + osam/ONNX SAM) into the
image viewer's ROI analysis subsystem: droplets are found by a segmentation
model instead of drawn by hand, reviewed before they become ROIs, and tracked
across the series for drift.

## Scope

Three tools, all driven by one SAM model selected in Preferences
(default `efficientsam:latest`, "EfficientSam (accuracy)"):

1. **AI picker** — click a droplet, get one ROI (point-prompt segmentation).
2. **Detect all** — point-grid sweep of the frame proposes every droplet-like
   region as *candidates*, filtered by significance (grid votes) and size,
   reviewed and accepted before entering the session.
3. **Track drift** — re-segment the session's ROIs across later frames every
   N frames, writing capture-time overrides.

Out of scope for v1: a detection-region rectangle (detect-all sweeps the
whole frame), electrode-layout seeding (issue #11's alternative path),
per-candidate manual geometry adjustment before accept (accept first, then
edit with the normal handles).

## Model selection & weight download

The prototype's full model list is offered in the plugin's Preferences tab
(`FluorescencePreferences` / `FluorescencePreferencesPane` in
`preferences.py`): EfficientSam speed/accuracy, Sam speed/balanced/accuracy,
Sam2 speed/balanced/large — a new
`fluorescence_ai_model = Str("efficientsam:latest")` trait rendered as a
display-name dropdown in a new "AI ROI detection" group.

Weights download **only when needed** (`osam` cache under `~/.cache/osam`;
cached = `model_type.get_size() is not None`), at two trigger points:

- **On selection**: when the preference changes to a model that is not
  cached, the ported labelme download dialog (`download_ai_model` from the
  prototype's `download.py`: per-file byte progress, window-modal,
  cancellable) runs immediately. **Cancel or failure reverts the preference
  to the previously selected model** — the selection only sticks once the
  weights exist. Already-cached models switch instantly, no dialog.
- **On first tool use**: launching any AI tool first ensures the selected
  model is cached (covers the never-downloaded default); the same dialog
  runs, and cancel aborts the tool cleanly without changing the preference.

The observation lives in the image-viewer side (the controller observes the
preferences helper trait), since the preferences pane itself cannot host the
dialog flow. The Qt download dialog is ported as
`fluorescence_controls_ui/image_viewer/sam_download.py` (it is Qt code, so it
stays out of the Qt-free `analysis/` package).

## Architecture

**New Qt-free module `fluorescence_controls_ui/image_viewer/analysis/sam_detect.py`**
(sibling of `roi_compute.py`; numpy/cv2 in-and-out; `osam` imported lazily):

- Ports from the prototype: `OsamSession` (+ DirectML encoder routing patch),
  `SamRefiner` (1920-wide downscale, embedding cache, `segment_point`,
  `segment_grid` with degenerate-mask rejection), `suppress_with_votes`
  (IoU/containment dedup summing votes), percentile `normalize_to_uint8`
  contrast stretch (the viewer's 16-bit arrays are stretched before encoding).
  The refiner is built for the preference-selected model and rebuilt (caches
  dropped) when the preference changes; `MODEL_OPTIONS` (name ↔ display
  label) is ported alongside it for the Preferences dropdown.
- `Candidate` dataclass replaces the prototype's `Roi`: carries **both** the
  simplified polygon outline (`cv2.approxPolyDP`) and the fitted ellipse
  (`cv2.fitEllipse`), plus `votes`, `size` (mean ellipse diameter px),
  `score`, `prompt` point, and a `discarded` flag. The polygon/ellipse choice
  is applied at accept time via `geometry_for(kind)` → a plugin
  `(kind, geometry)` pair (flat float lists per `roi_geometry.py`).
- `sam_available() -> bool` — lazy import probe; the UI keys off it.

**Threading** reuses the `roi_batch.py` idiom (shared `ThreadPoolExecutor` +
`queue.SimpleQueue` drained by the dock pane's existing timer), not the
prototype's QThreads. Tracking keeps the prototype's pipelining: a prefetch
thread loads + encodes frame k+1 while frame k's decodes run in a small pool.
One cancellation idiom throughout: a generation counter/event checked between
steps; pressing the track button again stops early, finished frames kept.

**Drift mapping**: each tracked frame emits `(capture_time, {roi_id:
(kind, geometry)})`; the GUI drain applies `roi.apply_edit(capture_time,
geometry)`. Skipped frames inherit via `effective_geometry` — no `Roi` model
changes, no new persistence (overrides already round-trip through
`roi_store.py`). Track prompts start at each ROI's current effective center
(`centre_of`) and chain the newly found center forward.

## UI

**Toolbar** (existing `analysis_toolbar` in `view.py`):

- *AI picker* — `IconModeButtonEditor` arming `interaction_mode="ai_pick"`;
  each canvas click fires one point-prompt job; the result commits
  immediately through `_create_roi` (user-asserted; exempt from the
  significance filter). First click on a frame pays the encode (busy cursor +
  status text); later clicks are sub-second.
- *Detect all* — `IconButtonEditor`; runs the grid sweep with progress
  ("n/144 points"); results land in `RoiAnalysisModel.candidates`.
- *Track drift* — `IconButtonEditor` with active state; press again to stop.

**Candidate review**: candidates render on the canvas as visually distinct
outlines (dashed, dedicated color) via the ball-reference pattern — items
keyed outside `session.rois`, never persisted. Clicking a candidate toggles
`discarded`. While candidates exist, an **Accept n** button (count = filter
survivors) and a **Clear** button are visible; Accept commits survivors in
one bulk `_create_rois()` call; re-running Detect all replaces the set.

**Options row** (beside the rolling-ball controls under the image, visible
when `sam_available()`): **Significance** spinner (min votes, default 2),
**Min size** spinner (mean diameter px, default 0), **Output** toggle
(polygon | ellipse, default polygon), **Drift check every N frames** spinner
(default 3). Significance/size filter the candidate preview live and
non-destructively. The filters apply only to candidates — `Track drift`
takes all session ROIs, since those were already accepted.

**AI unavailable**: the three glyphs render disabled, tooltip "AI support not
installed — Help → Install AI support". New Help-menu action (in `menus.py`)
**Install AI support…**: runs `pixi add --pypi osam` (plus
`onnxruntime-directml` on Windows) as a background subprocess from the pixi
project root, progress dialog via `microdrop_application.dialogs.pyface_wrapper`,
re-probes `sam_available()` on success and enables the tools live; on failure
shows pixi's output and stays disabled. Weight downloads are never silent —
they always go through the cancellable dialog described in "Model selection &
weight download".

## Controller & model changes

`RoiAnalysisModel` gains: `ai_pick_button`, `ai_detect_button`,
`ai_track_button`, `ai_accept_button`, `ai_clear_button` (Buttons);
`candidates` (List); `ai_significance = Int(2)`, `ai_min_size = Int(0)`,
`ai_output_kind = Enum("polygon", "ellipse")`, `ai_drift_interval = Int(3)`;
`ai_available = Bool` (probed at startup and after install); progress/status
strings. `interaction_mode` gains `"ai_pick"`.

`RoiAnalysisController` gains the three job launchers (each preceded by the
ensure-model-downloaded gate), the queue drain hook (called from the dock
pane's existing `_drain_timer`), candidate filtering
(`_filtered_candidates()`), `_create_rois(pairs, base_anchor)` — a bulk
sibling of `_create_roi`: N appends, one `_save_config()`, one
`_restart_batch_if_running()`, instant stats per ROI — and the
`fluorescence_ai_model` preference observer (download-or-revert flow,
refiner rebuild on a successful switch).

`RoiCanvasLayer` gains a candidate item set (distinct pen; hit-testing to
toggle discard) and an `ai_pick` click callback, following the existing
callback wiring in `view.py`.

## Error handling

Worker failures surface as one status-line message + log entry (no dialog
storms). A click that segments nothing → status "no droplet found here".
Encode or weight-download failure disarms the active tool. Frames where
tracking finds nothing keep the previous geometry (prototype behavior).
The install action reports pixi's exit code/output and leaves tools disabled
on failure.

## Dependencies & packaging

`osam`/`onnxruntime` are NOT hard dependencies. `pyproject.toml` gains an
optional extra (e.g. `[project.optional-dependencies] ai = ["osam"]`).
The conda package is unaffected; users opt in via the Help-menu installer
(pixi pypi install). DirectML acceleration is best-effort (the provider
patch no-ops when unavailable).

## Testing (light, per project convention)

- `test_sam_candidates.py`: fake `Detection` masks → `Candidate` polygon and
  ellipse geometry (against `roi_geometry.normalize`), vote merging through
  `suppress_with_votes`, significance/size filtering, `geometry_for` output.
- Controller-level (pattern of `test_roi_editing.py`): candidates → toggle
  discard → accept → `session.rois` contains exactly the survivors, one
  save; picker result commits immediately.
- The osam session itself is not exercised in CI; manual GUI verification
  with real captures covers encode/decode, tracking, and the installer.
