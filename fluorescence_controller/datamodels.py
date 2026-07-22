from pydantic import BaseModel, ConfigDict, Field

from microdrop_utils.dramatiq_pub_sub_helpers import ValidatedTopicPublisher

from .consts import (
    FLUORESCENCE_BOARD_DEVICE_ID, LED_WAVELENGTHS, LED_DUTY_MAX,
    LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, PROTOCOL_SET_FLUORESCENCE,
    UPLOAD_FIRMWARE,
)


class _LedCommand(BaseModel):
    """Base for per-LED commands: ``led`` is the firmware channel index."""
    model_config = ConfigDict(extra='forbid')
    led: int = Field(ge=0, le=len(LED_WAVELENGTHS) - 1)


class SetLedData(_LedCommand):
    """LED duty -> ``led_<index>_<duty>``. Duty is a percentage 0-100.

    ``exclusive`` turns every other LED off first (``led_off`` then the LED
    command) INSIDE one backend handler — the standalone UI's wavelength
    switch sent the two commands separately, but separate pub/sub messages
    have no ordering guarantee across the worker pool.
    """
    duty: int = Field(ge=0, le=LED_DUTY_MAX)
    exclusive: bool = False


class SetLedFrequencyData(_LedCommand):
    """LED PWM frequency -> ``ledf_<index>_<frequency>`` (Hz)."""
    frequency: int = Field(ge=LED_FREQUENCY_MIN, le=LED_FREQUENCY_MAX)


class ProtocolSetFluorescenceData(_LedCommand):
    """One protocol step's LED state, applied atomically then settled then
    acked. ``led``/``duty``/``frequency`` are ignored when ``light_on`` is
    False (the step turns the light off)."""
    light_on: bool
    duty: int = Field(ge=0, le=LED_DUTY_MAX)
    frequency: int = Field(ge=LED_FREQUENCY_MIN, le=LED_FREQUENCY_MAX)
    settle_s: float = Field(ge=0.0, le=60.0)


class UploadFirmwareData(BaseModel):
    """One firmware-upload run: mirrors firmware_uploader.upload_firmware.

    ``firmware_source`` is a folder tree OR a .zip bundle (the backend unzips
    a zip to a temp dir, uploads it, then deletes it). ``port`` empty means
    auto: the backend reuses a connected proxy's stored port, else probes for
    the board (whoami / Pico VID). ``device_id`` empty matches the first
    board that identifies at all. ``upload_timeout_s`` 0 means never kill the
    upload.
    """
    model_config = ConfigDict(extra='forbid')

    firmware_source: str
    single_file: str = ""  # upload only this file (absolute or dir-relative)
    port: str = ""
    device_id: str = FLUORESCENCE_BOARD_DEVICE_ID
    update_config: bool = False
    skip_filesystem_format: bool = False
    reset_after_upload: bool = True
    dry_run: bool = False
    upload_timeout_s: int = Field(default=0, ge=0)


class UploadFirmwarePublisher(ValidatedTopicPublisher):
    """Validated publisher for the ``UPLOAD_FIRMWARE`` topic.

    Exposes a keyword-only .publish(...) method that mirrors the
    UploadFirmwareData fields for call-site readability.
    """
    validator_class = UploadFirmwareData

    def publish(self, *, firmware_source, single_file, port, device_id,
                update_config, skip_filesystem_format, reset_after_upload,
                dry_run, upload_timeout_s, **kw):
        super().publish({
            "firmware_source": firmware_source,
            "single_file": single_file,
            "port": port,
            "device_id": device_id,
            "update_config": update_config,
            "skip_filesystem_format": skip_filesystem_format,
            "reset_after_upload": reset_after_upload,
            "dry_run": dry_run,
            "upload_timeout_s": upload_timeout_s,
        }, **kw)


upload_firmware_publisher = UploadFirmwarePublisher(topic=UPLOAD_FIRMWARE)


class ProtocolSetFluorescencePublisher(ValidatedTopicPublisher):
    """Validated publisher for the ``PROTOCOL_SET_FLUORESCENCE`` topic.

    Exposes a keyword-only .publish(...) method that mirrors the
    ProtocolSetFluorescenceData fields for call-site readability.
    """
    validator_class = ProtocolSetFluorescenceData

    def publish(self, *, light_on, led, duty, frequency, settle_s, **kw):
        super().publish({
            "light_on": light_on,
            "led": led,
            "duty": duty,
            "frequency": frequency,
            "settle_s": settle_s,
        }, **kw)


protocol_set_fluorescence_publisher = ProtocolSetFluorescencePublisher(
    topic=PROTOCOL_SET_FLUORESCENCE)
