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

# Service Request Topics
START_DEVICE_MONITORING = f"{DEVICE_NAME}/requests/start_device_monitoring"
RETRY_CONNECTION = f"{DEVICE_NAME}/requests/retry_connection"
SEND_COMMAND = f"{DEVICE_NAME}/requests/send_command"

# Topics actor declared by plugin subscribes to. The listener-name key MUST
# match FluorescenceControllerBase.listener_name.
ACTOR_TOPIC_DICT = {
    "fluorescence_controller_listener": [
        f"{DEVICE_NAME}/requests/#",
        CONNECTED,
        DISCONNECTED,
    ]}
