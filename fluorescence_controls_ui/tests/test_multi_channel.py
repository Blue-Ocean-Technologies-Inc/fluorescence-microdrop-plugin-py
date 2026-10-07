# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for the Multi-Channel mix: per-channel proportions
scale the single intensity knob into per-LED duties, and the proportions
persist like the other control values. Also the controller's mode
switches: entering Multi-Channel lights the mix, leaving it is one
exclusive set_led, and the mix never reaches a capture-chain row."""

# Standard library imports.
import json

# Third-party imports.
import pytest

# Enthought library imports.
from apptools.preferences.api import Preferences
from traits.api import TraitError

# Microdrop package imports.
import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controller.consts import (
    LED_WAVELENGTHS,
    SET_LED,
    SET_LED_FREQUENCY,
    SET_LED_INTENSITIES,
)
from fluorescence_controller.datamodels import SetLedIntensitiesData
from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.consts import LED_PROPORTION_TRAITS, MULTI_CHANNEL
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.model import FluorescenceStatusModel, scaled_duty
from fluorescence_controls_ui.preferences import FluorescencePreferences

# Microdrop utils imports.
import microdrop_utils.dramatiq_pub_sub_helpers as pub_sub_helpers


@pytest.fixture
def helper():
    return FluorescencePreferences(preferences=Preferences())  # in-memory


@pytest.fixture
def model(helper):
    return FluorescenceStatusModel(preferences=helper)


@pytest.mark.parametrize(
    "intensity, proportion, duty",
    [
        (100, 100, 100),
        (100, 0, 0),
        (0, 100, 0),
        (50, 50, 25),
        (80, 25, 20),
        (33, 50, 17),  # 16.5 rounds half up
        (1, 49, 0),  # 0.49 rounds down: a faint share stays off
        (1, 50, 1),
    ],
)
def test_scaled_duty(intensity, proportion, duty):
    assert scaled_duty(intensity, proportion) == duty


def test_one_proportion_trait_per_channel(model):
    assert len(LED_PROPORTION_TRAITS) == len(LED_WAVELENGTHS)
    for name in LED_PROPORTION_TRAITS:
        assert getattr(model, name) == 0


def test_led_intensities_lists_every_channel(model):
    model.intensity = 80
    model.trait_set(led_proportion_0=100, led_proportion_2=50)

    assert model.led_intensities() == {0: 80, 1: 0, 2: 40, 3: 0, 4: 0, 5: 0}


def test_led_intensities_all_off_at_zero_intensity(model):
    model.trait_set(**{name: 100 for name in LED_PROPORTION_TRAITS})
    model.intensity = 0

    assert set(model.led_intensities().values()) == {0}


def test_led_intensities_follow_the_intensity_knob(model):
    model.led_proportion_1 = 50

    model.intensity = 100
    assert model.led_intensities()[1] == 50

    model.intensity = 40
    assert model.led_intensities()[1] == 20


def test_led_intensities_validate_as_a_request_payload(model):
    model.intensity = 100
    model.trait_set(**{name: 100 for name in LED_PROPORTION_TRAITS})

    data = SetLedIntensitiesData(intensities=model.led_intensities())
    assert data.intensities == {index: 100 for index in range(len(LED_WAVELENGTHS))}


def test_proportions_are_bounded(model):
    with pytest.raises(TraitError):
        model.led_proportion_0 = 101


def test_proportions_restore_into_a_fresh_model(helper, model):
    model.led_proportion_3 = 70  # pushed to preferences live

    restored = FluorescenceStatusModel(preferences=helper)  # "next session"
    assert restored.led_proportion_3 == 70
    assert helper.led_proportion_3 == 70


# --- controller mode switches -----------------------------------------------------


@pytest.fixture
def published(monkeypatch):
    """Every publish, raw (controller) or validated (publisher), as
    (topic, payload) in order."""
    sink = []

    def record(message, topic=None, **kwargs):
        sink.append((topic, json.loads(message) if message else {}))

    monkeypatch.setattr(controller_mod, "publish_message", record)
    monkeypatch.setattr(pub_sub_helpers, "publish_message", record)
    return sink


def _mix(**duties):
    """The expected set_led_intensities payload: listed duties, others 0."""
    intensities = {str(index): 0 for index in range(len(LED_WAVELENGTHS))}
    intensities.update(
        {key.removeprefix("led_"): value for key, value in duties.items()}
    )
    return (SET_LED_INTENSITIES, {"intensities": intensities})


@pytest.fixture
def controller(model, published):
    """The pane controller over ``model`` (held by the test, which keeps
    its observers alive)."""
    return FluorescenceControlsController(model=model)


@pytest.fixture
def lit(controller, model, published):
    """``controller`` with the stream on and the light on."""
    model.trait_set(led_proportion_0=100, led_proportion_2=50, intensity=80)
    model.stream_active = True
    model.light_on = True
    published.clear()
    return controller


def test_single_to_multi_lights_the_mix(lit, model, published):
    model.wavelength = MULTI_CHANNEL

    assert published == [_mix(led_0=80, led_2=40)]


def test_multi_to_single_is_one_exclusive_set_led(lit, model, published):
    model.wavelength = MULTI_CHANNEL
    published.clear()

    model.wavelength = LED_WAVELENGTHS[3]

    assert published == [(SET_LED, {"led": 3, "duty": 80, "exclusive": True})]


def test_intensity_zero_turns_the_whole_mix_off(lit, model, published):
    model.wavelength = MULTI_CHANNEL
    published.clear()

    model.intensity = 0

    assert published == [_mix()]


def test_proportion_edit_republishes_the_mix(lit, model, published):
    model.wavelength = MULTI_CHANNEL
    published.clear()

    model.led_proportion_5 = 25

    assert published == [_mix(led_0=80, led_2=40, led_5=20)]


def test_proportion_edit_is_silent_in_single_channel_mode(lit, model, published):
    model.led_proportion_5 = 25

    assert published == []


def test_stream_start_sets_every_frequency_then_the_mix(controller, model, published):
    model.trait_set(wavelength=MULTI_CHANNEL, led_proportion_1=100, light_on=True)
    published.clear()

    model.stream_active = True

    frequencies = [
        (SET_LED_FREQUENCY, {"led": led, "frequency": model.frequency})
        for led in range(len(LED_WAVELENGTHS))
    ]
    assert published == [*frequencies, _mix(led_1=model.intensity)]


def test_multi_channel_releases_and_never_writes_the_chain_row(controller, model):
    row = FluorescenceChainRow(wavelength=LED_WAVELENGTHS[1])
    model.chain_rows = [row]
    model.chain_selection = row

    model.wavelength = MULTI_CHANNEL
    model.intensity = 10

    assert model.chain_selection is None
    assert row.wavelength == LED_WAVELENGTHS[1]
    assert row.intensity != 10


def test_row_click_leaves_multi_channel(controller, model):
    row = FluorescenceChainRow(wavelength=LED_WAVELENGTHS[4])
    model.chain_rows = [row]
    model.wavelength = MULTI_CHANNEL

    model.chain_selection = row

    assert model.wavelength == LED_WAVELENGTHS[4]
    assert not model.multi_channel


def test_add_capture_is_refused_in_multi_channel(controller, model):
    model.wavelength = MULTI_CHANNEL

    controller.add_capture()

    assert model.chain_rows == []
