"""The capture-chain table's row type: a Qt-free `HasTraits` the
`TableEditor` binds to directly, holding the same LED/camera params as the
panel model plus the `run` tick.

Converts to/from Task 1's `ChainEntry` (`fluorescence_protocol_controls
.capture_chain`), the value contract a chain is stored/loaded under —
`exposure` here maps to `exposure_ms` there (the row keeps the panel's
millisecond field name; the stored entry keeps its explicit unit)."""
from traits.api import Bool, Enum, HasTraits, Range, Str

from fluorescence_protocol_controls.capture_chain import ChainEntry

from .cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from .consts import (
    EXPOSURE_MS_MAX, EXPOSURE_MS_MIN,
    LED_DUTY_MAX, LED_DUTY_MIN,
    LED_FREQUENCY_MAX, LED_FREQUENCY_MIN,
    LED_WAVELENGTHS,
)


class FluorescenceChainRow(HasTraits):
    """One row of a capture chain (attached to a step/group, or in the
    free-mode stash): the LED/camera params to apply plus whether it runs."""

    label = Str()
    wavelength = Enum(*LED_WAVELENGTHS)
    intensity = Range(LED_DUTY_MIN, LED_DUTY_MAX, value=50)
    frequency = Range(LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=40000)
    exposure = Range(float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=10.0)
    gain = Range(ASI_GAIN_MIN, ASI_GAIN_MAX, value=0)
    run = Bool(True)
    auto_exposure = Bool(False)
    auto_gain = Bool(False)
    # Optional user tag; `label` above is derived from it (see
    # capture_chain.chain_label) and never edited directly.
    image_tag = Str("")

    def to_entry_dict(self) -> dict:
        """This row's params as a `ChainEntry`-shaped dict (`exposure` ->
        `exposure_ms`)."""
        return {
            "label": self.label,
            "wavelength": self.wavelength,
            "intensity": self.intensity,
            "frequency": self.frequency,
            "exposure_ms": self.exposure,
            "gain": self.gain,
            "run": self.run,
            "auto_exposure": self.auto_exposure,
            "auto_gain": self.auto_gain,
            "image_tag": self.image_tag,
        }

    @classmethod
    def from_entry(cls, entry: ChainEntry) -> "FluorescenceChainRow":
        """A row populated from a `ChainEntry` (`exposure_ms` -> `exposure`)."""
        return cls(
            label=entry.label,
            wavelength=entry.wavelength,
            intensity=entry.intensity,
            frequency=entry.frequency,
            exposure=entry.exposure_ms,
            gain=entry.gain,
            run=entry.run,
            auto_exposure=entry.auto_exposure,
            auto_gain=entry.auto_gain,
            image_tag=entry.image_tag,
        )
