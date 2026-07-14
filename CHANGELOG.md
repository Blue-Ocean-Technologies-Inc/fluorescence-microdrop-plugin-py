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
