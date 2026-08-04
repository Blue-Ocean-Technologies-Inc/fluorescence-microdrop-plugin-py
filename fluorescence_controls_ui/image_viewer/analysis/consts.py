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

#: Coalescing delay (ms) between an analysis-state notification and the
#: plot redraw — a drain burst paints once.
ROI_PLOT_COALESCE_MS = 100

#: Below this the plot canvas stops shrinking and the plot pane's
#: scroll area takes over with scrollbars instead.
ROI_PLOT_CANVAS_MIN_WIDTH = 300
ROI_PLOT_CANVAS_MIN_HEIGHT = 200

#: Smallest ROI dimension (radius / box side, px) a canvas drag may create.
MIN_ROI_SIZE_PX = 3.0

#: Rotation-grip snap (degrees) while Shift is held.
ROTATE_SNAP_DEGREES = 15.0

#: Default per-ROI plot colors, cycled at creation (matplotlib tab10).
DEFAULT_ROI_COLORS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)

#: Plot pane view modes: the intensity chart, the fits' second-
#: derivative curves, or the per-ROI time-of-fastest-change bars.
VIEW_MODES = ("intensity", "second_derivative", "fastest_change")
VIEW_MODE_LABELS = {"intensity": "Intensity",
                    "second_derivative": "2nd derivative",
                    "fastest_change": "Fastest change"}

#: Persisted computed-stats store inside ANALYSIS_DIR_NAME.
ROI_STATS_FILENAME = "roi_stats.json"

#: Seconds of quiet since the last change before a debounced write of
#: the stats store.
STATS_SAVE_DEBOUNCE_S = 2.0
