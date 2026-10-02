# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

# Standard library imports.
from typing import Annotated

# Third-party imports.
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Microdrop package imports.
from peripheral_device_controller_base.firmware_upload_datamodels import (
    UploadFirmwarePublisher,
)

# Microdrop utils imports.
from microdrop_utils.dramatiq_pub_sub_helpers import ValidatedTopicPublisher

# Local imports.
from .consts import (
    LED_DUTY_MAX,
    LED_DUTY_MIN,
    LED_FREQUENCY_MAX,
    LED_FREQUENCY_MIN,
    LED_WAVELENGTHS,
    PROTOCOL_SET_FLUORESCENCE,
    SET_LED_INTENSITIES,
    UPLOAD_FIRMWARE,
)

#: A firmware LED channel index (the position in LED_WAVELENGTHS).
LedIndex = Annotated[int, Field(ge=0, le=len(LED_WAVELENGTHS) - 1)]
#: An LED duty percentage.
LedDuty = Annotated[int, Field(ge=LED_DUTY_MIN, le=LED_DUTY_MAX)]
#: A channel's share of the intensity in a Multi-Channel mix (%).
LedProportion = Annotated[int, Field(ge=0, le=100)]


def scaled_duty(intensity, proportion):
    """Return the duty of a channel at ``proportion`` % of ``intensity`` %.

    Rounds half up in integer arithmetic, so 0 in either argument is exactly
    0 (the channel stays off) and no float error creeps into the duty.
    """
    return (intensity * proportion + 50) // 100


class _LedCommand(BaseModel):
    """Base for per-LED commands: ``led`` is the firmware channel index."""

    model_config = ConfigDict(extra="forbid")
    led: LedIndex


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


class SetLedIntensitiesData(BaseModel):
    """Several LED duties at once (Multi-Channel mode): led index -> duty.

    Channels missing from the mapping are left as they are, so a sender that
    wants a clean mix lists every channel (zero for the ones to keep off).
    """

    model_config = ConfigDict(extra="forbid")
    intensities: dict[LedIndex, LedDuty] = Field(min_length=1)


class ProtocolSetFluorescenceData(_LedCommand):
    """One protocol step's LED state, applied atomically then settled then
    acked. The light is one LED (``led`` at ``duty``) or a Multi-Channel
    mix (``intensities``: led index -> duty, every channel listed);
    ``frequency`` applies to whichever LEDs are lit. All of it is ignored
    when ``light_on`` is False (the step turns the light off)."""

    light_on: bool
    led: LedIndex | None = None
    duty: LedDuty | None = None
    intensities: dict[LedIndex, LedDuty] | None = None
    frequency: int = Field(ge=LED_FREQUENCY_MIN, le=LED_FREQUENCY_MAX)
    settle_s: float = Field(ge=0.0, le=60.0)

    @model_validator(mode="after")
    def _one_light_source(self):
        single = self.led is not None and self.duty is not None
        if self.light_on and not (single or self.intensities):
            raise ValueError("light_on needs led + duty, or intensities")

        return self


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

    def publish(
        self,
        *,
        light_on,
        frequency,
        settle_s,
        led=None,
        duty=None,
        intensities=None,
        **kw,
    ):
        super().publish(
            {
                "light_on": light_on,
                "led": led,
                "duty": duty,
                "intensities": intensities,
                "frequency": frequency,
                "settle_s": settle_s,
            },
            **kw,
        )


protocol_set_fluorescence_publisher = ProtocolSetFluorescencePublisher(
    topic=PROTOCOL_SET_FLUORESCENCE
)


class SetLedIntensitiesPublisher(ValidatedTopicPublisher):
    """Validated publisher for the ``SET_LED_INTENSITIES`` topic."""

    validator_class = SetLedIntensitiesData

    def publish(self, *, intensities, **kw):
        super().publish({"intensities": intensities}, **kw)


set_led_intensities_publisher = SetLedIntensitiesPublisher(topic=SET_LED_INTENSITIES)
