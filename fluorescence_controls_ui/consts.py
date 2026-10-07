# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

# Microdrop package imports.
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
    MULTI_CHANNEL,
    SEND_COMMAND,
    SET_LED,
    SET_LED_FREQUENCY,
    START_DEVICE_MONITORING,
    TELEMETRY,
)
from pluggable_protocol_tree.consts import PROTOCOL_TREE_ROW_SELECTED

# Microdrop style imports.
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

# Multi-Channel mix: one proportion (% of the master intensity) per LED
# channel, trait names in LED_WAVELENGTHS order. Default 0 keeps every
# channel dark until the operator dials a mix in.
LED_PROPORTION_TRAITS = tuple(
    f"led_proportion_{index}" for index in range(len(LED_WAVELENGTHS))
)
LED_PROPORTION_MIN, LED_PROPORTION_MAX = 0, 100
LED_PROPORTION_DEFAULT = 0

# The pane's and a chain row's wavelength choices: one LED, or the
# MULTI_CHANNEL proportion mix above.
WAVELENGTH_CHOICES = (*LED_WAVELENGTHS, MULTI_CHANNEL)

# Camera defaults (the standalone config values, shown in ms — the camera
# itself takes microseconds; the controller converts).
EXPOSURE_MS_MIN, EXPOSURE_MS_MAX = 0.032, 60_000
EXPOSURE_DEFAULT, GAIN_DEFAULT = 10, 0

# Camera lead time (ms): the wait between the camera settings + LED settle
# and the frame grab, so exposure/gain have settled. On top of the LED
# settle (LED_STABILIZATION_S); 0 grabs straight after the LED ack.
CAMERA_LEAD_TIME_MS_MIN, CAMERA_LEAD_TIME_MS_MAX = 0, 60_000
CAMERA_LEAD_TIME_MS_DEFAULT = 0

# Control-pane values persisted across sessions: model trait ->
# FluorescencePreferences trait. light_on is deliberately absent — the
# light always starts OFF regardless of how the last session ended.
PERSISTED_CONTROL_TRAITS = [
    "wavelength",
    "intensity",
    "frequency",
    "gain",
    "exposure",
    "camera_lead_time_ms",
    "device_viewer_stream",
    "auto_exposure",
    "auto_gain",
    *LED_PROPORTION_TRAITS,
    "led_mix_presets",
]

# ZWO ASI camera driver for Windows (from the standalone app's README): the
# camera needs this driver installed before it shows up on Windows.
ASI_DRIVER_URL = (
    "https://dl.zwoastro.com/software"
    "?app=AsiCameraDriver&platform=windows86&region=Overseas"
)

#: strftime format of the UTC stamp embedded in capture filenames
#: (capture_service.utc_stamp writes it; the core image_viewer plugin's
#: discovery.capture_timestamp parses it back).
CAPTURE_TIMESTAMP_FORMAT = "%Y_%m_%d-%H_%M_%S"

#: QImage.save quality for capture PNGs. Qt maps PNG quality q to zlib
#: level (100 - q) * 9 // 91: 85 is level 1 — lossless like every level,
#: far faster to encode than the default 6 for a slightly larger file
#: (90 and above would store uncompressed).
CAPTURE_PNG_QUALITY = 85

#: Suffix of a capture while it is being written; the finished file is
#: renamed into place, and image discovery never matches this suffix.
CAPTURE_PARTIAL_SUFFIX = ".partial"
