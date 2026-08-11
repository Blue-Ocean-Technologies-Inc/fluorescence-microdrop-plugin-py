# Heater-log temperature x-axis (design)

Date: 2026-08-11
Branch: `feat/heater-log-temperature-axis`
Issue: #12 — Integrate heater logs with the ROI series

## Problem

The ROI plot reads intensity against elapsed time; the heater plugin
logs temperature against the same wall clock, into
`<experiment>/heater_logs/<YYYYMMDD_HHMMSS>.jsonl` (1 Hz `TEMP`
lines: naive local ISO `timestamp`, `temperatures` = {sensor: °C}).
A melt curve wants intensity against temperature — the fit midpoint
should be a °C, not a second.

## Decision

Join the two datasets on time, and let the user swap the plot's
x-axis between Time (s) and Temperature (°C) from the Axes tab. The
swap happens in `derive_series`, so fits, d² and fastest-change all
follow the chosen x. The CSV export always carries a
`temperature_c` per frame when a heater log is found.

## Components

### `analysis/heater_log.py` (new, pure, Qt-free)

- `read_heater_samples(folder, start_epoch, end_epoch)` →
  `[(epoch, {sensor: °C})]` sorted by time. `*.jsonl` files sort by
  the stamp in their name; a file covers from its own stamp until
  the next file's, and only files overlapping the capture range are
  parsed. Only `"_frame": "TEMP"` lines count; their naive ISO
  timestamp is local time → epoch. Samples kept for the range ±60 s
  so interpolation has bracketing points. Malformed lines skipped;
  missing/empty folder → `[]`.
- `sensors_in(samples)` → sorted sensor names (feeds the dropdown).
- `temperature_at(samples, sensor, epochs)` → linear interpolation
  of the named sensor ("mean" = per-line mean of all sensors) at
  each epoch; NaN outside the sampled range.

### Model (`roi_model.py`)

- `AnalysisSession.heater_log_dir = Str()` — persisted per
  experiment (top-level in roi_config.json, like `plot_stat`).
  Empty means `<experiment>/heater_logs`, resolved by the
  controller.
- `AnalysisSession.heater_samples` — loaded samples (not
  persisted), set by the controller.
- `FigureSettings.x_axis = Enum("time", "temperature")`,
  `heater_sensor = Str("mean")` — persisted in `_FIGURE_FIELDS`.

### Series derivation (`plot_series.py`)

When `figure.x_axis == "temperature"`, `derive_series` replaces the
elapsed x with `temperature_at(session.heater_samples, sensor,
capture_epochs)`. NaN x (frame outside log coverage) breaks the
line there; the plot pane counts those frames in a note like the
existing hidden-point notes. Points stay in capture order — a
cool-down leg traces back over the ramp rather than being sorted
away.

### Controller (`roi_controller.py`)

Loads `heater_samples` when the heater folder changes, when the
x-axis flips to temperature, and before an export; cached by the
log files' mtimes so redraws never re-read. Resolves the default
folder from the experiment directory.

### UI (`plot_pane.py`, Axes tab)

- "X axis" dropdown: Time (s) / Temperature (°C).
- Visible when temperature: heater-folder text field + browse
  button (directory dialog), and the sensor dropdown ("mean" +
  sensors discovered in the loaded logs). X label follows the
  choice.

### CSV export (`roi_controller.py`, `roi_store.py`)

Each row gains `temperature_c` after `elapsed_sec` — the selected
sensor's interpolated value, blank when unknown — filled whenever a
heater log is found, whatever x-axis is displayed. The sensor name
is recorded in the constant trailer columns beside `ring_gap_px`.

### Legacy capture timestamps (`discovery.py`)

`capture_timestamp()` gains a second pattern for the standalone
app's `2026-05-04_18-28-44` naming, parsed as **local** time (that
app wrote local stamps; the plugin's own `2026_05_04-18_28_44`
format stays UTC). Without it those captures fall back to copy-time
mtimes and cannot join to anything.

### Demo data (`examples/generate_heater_demo_log.py`)

Reads a captures folder, synthesizes a 1 Hz heater log across its
capture span — hold ~20 °C, linear ramp to ~95 °C, hold — two
near-identical thermistors with light noise, filename from the
first stamp. Run once to create
`Experiments/2026_08_11-19_34_50/heater_logs/20260504_182844.jsonl`.

## Testing

User verifies through the GUI (their call — mostly UI work). The
pure pieces (`heater_log.py`, timestamp parsing, the x swap) keep
testable shapes for later.
