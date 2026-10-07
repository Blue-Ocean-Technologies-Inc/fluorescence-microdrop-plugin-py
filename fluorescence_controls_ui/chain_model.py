# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""The capture-chain table's row type: a Qt-free `HasTraits` the
`TableEditor` binds to directly, holding the same LED/camera params as the
panel model plus the `run` tick.

Converts to/from Task 1's `ChainEntry` (`fluorescence_protocol_controls
.capture_chain`), the value contract a chain is stored/loaded under —
`exposure` here maps to `exposure_ms` there (the row keeps the panel's
millisecond field name; the stored entry keeps its explicit unit)."""

# Enthought library imports.
from traits.api import Bool, Dict, Enum, HasTraits, Int, Range, Str, observe

# Microdrop package imports.
from fluorescence_protocol_controls.capture_chain import ChainEntry

# Local imports.
from .cameras.consts import ASI_GAIN_MAX, ASI_GAIN_MIN
from .consts import (
    CAMERA_LEAD_TIME_MS_DEFAULT,
    CAMERA_LEAD_TIME_MS_MAX,
    CAMERA_LEAD_TIME_MS_MIN,
    EXPOSURE_MS_MAX,
    EXPOSURE_MS_MIN,
    LED_DUTY_MAX,
    LED_DUTY_MIN,
    LED_FREQUENCY_MAX,
    LED_FREQUENCY_MIN,
    MULTI_CHANNEL,
    WAVELENGTH_CHOICES,
)


class CapturePhases(HasTraits):
    """The protocol phase(s) a capture fires in, shared by the chain row
    and the panel model that edits it. At least one phase is always on:
    switching off the sole phase hands it to the other, so clicking the
    only lit Start/End toggle swaps phases instead of being refused."""

    #: Fire at step start (the executor's on_pre_step).
    capture_start = Bool(True)

    #: Fire at step end (the executor's on_post_step).
    capture_end = Bool(False)

    @observe("[capture_start,capture_end]")
    def _keep_one_capture_phase(self, event):
        # Turn the OTHER phase on, never the one just switched off: a
        # TraitsUI editor skips repainting a trait it is itself writing,
        # so reverting the clicked toggle would leave its button stale.
        if self.capture_start or self.capture_end:
            return

        if event.name == "capture_start":
            self.capture_end = True
        else:
            self.capture_start = True


class FluorescenceChainRow(CapturePhases):
    """One row of a capture chain (attached to a step/group, or in the
    free-mode stash): the LED/camera params to apply plus whether it runs.
    The phase flags (`capture_start` / `capture_end`) mirror ChainEntry;
    the panel's Start/End toggles edit them via the live binding."""

    label = Str()
    #: One LED, or MULTI_CHANNEL to fire the `proportions` mix.
    wavelength = Enum(*WAVELENGTH_CHOICES)
    intensity = Range(LED_DUTY_MIN, LED_DUTY_MAX, value=50)
    frequency = Range(LED_FREQUENCY_MIN, LED_FREQUENCY_MAX, value=40000)
    exposure = Range(float(EXPOSURE_MS_MIN), float(EXPOSURE_MS_MAX), value=10.0)
    gain = Range(ASI_GAIN_MIN, ASI_GAIN_MAX, value=0)
    camera_lead_time_ms = Range(
        CAMERA_LEAD_TIME_MS_MIN,
        CAMERA_LEAD_TIME_MS_MAX,
        value=CAMERA_LEAD_TIME_MS_DEFAULT,
    )
    run = Bool(True)
    auto_exposure = Bool(False)
    auto_gain = Bool(False)
    # Optional user tag; `label` above is derived from it (see
    # capture_chain.chain_label) and never edited directly.
    image_tag = Str("")
    #: Multi-Channel shares (led index -> % of `intensity`); stored on the
    #: entry only while `wavelength` is MULTI_CHANNEL.
    proportions = Dict(Int, Int)

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
            "camera_lead_time_ms": self.camera_lead_time_ms,
            "run": self.run,
            "auto_exposure": self.auto_exposure,
            "auto_gain": self.auto_gain,
            "image_tag": self.image_tag,
            "capture_start": self.capture_start,
            "capture_end": self.capture_end,
            "proportions": (
                dict(self.proportions) if self.wavelength == MULTI_CHANNEL else None
            ),
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
            camera_lead_time_ms=entry.camera_lead_time_ms,
            run=entry.run,
            auto_exposure=entry.auto_exposure,
            auto_gain=entry.auto_gain,
            image_tag=entry.image_tag,
            capture_start=entry.capture_start,
            capture_end=entry.capture_end,
            proportions=entry.proportions or {},
        )
