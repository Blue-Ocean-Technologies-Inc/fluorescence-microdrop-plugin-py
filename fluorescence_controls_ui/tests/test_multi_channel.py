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
persist like the other control values."""

# Third-party imports.
import pytest

# Enthought library imports.
from apptools.preferences.api import Preferences
from traits.api import TraitError

# Microdrop package imports.
from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_controller.datamodels import SetLedIntensitiesData
from fluorescence_controls_ui.consts import LED_PROPORTION_TRAITS
from fluorescence_controls_ui.model import FluorescenceStatusModel, scaled_duty
from fluorescence_controls_ui.preferences import FluorescencePreferences


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
