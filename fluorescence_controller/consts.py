from peripheral_device_controller_base.consts import connected_topic, disconnected_topic, searching_topic

# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ")

DEVICE_NAME = "Fluorescence"

# Fluorescence board hardware id (RP2040 / MicroPython, VID 2E8A, PID 0005).
# TODO: adjust once the real board's VID:PID is known.
FLUORESCENCE_HWID = "VID:PID=2E8A:0005"
BOARD_BAUDRATE = 115200

# Topics published by this plugin (signals)
CONNECTED = connected_topic(DEVICE_NAME)
DISCONNECTED = disconnected_topic(DEVICE_NAME)
# JSON bool: True while scanning for the board, False once connected/stopped.
SEARCHING = searching_topic(DEVICE_NAME)
# Raw measurement/telemetry lines from the board (shape TBD by the firmware).
TELEMETRY = f"{DEVICE_NAME}/signals/telemetry"
# Board identity parsed from the led_help response: JSON {"name", "leds"}.
BOARD_ID = f"{DEVICE_NAME}/signals/board_id"

# LED channels: combo/index order matches the firmware's PWM channel table
# (blue..deep_red on consecutive pins), so a UI combo index IS the led index.
LED_WAVELENGTHS = (
    "Blue (460 nm)", "Cyan (490 nm)", "Green (540 nm)",
    "Orange (600 nm)", "Red (630 nm)", "Deep Red (660 nm)",
)
LED_DUTY_MIN, LED_DUTY_MAX = 0, 100
LED_FREQUENCY_MIN, LED_FREQUENCY_MAX = 1, 100000

# Service Request Topics
START_DEVICE_MONITORING = f"{DEVICE_NAME}/requests/start_device_monitoring"
RETRY_CONNECTION = f"{DEVICE_NAME}/requests/retry_connection"
SEND_COMMAND = f"{DEVICE_NAME}/requests/send_command"
# Typed LED commands (formatted onto the board's plain-text protocol by the
# command setter): led_<index>_<duty>, ledf_<index>_<freq>, led_off, led_on.
SET_LED = f"{DEVICE_NAME}/requests/set_led"
SET_LED_FREQUENCY = f"{DEVICE_NAME}/requests/set_led_frequency"
ALL_LEDS_OFF = f"{DEVICE_NAME}/requests/all_leds_off"
ALL_LEDS_ON = f"{DEVICE_NAME}/requests/all_leds_on"

# Topics actor declared by plugin subscribes to. The listener-name key MUST
# match FluorescenceControllerBase.listener_name.
ACTOR_TOPIC_DICT = {
    "fluorescence_controller_listener": [
        f"{DEVICE_NAME}/requests/#",
        CONNECTED,
        DISCONNECTED,
    ]}
