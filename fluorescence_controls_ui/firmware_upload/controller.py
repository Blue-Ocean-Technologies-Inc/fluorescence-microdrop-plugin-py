"""Fluorescence wiring for the shared firmware-upload dialog.

The dialog itself (model / view / controller) is device-agnostic and lives in
``microdrop_utils.firmware_upload_dialog``; here we just build one wired to
the fluorescence live_state, publisher, topics, and defaults.
"""

from microdrop_utils.firmware_upload_dialog.controller import (
    FirmwareUploadDialogController,
)

from fluorescence_controller.consts import (
    CANCEL_FIRMWARE_UPLOAD, FIRMWARE_UPLOAD_FINISHED, FIRMWARE_UPLOAD_LOG,
    FIRMWARE_UPLOAD_STARTED, FLUORESCENCE_BOARD_DEVICE_ID,
)
from fluorescence_controller.datamodels import upload_firmware_publisher

from ..live_state import fluorescence_live_state
from .consts import DEFAULT_FIRMWARE_DIR


def make_firmware_upload_controller():
    """A firmware-upload dialog controller wired for the fluorescence board."""
    return FirmwareUploadDialogController(
        live_state=fluorescence_live_state,
        upload_publisher=upload_firmware_publisher,
        cancel_topic=CANCEL_FIRMWARE_UPLOAD,
        started_topic=FIRMWARE_UPLOAD_STARTED,
        log_topic=FIRMWARE_UPLOAD_LOG,
        finished_topic=FIRMWARE_UPLOAD_FINISHED,
        default_firmware_dir=str(DEFAULT_FIRMWARE_DIR),
        default_device_id=FLUORESCENCE_BOARD_DEVICE_ID,
        dialog_title="Upload Fluorescence Firmware",
    )
