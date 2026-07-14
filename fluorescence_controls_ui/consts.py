from device_viewer.consts import PROTOCOL_RUNNING
from microdrop_style.colors import ERROR_COLOR, SUCCESS_COLOR, GREY
from pluggable_protocol_tree.consts import PROTOCOL_TREE_ROW_SELECTED

from fluorescence_controller.consts import (  # noqa: F401 (re-export)
    DEVICE_NAME, START_DEVICE_MONITORING, SEND_COMMAND, TELEMETRY,
    SET_LED, SET_LED_FREQUENCY, ALL_LEDS_OFF, ALL_LEDS_ON, BOARD_ID,
    LED_WAVELENGTHS, LED_DUTY_MIN, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX,
)

# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ").replace("Ui", "UI")
listener_name = f"{PKG}_listener"

# Main listener subscribes to all fluorescence signals
# (connected/disconnected/searching, telemetry), the run state (a running
# protocol owns the hardware — the pane's publishes are gated then), and
# the protocol tree's selected-step broadcast (snapshot live-tracking).
ACTOR_TOPIC_DICT = {
    listener_name: [
        f"{DEVICE_NAME}/signals/#",
        PROTOCOL_RUNNING,
        PROTOCOL_TREE_ROW_SELECTED,
    ],
}

# Status colors. Connected maps straight to the green "connected" color
# (no chip / "no device" intermediate sub-state).
disconnected_color = GREY["lighter"]
connected_color = SUCCESS_COLOR
halted_color = ERROR_COLOR

# Per-mode LED defaults (the standalone app's config.yml `controller` values).
BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT = 50, 40000
FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT = 50, 40000

# Per-mode camera defaults (the standalone config values, shown in ms —
# the camera itself takes microseconds; the controller converts).
EXPOSURE_MS_MIN, EXPOSURE_MS_MAX = 1, 60_000
BR_EXPOSURE_DEFAULT, BR_GAIN_DEFAULT = 10, 0
FL_EXPOSURE_DEFAULT, FL_GAIN_DEFAULT = 20, 300

# Control-pane values persisted across sessions: model trait ->
# FluorescencePreferences trait. light_on is deliberately absent — the
# light always starts OFF regardless of how the last session ended.
PERSISTED_CONTROL_TRAITS = ["mode", "br_intensity", "br_wavelength", "br_frequency", "br_gain", "br_exposure", "fl_intensity", "fl_wavelength", "fl_frequency", "fl_gain", "fl_exposure", "device_viewer_stream", "auto_exposure", "auto_gain"]

# Image-viewer display-window values persisted across sessions: model trait
# -> FluorescencePreferences trait. window_max restores BEFORE window_min:
# window_min's upper bound rides window_max, so the reverse order could
# reject a stored min above the not-yet-restored max.
PERSISTED_VIEWER_TRAITS = {
    "auto_contrast": "fluorescence_viewer_auto_contrast",
    "window_max": "fluorescence_viewer_window_max",
    "window_min": "fluorescence_viewer_window_min",
}

# ZWO ASI camera driver for Windows (from the standalone app's README): the
# camera needs this driver installed before it shows up on Windows.
ASI_DRIVER_URL = ("https://dl.zwoastro.com/software"
                  "?app=AsiCameraDriver&platform=windows86&region=Overseas")

#: Filename patterns counted as viewable images when browsing a folder.
IMAGE_PATTERNS = ("*.png", "*.tif", "*.tiff", "*.jpg", "*.jpeg", "*.bmp")
#: Rescan cadence for newly landed captures / experiment switches (ms).
DISCOVERY_POLL_INTERVAL_MS = 2_000
#: Auto-advance cadence while the slideshow is playing (ms).
SLIDESHOW_INTERVAL_MS = 1_500

