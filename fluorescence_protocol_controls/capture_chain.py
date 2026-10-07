# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""The capture-chain value contract: a step's (or the free-mode pane's)
list of named LED/camera captures, stored on the row as a plain list of
dicts and parsed back into typed `ChainEntry` objects.

Parsing is deliberately tolerant: a stale protocol file authored against
an older chain shape (or hand-edited) must never crash a load. Entries
that fail validation are skipped and logged; their valid siblings still
load.
"""

# Third-party imports.
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# Microdrop package imports.
from fluorescence_controller.consts import (
    LED_DUTY_MAX,
    LED_DUTY_MIN,
    LED_FREQUENCY_MAX,
    LED_FREQUENCY_MIN,
    LED_WAVELENGTHS,
    MULTI_CHANNEL,
)
from fluorescence_controller.datamodels import LedIndex, LedProportion, scaled_duty
from fluorescence_controls_ui.cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from fluorescence_controls_ui.consts import (
    CAMERA_LEAD_TIME_MS_DEFAULT,
    CAMERA_LEAD_TIME_MS_MAX,
    CAMERA_LEAD_TIME_MS_MIN,
    EXPOSURE_MS_MAX,
    EXPOSURE_MS_MIN,
)

# Logger import.
from logger.logger_service import get_logger

logger = get_logger(__name__)

#: Short channel names for mix labels, from the wavelength names' initials
#: ("Deep Red (660 nm)" -> "DR"), in LED_WAVELENGTHS order.
LED_SHORT_NAMES = tuple(
    "".join(word[0] for word in name.split(" (")[0].split()) for name in LED_WAVELENGTHS
)
#: The label token that marks a Multi-Channel capture.
MULTI_CHANNEL_TOKEN = "Multi"


class ChainEntry(BaseModel):
    """One named capture in a chain: the LED/camera params to apply plus
    whether it actually runs (`run=False` parks it without deleting it)."""

    model_config = ConfigDict(extra="ignore")

    label: str
    wavelength: str
    intensity: int = Field(ge=LED_DUTY_MIN, le=LED_DUTY_MAX)
    frequency: int = Field(ge=LED_FREQUENCY_MIN, le=LED_FREQUENCY_MAX)
    exposure_ms: float = Field(ge=EXPOSURE_MS_MIN, le=EXPOSURE_MS_MAX)
    gain: int = Field(ge=ASI_GAIN_MIN, le=ASI_GAIN_MAX)
    # Milliseconds between the LED applied-and-settled ack and the frame
    # grab, for exposure/gain to settle. Defaulted so chains saved before
    # it existed still load (and capture exactly as they did).
    camera_lead_time_ms: int = Field(
        default=CAMERA_LEAD_TIME_MS_DEFAULT,
        ge=CAMERA_LEAD_TIME_MS_MIN,
        le=CAMERA_LEAD_TIME_MS_MAX,
    )
    run: bool = True
    # Per-row auto camera modes: when on, the capture thread's brightness
    # loop owns exposure/gain and the stored values are only the starting
    # point (a deliberate trade of replay determinism for convenience).
    auto_exposure: bool = False
    auto_gain: bool = False
    # Optional user tag; `label` is DERIVED from it via chain_label()
    # (image_tag_wavelength_index) and is read-only in the UI.
    image_tag: str = ""

    # Protocol phase(s) this entry fires in (the executor's on_pre_step /
    # on_post_step — the same hooks the regular capture column picks
    # between; this entry may fire in both). At least one is always on:
    # both-False input is coerced to the step-start default rather than
    # rejected, so a hand-edited protocol file still loads. The pane holds
    # the same invariant live (fluorescence_controls_ui CapturePhases).
    capture_start: bool = True
    capture_end: bool = False

    # Multi-Channel mix (wavelength == MULTI_CHANNEL only): led index ->
    # share of `intensity` (%). Absent on single-wavelength entries, which
    # is also how every entry saved before mixes existed loads.
    proportions: dict[LedIndex, LedProportion] | None = None

    @field_validator("wavelength")
    @classmethod
    def _wavelength_is_known(cls, value):
        if value not in (*LED_WAVELENGTHS, MULTI_CHANNEL):
            raise ValueError(f"Unknown LED wavelength: {value!r}")
        return value

    @model_validator(mode="after")
    def _at_least_one_phase(self):
        if not (self.capture_start or self.capture_end):
            self.capture_start = True
        return self

    @model_validator(mode="after")
    def _proportions_match_wavelength(self):
        """A mix needs its shares; a single wavelength carries none (stray
        shares are dropped rather than rejected, like the phase coercion)."""
        if self.multi_channel and not self.proportions:
            raise ValueError(f"{MULTI_CHANNEL} entry without proportions")

        if not self.multi_channel:
            self.proportions = None

        return self

    @property
    def multi_channel(self) -> bool:
        return self.wavelength == MULTI_CHANNEL

    @property
    def led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.wavelength)

    def led_intensities(self) -> dict[int, int]:
        """The mix at this entry's intensity: every channel's duty (0 for a
        channel without a share, so nothing else stays lit)."""
        return {
            index: scaled_duty(self.intensity, self.proportions.get(index, 0))
            for index in range(len(LED_WAVELENGTHS))
        }

    def led_request(self) -> dict:
        """The LED part of this entry's protocol_set_fluorescence request:
        the per-channel mix, or the one LED at the intensity."""
        if self.multi_channel:
            return {"intensities": self.led_intensities()}

        return {"led": self.led_index, "duty": self.intensity}


def parse_chain(value) -> list[ChainEntry]:
    """A stored column value (list of dicts, or None) parsed into
    `ChainEntry` objects. Entries that fail validation are skipped with a
    warning so a stale protocol file never crashes a load."""
    if not value:
        return []
    entries = []
    for raw in value:
        try:
            entries.append(ChainEntry(**raw))
        except Exception as e:
            logger.warning(f"Skipping invalid capture-chain entry {raw!r}: {e}")
    return entries


def dump_chain(entries: list[ChainEntry]) -> list[dict]:
    """The column value to store: a plain list of dicts."""
    return [e.model_dump() for e in entries]


def ticked(entries) -> list[ChainEntry]:
    """The entries that actually run (`run=True`), in chain order."""
    return [e for e in entries if e.run]


def sanitize_label(label: str) -> str:
    """A label reduced to a filename-safe form: alnum plus space/dash/
    underscore are kept, then spaces become underscores (the existing
    device_viewer scheme). An empty result falls back to `"capture"`."""
    clean = "".join(c for c in label if c.isalnum() or c in (" ", "-", "_")).strip()
    clean = clean.replace(" ", "_")
    return clean or "capture"


def mix_label(proportions) -> str:
    """A mix's label token: ``Multi`` plus each lit channel's short name and
    share, e.g. ``Multi B100 G60 R25`` (channels at 0 % are left out)."""
    shares = [
        f"{LED_SHORT_NAMES[index]}{share}"
        for index, share in sorted((proportions or {}).items())
        if share
    ]

    return " ".join([MULTI_CHANNEL_TOKEN, *shares])


def chain_label(image_tag: str, wavelength: str, index: int, proportions=None) -> str:
    """The DERIVED label of chain position ``index`` (1-based):
    ``image_tag_wavelength_index``, with the optional tag omitted when
    empty and a Multi-Channel wavelength spelled as its ``mix_label``. The
    index makes labels unique within a chain by construction, which is why
    there is no suffix-on-collision machinery."""
    if wavelength == MULTI_CHANNEL:
        wavelength = mix_label(proportions)

    parts = (
        [image_tag, wavelength, str(index)] if image_tag else [wavelength, str(index)]
    )

    return sanitize_label("_".join(parts))
