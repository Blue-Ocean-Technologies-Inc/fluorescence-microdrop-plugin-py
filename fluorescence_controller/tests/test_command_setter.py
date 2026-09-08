# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests: typed requests -> exact board command lines."""

# Standard library imports.
import json

# Third-party imports.
import pytest
from pydantic import ValidationError

# Microdrop package imports.
from fluorescence_controller.datamodels import SetLedData, SetLedFrequencyData
from fluorescence_controller.fluorescence_serial_proxy import FluorescenceSerialProxy
from fluorescence_controller.services.fluorescence_command_setter_service import (
    FluorescenceCommandSetterService,
)


class FakeProxy(FluorescenceSerialProxy):
    """Records command lines; skips the serial-port constructor (the
    service's proxy trait is typed to the real proxy class)."""

    def __init__(self):
        self.sent = []

    def send_command(self, command):
        self.sent.append(command)


@pytest.fixture
def service():
    service = FluorescenceCommandSetterService()
    service.proxy = FakeProxy()
    return service


def test_set_led_formats_the_led_command(service):
    service.on_set_led_request(json.dumps({"led": 0, "duty": 38}))
    assert service.proxy.sent == ["led_0_38"]


def test_set_led_exclusive_is_off_then_on_in_one_handler(service):
    # The standalone UI's wavelength switch: board.off() then led_<new>_<duty>.
    service.on_set_led_request(json.dumps({"led": 2, "duty": 15, "exclusive": True}))
    assert service.proxy.sent == ["led_off", "led_2_15"]


def test_set_led_frequency(service):
    service.on_set_led_frequency_request(json.dumps({"led": 1, "frequency": 40000}))
    assert service.proxy.sent == ["ledf_1_40000"]


def test_all_off_and_on(service):
    service.on_all_leds_off_request("")
    service.on_all_leds_on_request("")
    assert service.proxy.sent == ["led_off", "led_on"]


def test_payload_bounds_are_enforced():
    with pytest.raises(ValidationError):
        SetLedData(led=0, duty=101)
    with pytest.raises(ValidationError):
        SetLedData(led=6, duty=50)  # only 6 LEDs (0-5)
    with pytest.raises(ValidationError):
        SetLedFrequencyData(led=0, frequency=0)


def test_raw_passthrough(service):
    service.on_send_command_request("led_help")
    assert service.proxy.sent == ["led_help"]
