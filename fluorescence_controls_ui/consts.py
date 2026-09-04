from device_viewer.consts import PROTOCOL_RUNNING
from fluorescence_controller.consts import (  # noqa: F401 (re-export)
    ALL_LEDS_OFF,
    ALL_LEDS_ON,
    BOARD_ID,
    DEVICE_NAME,
    LED_DUTY_MAX,
    LED_DUTY_MIN,
    LED_FREQUENCY_MAX,
    LED_FREQUENCY_MIN,
    LED_WAVELENGTHS,
    SEND_COMMAND,
    SET_LED,
    SET_LED_FREQUENCY,
    START_DEVICE_MONITORING,
    TELEMETRY,
)
from pluggable_protocol_tree.consts import PROTOCOL_TREE_ROW_SELECTED

from microdrop_style.colors import ERROR_COLOR, GREY, SUCCESS_COLOR

# This module's package.
PKG = ".".join(__name__.split(".")[:-1])
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

# LED defaults (the standalone app's config.yml brightfield `controller`
# values — the single param set uses these regardless of wavelength).
INTENSITY_DEFAULT, FREQUENCY_DEFAULT = 50, 40000

# Camera defaults (the standalone config values, shown in ms — the camera
# itself takes microseconds; the controller converts).
EXPOSURE_MS_MIN, EXPOSURE_MS_MAX = 0.032, 60_000
EXPOSURE_DEFAULT, GAIN_DEFAULT = 10, 0

# Control-pane values persisted across sessions: model trait ->
# FluorescencePreferences trait. light_on is deliberately absent — the
# light always starts OFF regardless of how the last session ended.
PERSISTED_CONTROL_TRAITS = [
    "wavelength",
    "intensity",
    "frequency",
    "gain",
    "exposure",
    "device_viewer_stream",
    "auto_exposure",
    "auto_gain",
]

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
ASI_DRIVER_URL = (
    "https://dl.zwoastro.com/software"
    "?app=AsiCameraDriver&platform=windows86&region=Overseas"
)

#: Filename patterns counted as viewable images when browsing a folder.
IMAGE_PATTERNS = ("*.png", "*.tif", "*.tiff", "*.jpg", "*.jpeg", "*.bmp")
#: Rescan cadence for newly landed captures / experiment switches (ms).
DISCOVERY_POLL_INTERVAL_MS = 2_000
#: Auto-advance cadence while the slideshow is playing (ms).
SLIDESHOW_INTERVAL_MS = 1_500

#: strftime format of the UTC stamp embedded in capture filenames
#: (capture_service.utc_stamp writes it; discovery.capture_timestamp
#: parses it back).
CAPTURE_TIMESTAMP_FORMAT = "%Y_%m_%d-%H_%M_%S"


#: Decoded frames kept in the viewer's navigation cache. Full 16-bit
#: frames run ~20 MB decoded, so this bounds the cache near 160 MB while
#: making back-and-forth seeking over recent frames instant.
IMAGE_CACHE_FRAMES = 8

#: One wheel notch's zoom on the image canvas: default factor going in
#: (going out is its reciprocal) and the range the Advanced setting
#: allows. 1.05 is barely perceptible per notch; 2.0 doubles per notch.
IMAGE_ZOOM_STEP_DEFAULT = 1.25
IMAGE_ZOOM_STEP_BOUNDS = (1.05, 2.0)
