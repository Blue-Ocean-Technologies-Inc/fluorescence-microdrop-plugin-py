from pydantic import BaseModel, ConfigDict, Field

from microdrop_utils.dramatiq_pub_sub_helpers import ValidatedTopicPublisher
from peripheral_device_controller_base.firmware_upload_datamodels import (
    UploadFirmwarePublisher,
)

from .consts import (
    LED_WAVELENGTHS, LED_DUTY_MAX,
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


# Firmware-upload payload + publisher are shared (peripheral base); this
# plugin only binds a publisher to its own upload topic. The dialog fills the
# board-specific default device id (FLUORESCENCE_BOARD_DEVICE_ID) before it
# reaches the wire, so the payload itself carries no fluorescence default.
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
