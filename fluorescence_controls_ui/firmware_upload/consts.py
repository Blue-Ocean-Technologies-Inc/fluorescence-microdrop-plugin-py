from pathlib import Path

# Dev-machine default for the firmware SOURCE tree (the standalone repo's
# firmware folder — deliberately not shipped with this plugin); the dialog's
# Firmware folder field is editable, so other machines just browse to theirs.
DEFAULT_FIRMWARE_DIR = Path(r"C:\Users\Info\PycharmProjects\fluorescence-camera-ui\firmware")

# Separates "COM7" from its human-readable description in the port dropdown.
PORT_ENTRY_SEPARATOR = " — "

LOG_CONSOLE_FONT_FAMILY = "Consolas"

#: Shown in the read-only Device ID field until the board's whoami arrives
#: (matches the status pane's board_id_text "-" placeholder). Treated as
#: "no id known" when building the upload payload.
DEVICE_ID_PLACEHOLDER = "-"
