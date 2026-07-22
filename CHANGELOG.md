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
