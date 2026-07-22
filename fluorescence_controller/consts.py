from peripheral_device_controller_base.consts import (
    connected_topic, disconnected_topic, searching_topic,
    upload_firmware_topic, cancel_firmware_upload_topic,
    firmware_upload_started_topic, firmware_upload_log_topic,
    firmware_upload_finished_topic,
)

# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ")

DEVICE_NAME = "Fluorescence"

# Fluorescence board hardware id (RP2040 / MicroPython, VID 2E8A, PID 0005).
# The heater board shares this VID:PID, so the monitor also matches the
# whoami device_id before claiming a port.
FLUORESCENCE_HWID = "VID:PID=2E8A:0005"
DEVICE_ID_FRAGMENT = "fluo"
# Full whoami device_id in the board's config.json (DEVICE_ID_FRAGMENT is the
# substring the monitor greps for; the firmware-upload dialog falls back to
# this exact id when no whoami has been received yet).
FLUORESCENCE_BOARD_DEVICE_ID = "fluo_board"
BOARD_BAUDRATE = 115200

# Serial timeouts + write-retry policy (heater proxy parity). A write that
# cannot complete within the write timeout means the board is not draining
# its USB CDC buffer (wedged firmware or unplugged) — after the retries the
# proxy disconnects so the monitor can rediscover the board.
SERIAL_READ_TIMEOUT_S = 1.0
SERIAL_WRITE_TIMEOUT_S = 2.0
MAX_COMMAND_RETRIES = 2
COMMAND_RETRY_DELAY_S = 0.1

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
LED_FREQUENCY_MIN, LED_FREQUENCY_MAX = 20, 100000

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
# Protocol-driven atomic apply: one step's LED state (frequency + exclusive
# off->on set, or all off) + settle in ONE handler call. The backend acks
# with FLUORESCENCE_APPLIED only after the settle, so a protocol step can
# block until the light is truly capture-ready (magnet backend pattern).
PROTOCOL_SET_FLUORESCENCE = f"{DEVICE_NAME}/requests/protocol_set_fluorescence"
FLUORESCENCE_APPLIED = f"{DEVICE_NAME}/signals/fluorescence_applied"

# Firmware upload: the shared PeripheralFirmwareUploadService owns the run and
# the shared dialog renders the signals below. Topic strings come from the
# peripheral base factories (identical wire names, one definition). Upload /
# cancel are always-allowed subtopics (FluorescenceControllerBase): flashing
# IS the recovery path for a board whose firmware can't connect, and the
# service disconnects the proxy before flashing.
UPLOAD_FIRMWARE = upload_firmware_topic(DEVICE_NAME)
CANCEL_FIRMWARE_UPLOAD = cancel_firmware_upload_topic(DEVICE_NAME)
FIRMWARE_UPLOAD_STARTED = firmware_upload_started_topic(DEVICE_NAME)
FIRMWARE_UPLOAD_LOG = firmware_upload_log_topic(DEVICE_NAME)
FIRMWARE_UPLOAD_FINISHED = firmware_upload_finished_topic(DEVICE_NAME)

# Topics actor declared by plugin subscribes to. The listener-name key MUST
# match FluorescenceControllerBase.listener_name.
ACTOR_TOPIC_DICT = {
    "fluorescence_controller_listener": [
        f"{DEVICE_NAME}/requests/#",
        CONNECTED,
        DISCONNECTED,
    ]}
