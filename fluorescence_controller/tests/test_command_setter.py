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
import threading

# Third-party imports.
import pytest
from pydantic import ValidationError

# Microdrop package imports.
from fluorescence_controller.consts import FLUORESCENCE_APPLIED, SET_LED_INTENSITIES
from fluorescence_controller.datamodels import (
    ProtocolSetFluorescenceData,
    SetLedData,
    SetLedFrequencyData,
    SetLedIntensitiesData,
    set_led_intensities_publisher,
)
from fluorescence_controller.fluorescence_serial_proxy import FluorescenceSerialProxy
from fluorescence_controller.services import (
    fluorescence_command_setter_service as setter_module,
)
from fluorescence_controller.services.fluorescence_command_setter_service import (
    FluorescenceCommandSetterService,
)


class FakeProxy(FluorescenceSerialProxy):
    """Records command lines; skips the serial-port constructor (the
    service's proxy trait is typed to the real proxy class)."""

    def __init__(self):
        self.sent = []
        self.transaction_lock = threading.RLock()

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


def test_set_led_intensities_sets_every_listed_channel_in_order(service):
    # JSON object keys arrive as strings; the schema coerces them to indices.
    body = json.dumps({"intensities": {"3": 0, "0": 40, "5": 100}})
    service.on_set_led_intensities_request(body)
    assert service.proxy.sent == ["led_0_40", "led_3_0", "led_5_100"]


def test_set_led_intensities_holds_the_transaction_lock(service):
    held = []
    service.proxy.send_command = lambda command: held.append(
        service.proxy.transaction_lock._is_owned()
    )
    service.on_set_led_intensities_request(json.dumps({"intensities": {0: 10, 1: 20}}))
    assert held == [True, True]


@pytest.mark.parametrize(
    "intensities",
    [
        {0: 101},  # duty above 100 %
        {0: -1},  # duty below 0 %
        {6: 50},  # only 6 LEDs (0-5)
        {-1: 50},
        {},  # nothing to apply
    ],
)
def test_set_led_intensities_bounds_are_enforced(intensities):
    with pytest.raises(ValidationError):
        SetLedIntensitiesData(intensities=intensities)


def test_set_led_intensities_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SetLedIntensitiesData(intensities={0: 1}, exclusive=True)


def test_set_led_intensities_publisher_round_trips_to_the_handler(service, monkeypatch):
    import microdrop_utils.dramatiq_pub_sub_helpers as helpers

    sent = []
    monkeypatch.setattr(
        helpers,
        "publish_message",
        lambda message, topic, **kw: sent.append((topic, message)),
    )
    set_led_intensities_publisher.publish(intensities={2: 30, 1: 0})

    [(topic, message)] = sent
    assert topic == SET_LED_INTENSITIES

    service.on_set_led_intensities_request(message)
    assert service.proxy.sent == ["led_1_0", "led_2_30"]


# --- protocol step with a Multi-Channel mix (#31) ----------------------------


@pytest.fixture
def acks(monkeypatch):
    sink = []
    monkeypatch.setattr(
        setter_module,
        "publish_message",
        lambda topic, message, **kw: sink.append((topic, message)),
    )
    monkeypatch.setattr(setter_module.time, "sleep", lambda seconds: None)
    return sink


def test_protocol_mix_sets_every_frequency_then_every_duty_then_acks(service, acks):
    body = json.dumps(
        {
            "light_on": True,
            "intensities": {"0": 80, "1": 0, "2": 48},
            "frequency": 1000,
            "settle_s": 0.2,
        }
    )
    service.on_protocol_set_fluorescence_request(body)

    assert service.proxy.sent == [
        *[f"ledf_{led}_1000" for led in range(6)],
        "led_0_80",
        "led_1_0",
        "led_2_48",
    ]
    assert acks == [(FLUORESCENCE_APPLIED, "1")]


def test_protocol_single_led_is_unchanged(service, acks):
    body = json.dumps(
        {"light_on": True, "led": 2, "duty": 15, "frequency": 1000, "settle_s": 0}
    )
    service.on_protocol_set_fluorescence_request(body)

    assert service.proxy.sent == ["ledf_2_1000", "led_off", "led_2_15"]
    assert acks == [(FLUORESCENCE_APPLIED, "1")]


def test_protocol_light_on_needs_an_led_or_a_mix():
    with pytest.raises(ValidationError):
        ProtocolSetFluorescenceData(light_on=True, frequency=1000, settle_s=0)

    # Light off needs neither.
    ProtocolSetFluorescenceData(light_on=False, frequency=1000, settle_s=0)


@pytest.mark.parametrize("intensities", [{0: 101}, {6: 10}])
def test_protocol_mix_bounds_are_enforced(intensities):
    with pytest.raises(ValidationError):
        ProtocolSetFluorescenceData(
            light_on=True, intensities=intensities, frequency=1000, settle_s=0
        )
