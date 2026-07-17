"""The capture-chain value contract: a step's (or the free-mode pane's)
list of named LED/camera captures, stored on the row as a plain list of
dicts and parsed back into typed `ChainEntry` objects.

Parsing is deliberately tolerant: a stale protocol file authored against
an older chain shape (or hand-edited) must never crash a load. Entries
that fail validation are skipped and logged; their valid siblings still
load.
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from logger.logger_service import get_logger

from fluorescence_controller.consts import (
    LED_DUTY_MAX, LED_DUTY_MIN, LED_FREQUENCY_MAX, LED_FREQUENCY_MIN,
    LED_WAVELENGTHS,
)
from fluorescence_controls_ui.cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from fluorescence_controls_ui.consts import EXPOSURE_MS_MAX, EXPOSURE_MS_MIN

logger = get_logger(__name__)


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
    run: bool = True

    @field_validator("wavelength")
    @classmethod
    def _wavelength_is_known(cls, value):
        if value not in LED_WAVELENGTHS:
            raise ValueError(f"Unknown LED wavelength: {value!r}")
        return value

    @property
    def led_index(self) -> int:
        return LED_WAVELENGTHS.index(self.wavelength)


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
    clean = "".join(
        c for c in label if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    clean = clean.replace(" ", "_")
    return clean or "capture"


def unique_label(label: str, existing: set[str]) -> str:
    """`label`, or `label_2`, `label_3`, ... — the first suffix not
    already in `existing`."""
    if label not in existing:
        return label
    suffix = 2
    while f"{label}_{suffix}" in existing:
        suffix += 1
    return f"{label}_{suffix}"
