# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for the Multi-Channel mix presets: saving the
panel's shares under a name (overwriting a same-named preset), picking a
preset onto the sliders through the slider path, deleting the picked
preset, and the whole map persisting across sessions."""

# Standard library imports.
import json

# Third-party imports.
import pytest

# Enthought library imports.
from apptools.preferences.api import Preferences

# Microdrop package imports.
import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controller.consts import LED_WAVELENGTHS, SET_LED_INTENSITIES
from fluorescence_controls_ui.chain_model import FluorescenceChainRow
from fluorescence_controls_ui.consts import MULTI_CHANNEL
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences

# Microdrop utils imports.
import microdrop_utils.dramatiq_pub_sub_helpers as pub_sub_helpers


@pytest.fixture
def node():
    return Preferences()  # in-memory


@pytest.fixture
def helper(node):
    return FluorescencePreferences(preferences=node)


@pytest.fixture
def model(helper):
    return FluorescenceStatusModel(preferences=helper)


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


@pytest.fixture
def controller(model, published):
    """The pane controller over ``model`` (held by the test, which keeps
    its observers alive)."""
    return FluorescenceControlsController(model=model)


def _save(controller, model, name, **shares):
    model.trait_set(**shares)
    model.led_mix_preset_name = name
    controller.save_led_mix_preset()


# --- save -------------------------------------------------------------------------


def test_save_files_the_shares_under_the_trimmed_name(controller, model):
    _save(controller, model, "  Warm ", led_proportion_0=100, led_proportion_2=50)

    assert model.led_mix_presets == {"Warm": {0: 100, 1: 0, 2: 50, 3: 0, 4: 0, 5: 0}}
    assert model.led_mix_preset == "Warm"


def test_save_under_an_existing_name_overwrites_it(controller, model):
    _save(controller, model, "Warm", led_proportion_0=100)
    _save(controller, model, "Warm", led_proportion_0=10)

    assert list(model.led_mix_presets) == ["Warm"]
    assert model.led_mix_presets["Warm"][0] == 10


@pytest.mark.parametrize("name", ["", "   "])
def test_save_with_a_blank_name_does_nothing(controller, model, name):
    _save(controller, model, name, led_proportion_0=100)

    assert model.led_mix_presets == {}
    assert model.led_mix_preset == ""


def test_save_button_saves(controller, model):
    model.led_mix_preset_name = "Warm"

    model.save_led_mix_preset_button = True

    assert "Warm" in model.led_mix_presets


def test_choices_list_no_preset_then_the_saved_names(controller, model):
    assert model.led_mix_preset_choices == [""]

    _save(controller, model, "Warm")
    _save(controller, model, "Cool")

    assert model.led_mix_preset_choices == ["", "Cool", "Warm"]


# --- apply ------------------------------------------------------------------------


def test_picking_a_preset_loads_its_shares(controller, model):
    _save(controller, model, "Warm", led_proportion_0=100, led_proportion_2=50)
    model.led_mix_preset = ""
    model.trait_set(led_proportion_0=0, led_proportion_2=0, led_proportion_5=30)

    model.led_mix_preset = "Warm"

    assert model.led_proportions() == {0: 100, 1: 0, 2: 50, 3: 0, 4: 0, 5: 0}


def test_picking_no_preset_leaves_the_sliders(controller, model):
    _save(controller, model, "Warm", led_proportion_0=100)
    model.led_proportion_0 = 40

    model.led_mix_preset = ""

    assert model.led_proportion_0 == 40


def test_slider_edit_after_a_pick_keeps_the_pick(controller, model):
    _save(controller, model, "Warm", led_proportion_0=100)

    model.led_proportion_0 = 40

    assert model.led_mix_preset == "Warm"
    assert model.led_mix_presets["Warm"][0] == 100


def test_picking_while_lit_relights_the_mix(controller, model, published):
    model.trait_set(wavelength=MULTI_CHANNEL, intensity=80)
    _save(controller, model, "Warm", led_proportion_1=50)
    model.led_mix_preset = ""
    model.led_proportion_1 = 0
    model.stream_active = True
    model.light_on = True
    published.clear()

    model.led_mix_preset = "Warm"

    intensities = {str(index): 0 for index in range(len(LED_WAVELENGTHS))}
    intensities["1"] = 40
    assert published[-1] == (SET_LED_INTENSITIES, {"intensities": intensities})


def test_picking_re_saves_into_the_selected_mix_row(controller, model):
    _save(controller, model, "Warm", led_proportion_3=60)
    model.led_mix_preset = ""
    row = FluorescenceChainRow(wavelength=MULTI_CHANNEL, proportions={1: 20})
    model.chain_rows = [row]
    model.chain_selection = row

    model.led_mix_preset = "Warm"

    assert row.proportions == {0: 0, 1: 0, 2: 0, 3: 60, 4: 0, 5: 0}


# --- delete -----------------------------------------------------------------------


def test_delete_forgets_the_picked_preset_and_clears_the_pick(controller, model):
    _save(controller, model, "Warm", led_proportion_0=100)
    _save(controller, model, "Cool", led_proportion_5=100)

    model.delete_led_mix_preset_button = True

    assert list(model.led_mix_presets) == ["Warm"]
    assert model.led_mix_preset == ""
    assert model.led_mix_preset_choices == ["", "Warm"]
    assert model.led_proportion_5 == 100  # the sliders keep their shares


def test_delete_with_no_pick_does_nothing(controller, model):
    _save(controller, model, "Warm")
    model.led_mix_preset = ""

    controller.delete_led_mix_preset()

    assert list(model.led_mix_presets) == ["Warm"]


# --- persistence ------------------------------------------------------------------


def test_presets_persist_through_the_preferences_node(node, controller, model):
    """A fresh helper over the same node reads the stored string back
    (literal_eval) — the next session's path."""
    _save(controller, model, "Warm", led_proportion_0=100, led_proportion_2=50)

    restored = FluorescenceStatusModel(
        preferences=FluorescencePreferences(preferences=node)
    )

    assert restored.led_mix_presets == model.led_mix_presets
    assert restored.led_mix_preset_choices == ["", "Warm"]
    assert restored.led_mix_preset == ""  # the pick is session-only


def test_deleting_persists_too(node, controller, model):
    _save(controller, model, "Warm")

    controller.delete_led_mix_preset()

    restored = FluorescencePreferences(preferences=node)
    assert restored.led_mix_presets == {}
