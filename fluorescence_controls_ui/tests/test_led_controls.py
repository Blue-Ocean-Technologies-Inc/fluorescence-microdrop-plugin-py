"""Hardware-free tests for the LED controls (frontend side).

Mirrors the standalone app's slots: the light toggle drives the active
mode's LED set, live edits publish only while lit in the matching mode, and
wavelength switches are ONE exclusive set_led request (the backend runs the
legacy off->on sequence atomically). `publish_message` is monkeypatched at
the controller module.
"""
import json

import pytest

import fluorescence_controls_ui.controller as controller_mod
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controller.consts import (
    SET_LED, SET_LED_FREQUENCY, ALL_LEDS_OFF, LED_WAVELENGTHS,
)


@pytest.fixture
def published(monkeypatch):
    sink = []
    monkeypatch.setattr(
        controller_mod, "publish_message",
        lambda message, topic=None, **k: sink.append((topic, json.loads(message))),
    )
    return sink


def _controller():
    model = FluorescenceStatusModel()
    return FluorescenceControlsController(model=model), model


# --- defaults (the standalone config.yml values) --------------------------------

def test_defaults_match_standalone_config():
    model = FluorescenceStatusModel()
    assert model.mode == "br" and model.light_on is False
    assert (model.br_intensity, model.br_frequency) == (38, 315)
    assert (model.fl_intensity, model.fl_frequency) == (15, 40000)
    assert model.br_led_index == 0 and model.fl_led_index == 0


# --- master light toggle ---------------------------------------------------------

def test_light_on_drives_brightfield_in_br_mode(published):
    controller, model = _controller()
    model.light_on = True
    assert published == [(SET_LED, {"led": 0, "duty": 38})]


def test_light_on_drives_brightfield_in_dual_mode(published):
    # The original's abs/double branch: dual lights the brightfield set.
    controller, model = _controller()
    model.mode = "dual"
    model.light_on = True
    assert published == [(SET_LED, {"led": 0, "duty": 38})]


def test_light_on_drives_fluorescence_in_fl_mode(published):
    controller, model = _controller()
    model.mode = "fl"
    model.fl_wavelength = LED_WAVELENGTHS[2]
    model.light_on = True
    assert published == [(SET_LED, {"led": 2, "duty": 15})]


def test_light_off_is_all_leds_off(published):
    controller, model = _controller()
    model.light_on = True
    published.clear()
    model.light_on = False
    assert published == [(ALL_LEDS_OFF, {})]


# --- live edits gate on light + matching mode ------------------------------------

def test_intensity_edit_publishes_live_when_lit(published):
    controller, model = _controller()
    model.light_on = True
    published.clear()
    model.br_intensity = 55
    assert published == [(SET_LED, {"led": 0, "duty": 55})]


def test_intensity_edit_staged_while_light_off(published):
    controller, model = _controller()
    model.br_intensity = 55
    assert published == []


def test_br_edit_staged_in_fl_mode(published):
    # update_br_intensity requires mode == "br" in the original — even dual
    # stages brightfield edits.
    controller, model = _controller()
    model.mode = "fl"
    model.light_on = True
    published.clear()
    model.br_intensity = 55
    model.br_frequency = 400
    assert published == []


def test_frequency_edit_publishes_live(published):
    controller, model = _controller()
    model.light_on = True
    published.clear()
    model.br_frequency = 500
    assert published == [(SET_LED_FREQUENCY, {"led": 0, "frequency": 500})]


# --- wavelength switch = ONE exclusive request ------------------------------------

def test_wavelength_switch_is_single_exclusive_request(published):
    controller, model = _controller()
    model.light_on = True
    published.clear()
    model.br_wavelength = LED_WAVELENGTHS[4]      # Red (630 nm)
    assert published == [(SET_LED, {"led": 4, "duty": 38, "exclusive": True})]


def test_fl_wavelength_switch_in_fl_mode(published):
    controller, model = _controller()
    model.mode = "fl"
    model.light_on = True
    published.clear()
    model.fl_wavelength = LED_WAVELENGTHS[5]      # Deep Red (660 nm)
    assert published == [(SET_LED, {"led": 5, "duty": 15, "exclusive": True})]


def test_wavelength_switch_staged_while_off(published):
    controller, model = _controller()
    model.br_wavelength = LED_WAVELENGTHS[1]
    assert published == []
