from pydantic import BaseModel, ConfigDict, Field

from .consts import LED_WAVELENGTHS, LED_DUTY_MAX, LED_FREQUENCY_MIN, LED_FREQUENCY_MAX


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
