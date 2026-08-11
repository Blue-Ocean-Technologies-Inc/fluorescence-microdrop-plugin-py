## v2.3.0 (2026-08-11)

### Feat

- **controls-ui**: bulk exclude/include images before or after
- **controls-ui**: log the actual SAM session providers
- **controls-ui**: add zoom in/out buttons beside fit
- **controls-ui**: zoom sensitivity setting in the Advanced group
- **controls-ui**: hovered-pixel readout as a bottom-right canvas HUD
- **controls-ui**: scrollable advanced rows and analysis toolbar
- **controls-ui**: fast-tracking and GPU-encoder preferences
- **controls-ui**: Exclude-from-analysis checkbox under the seek slider
- **controls-ui**: analysis consumers skip excluded images
- **controls-ui**: per-experiment excluded-images set on the session
- **controls-ui**: coupled max-size filter for AI candidates
- **controls-ui**: collapsible measurement-settings row
- **controls-ui**: collapsible clusters on the analysis toolbar
- **controls-ui**: drift-check progress in the status readout
- **examples**: synthetic drift-demo series for the AI tracker
- **controls-ui**: Help-menu AI support installer and optional extra
- **controls-ui**: AI toolbar glyphs and detection options row
- **controls-ui**: candidate preview layer and AI-pick clicks on the canvas
- **controls-ui**: AI ROI controller with candidate accept flow
- **controls-ui**: cancellable SAM weight download dialog
- **controls-ui**: AI model preference and analysis-model AI traits
- **analysis**: SAM job runner (pick/detect/track) off the GUI thread
- **analysis**: port osam session and SamRefiner
- **analysis**: SAM mask -> Candidate conversion with vote dedup
- **analysis**: SAM detection module skeleton with optional osam

### Fix

- **controls-ui**: give the max-size filter its own 500 px default
- **controls-ui**: raise the candidate size-filter ceiling to 50000 px
- **controls-ui**: platform-restrict the DirectML installer step
- **controls-ui**: qualify the size spinners' dynamic bound names
- **controls-ui**: progress bar fills from drift-check counts
- **controls-ui**: give the filename readout the top row's stretch
- **controls-ui**: wand_shine/eye_tracking/ink_highlighter_move AI glyphs
- **controls-ui**: significance and size filters preview live on canvas
- **controls-ui**: final-review fixes for AI ROI identification
- **controls-ui**: tree-kill installer cancel and keep step-1 success
- **controls-ui**: candidate clicks win in every canvas mode
- **analysis**: keep track_running true when a newer track supersedes
- **analysis**: use double-underscore default for SamRefiner._session

### Refactor

- **controls-ui**: group the bulk exclude/include rows, tidy spacing
- **controls-ui**: pair the AI accept/clear buttons in one cell
- **controls-ui**: tighten the pane-title separators
- **controls-ui**: drop scrollable from sidebar and advanced groups
- **controls-ui**: show the image summary in the pane title
- **controls-ui**: toolbar back to a plain column
- **controls-ui**: ball reference to the toolbar, scale readout atop advanced
- **controls-ui**: advanced settings as titled grids
- **controls-ui**: pixel and scale readouts join the Advanced row
- **controls-ui**: drop the fast-model drift-tracking option
- **controls-ui**: one Advanced dropdown over the bottom settings
- **controls-ui**: navigation beside folder buttons, reset up top
- **controls-ui**: cluster the analysis toolbar with fixed gaps
- **controls-ui**: workhorse cluster right of the folder buttons
- **controls-ui**: plot/export/clear-all buttons to the top-left

### Perf

- **controls-ui**: async latest-wins image loading with an LRU cache

## v2.2.0 (2026-08-07)

### Feat

- **analysis**: collapsible sections in the controls mockups
- **analysis**: standalone mockups for the plot controls
- **analysis**: add an outlier demo, and fix the stale plot
- **analysis**: drop outliers and smooth the drawn curves
- **analysis**: draw the rolling ball on the image as a guide
- **analysis**: record fit quality and range with the parameters
- **analysis**: write the fitted parameters beside each export
- **analysis**: move the correction settings onto the image
- **analysis**: rolling-ball background correction
- **analysis**: correct against ROIs marked as standards
- **analysis**: theme the chart, and let the pane's sections resize
- **fluorescence**: follow the app's light/dark theme
- **analysis**: set a starting value per fit parameter
- **analysis**: edit the fit equation from the table
- **analysis**: fit any equation the user types
- **analysis**: light up the armed tool, delete on Del
- **analysis**: keep draw tools armed, and copy/paste ROIs
- **analysis**: round a box's corners from a grip
- **analysis**: add the subtract-first transform
- **analysis**: draw the background ring on the canvas
- **analysis**: put the ring parameters in the cache key
- **analysis**: zoom, pan and scroll the plot pane
- **analysis**: say when the worker pool is starting
- **analysis**: count the batch progress image by image
- **analysis**: export the normalised series beside the raw
- **analysis**: apply log scales and count hidden points
- **analysis**: add log and normalise plot toggles
- **analysis**: normalise each ROI series to its own range
- **analysis**: report ROI area in the table and the CSV
- **analysis**: label the per-area axis with its unit
- **analysis**: derive integrated and per-area statistics
- **analysis**: add pixel area and its unit label
- **viewer**: add the scale controls and readout
- **viewer**: draw the map-style scale bar on the image
- **viewer**: rubber-band a scale calibration line
- **viewer**: persist a per-experiment scale calibration
- **viewer**: add the scale-bar units and snapping maths
- **analysis**: swap the plot checkboxes for in-place toggles
- **analysis**: add eye and alpha editors to the ROI table
- **analysis**: give each ROI a plot visibility and alpha
- **analysis**: draw contour ROIs by placing nodes
- **analysis**: add the contour ROI item with node grips
- **analysis**: add the polygon ROI kind and its tool mode
- **analysis**: mask contour ROIs from a vertex list
- **analysis**: draw capsule ROIs from the toolbar
- **analysis**: add a rotation grip and ellipse resizing
- **analysis**: migrate ROI kinds to ellipse/box/capsule
- **analysis**: mask rotated ellipses, boxes and capsules
- **analysis**: add canonical ROI geometry with an angle
- **analysis**: add the "Trim poor tail" plot control
- **analysis**: trim poor fits to the leading points
- **examples**: sigmoid demo disk with fastest-change ground truth
- **analysis**: plot view modes (d2 curves, fastest-change bars)
- **analysis**: persist plot view_mode figure setting
- **analysis**: sigmoid fit, first derivative, fastest-change time
- **examples**: fit-demo experiment generator with ground truth
- **analysis**: fit controls, legend toggle and equations popup
- **analysis**: draw fits, equations and derivative markers
- **analysis**: persist fit, legend and derivative-marker settings
- **analysis**: curve-fitting core with second-derivative extrema
- **viewer**: sidebar layout with vertical analysis toolbar
- **analysis**: axis limit controls and publication export
- **analysis**: ROI table with rename, styles, live stats
- **analysis**: plot stat selector and per-ROI line styling
- **analysis**: persist stats per experiment, warm pool at startup
- **analysis**: session + stats-store persistence (v2 config)
- **analysis**: add AnalysisSession, RoiStyle, FigureSettings traits
- **image-viewer**: add ROI intensity plot dock pane
- **image-viewer**: add ROI analysis toolbutton row
- **image-viewer**: orchestrate ROI batch analysis
- **image-viewer**: draw/edit ROI layer on the canvas
- **image-viewer**: persist ROI config and intensity CSV
- **image-viewer**: add ROI batch compute runner
- **image-viewer**: add pure ROI stats compute layer
- **image-viewer**: add ROI analysis model layer
- **image-viewer**: add All choice to image-group filter
- **image-viewer**: parse capture time from filenames

### Fix

- **analysis**: enable the ball controls the moment they are toggled
- **fluorescence**: keep the icon font under the themed stylesheet
- **analysis**: show the fit on opening, and repaint on refit
- **analysis**: report the sigmoid's own 4PL parameters
- **analysis**: stack the background ring above the image
- **analysis**: drop pre-ring stats entries at load
- **analysis**: measure background in a true annulus
- **analysis**: advance the batch progress and show it once
- **analysis**: format the area cell in significant figures
- **analysis**: remove bar container, not bars, on plot refresh
- **analysis**: proportional equation-table columns, compact R2
- **analysis**: make plot margins WYSIWYG and pane split draggable
- **analysis**: guard pane teardown for never-created panes
- **analysis**: address final-review findings
- **analysis**: defer capture_service import in ROI export
- **analysis**: guard handle drags in sync, heal broken pool
- **analysis**: address final-review findings
- **image-viewer**: make instant ROI stats robust to batch restarts
- **controller**: adopt the monitor's claimed serial handle
- **controller**: relinquish port on wrong-board whoami identity

### Refactor

- **analysis**: compact toggles and Bkg Ref labelling
- **analysis**: rebuild the plot controls as the reviewed tabs
- **analysis**: align the Axes table with a real Qt grid
- **analysis**: settle the controls mockup on the tabbed layout
- **analysis**: restructure the controls mockups per review
- **analysis**: name the bare numbers
- **analysis**: rename standards to background references
- **analysis**: group the stats store by image, one per line
- **analysis**: export intensities long rather than wide
- **analysis**: draw the ROI eye as a cell, not a button
- **analysis**: always show the scale bar
- **analysis**: split ROI handles and canvas layer out
- **analysis**: TraitsUI plot controls, scrollable pane
- **analysis**: plot pane derives its own series from the session
- **analysis**: move per-experiment state into AnalysisSession

### Perf

- **analysis**: run the ROI batch on threads, and show the ring as a band

## v2.1.0 (2026-07-23)

### Fix

- **firmware-upload**: drop hardcoded dev firmware path

## v2.0.0 (2026-07-22)

### Feat

- **controls-ui**: lower the camera exposure minimum to 0.032 ms
- **fluorescence**: live run mirror, per-run camera, phase folders
- **image-viewer**: experiment-wide browsing and navigation
- **controls-ui**: show a '-' placeholder for the board device id
- **controls-ui**: blank device id until the board's whoami arrives
- **controls-ui**: keep the port combo in sync with the detected port
- **controls-ui**: zip source, board device id, timeout spinner
- **uploader**: accept a .zip firmware bundle
- **deps**: declare mpremote as a conda run dependency
- **controls-ui**: Upload Firmware entry in the Fluorescence menu
- **controls-ui**: firmware-upload dialog MVC subpackage
- **controls-ui**: ferry firmware-upload signals into live_state
- **examples**: firmware-upload dialog demo
- **services**: firmware upload service implementation
- **fluorescence_controller**: Add firmware upload service
- **uploader**: port mpremote firmware uploader from standalone script
- **datamodels**: UploadFirmwareData payload and validated publisher
- **consts**: add firmware-upload topics and Pico board ids
- **chain-column**: fire entries at step start, end, or both
- **controls-ui**: Start/End capture-time toggles in params pane
- **controls-ui**: carry capture phase fields through panel/row
- **capture-chain**: per-entry capture_start/capture_end phases
- **controls-ui**: collapsible viewer sections + folder in pane title
- **controls-ui**: burst-aware image viewer with wavelength filter
- **controls-ui**: derive chain labels from tag_wavelength_index
- **controls-ui**: route-table chain view, glyph buttons, row deletion

### Fix

- **uploader**: wipe filesystem per entry, never rmdir the root
- **chain-column**: end-phase burst folder gets _end suffix
- **fluorescence_controls_ui**: Adjust controls view glyphs + layout
- **controls-ui**: re-highlight the moved row after up/down
- **controls-ui**: stale-echo guard, up/down repositioning, one-shot capture
- **controls-ui**: seek sliders count 1-based in the view
- **controls-ui**: name pane bursts by dotted path, stamp filenames
- **controls-ui**: persist run toggles, guard attach dialog mid-run

### Refactor

- **firmware-upload**: rewire onto the shared peripheral base
- **services**: route upload status lines through the logger bridge
- **examples**: demo reuses the plugin's firmware-upload dialog

## v1.0.0 (2026-07-17)

### BREAKING CHANGE

- **controls**: the `mode` trait and the `br_*` / `fl_*` scalar traits (`br_wavelength`, `br_intensity`, `br_frequency`, `br_exposure`, `br_gain`, `fl_wavelength`, `fl_intensity`, `fl_frequency`, `fl_exposure`, `fl_gain`) are removed from the pane model and from `FluorescencePreferences`; the pane is authored per capture-chain entry instead of per persisted br/fl mode.
- **protocol-controls**: the old `fluorescence` compound column (`fluorescence_on` / `fluorescence_settings` cell ids) is retired; existing protocols' per-step fluorescence settings are dropped on load and are not migrated — rebuild affected steps' chains against the new `fluorescence_chain` column.

### Feat

- **protocol-controls**: `fluorescence_chain` column — per-step ordered list of named LED/camera capture entries, replacing the single br/fl snapshot per step
- **controls-ui**: free-mode chain authoring in the pane, plus an attach-to-step dialog driven by protocol-tree row selection
- **protocol-controls**: capture-cell locking (#541) — a step with a ticked chain locks out the shared "capture" column so only one feature owns that step's imaging
- **controls-ui**: one-folder-per-burst capture path for chain and manual bursts alike
- **controls-ui**: recursive raw-capture discovery so burst folders nested under a run are found on review

## v0.4.1 (2026-07-15)

## v0.4.0 (2026-07-14)

### Feat

- **controls-ui**: stream master gate for the LED board
- **controls-ui**: own Fluorescence Settings preferences tab

## v0.3.0 (2026-07-14)

### Feat

- pane and protocol steps live-sync, apply checkbox on column
- **controller**: protocol LED apply with settle-then-ack
- **cameras**: default to auto exposure/gain and full USB bandwidth
- **cameras**: adopt auto exposure/gain values on auto toggle-off
- **image-viewer**: refresh on capture events
- **controls**: auto exposure / auto gain checkboxes
- **advanced-camera**: tabbed Advanced Fluorescence Camera Controls pane
- **cameras**: shared advanced settings + feed forwarding
- **cameras**: advanced queue, software auto-exposure, temperature poll
- **cameras**: advanced SDK API in the zwoasi wrapper
- **controls**: Device View Stream checkbox for the ASI preview
- **controls**: slider editors and float exposure for pane controls
- **protocol-controls**: register plugin in wheel + fluorescence_ui group
- **protocol-controls**: per-step fluorescence settings column
- **viewer**: 16-bit image viewer dock pane
- **controls**: per-mode camera settings persisted via preferences
- ZWO ASI camera support with bundled SDK
- live camera preview dock pane
- driver-notice preference + Help-menu driver link
- ASI driver download notice on Windows

### Fix

- **controller**: serialize and harden board serial writes
- **protocol-columns**: LED settle via ctx.sleep for honest timing
- **controls**: handle the backend's searching signal
- **controls**: restore status-bar icon lost to pane-id convention
- **controller**: raise LED PWM frequency minimum to 20 Hz
- **controls**: persist intensity values across sessions
- **camera**: stop ASI feed cleanly and show true colors

### Refactor

- embed ASI cameras in the device viewer

### Perf

- **cameras**: downscale + rate-cap the device-viewer preview
- **provider**: emit display frames only when a preview is connected

## v0.2.1 (2026-07-08)

### Fix

- identify the board via whoami, not led_help

## v0.2.0 (2026-07-08)

### Feat

- board identity probe + collapsible sections
- intensity controls as stepped spinboxes
- clickable status icon with fluorescence tooltip
- per-mode LED controls dock pane
- typed LED command handlers
- fluorescence status/controls UI package
- fluorescence backend package

### Fix

- status icon green on connect

### Refactor

- light toggle as in-place button
