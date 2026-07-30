"""Constants for the ROI intensity-analysis subpackage."""

#: Outline-ring thickness (px) for the perimeter stats — the standalone
#: app's ROIManager default.
OUTLINE_PERIMETER_PX = 2

#: Prefix on the outline-ring stat columns (outline_mean, outline_std, ...).
OUTLINE_STATS_PREFIX = "outline_"

#: Per-experiment folder holding analysis outputs (CSV exports and the
#: persisted ROI definitions).
ANALYSIS_DIR_NAME = "analysis"

#: Persisted ROI definitions (bases + overrides) inside ANALYSIS_DIR_NAME.
ROI_CONFIG_FILENAME = "roi_config.json"

#: Cadence (ms) of the GUI-thread timer draining finished batch results
#: into the model.
ANALYSIS_RESULT_DRAIN_INTERVAL_MS = 200

#: Cadence (ms) of the plot pane's redraw poll.
ROI_PLOT_REFRESH_INTERVAL_MS = 500

#: Smallest ROI dimension (radius / box side, px) a canvas drag may create.
MIN_ROI_SIZE_PX = 3.0
