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
