from microdrop_style.colors import ERROR_COLOR, SUCCESS_COLOR, GREY

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
# (connected/disconnected/searching, telemetry).
ACTOR_TOPIC_DICT = {
    listener_name: [f"{DEVICE_NAME}/signals/#"],
}

# Status colors. Connected maps straight to the green "connected" color
# (no chip / "no device" intermediate sub-state).
disconnected_color = GREY["lighter"]
connected_color = SUCCESS_COLOR
halted_color = ERROR_COLOR

# Per-mode LED defaults (the standalone app's config.yml `controller` values).
BR_INTENSITY_DEFAULT, BR_FREQUENCY_DEFAULT = 38, 315
FL_INTENSITY_DEFAULT, FL_FREQUENCY_DEFAULT = 15, 40000
