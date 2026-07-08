"""Hardware-free tests for the led_help identity probe.

The firmware has no whoami over serial; the proxy sends led_help on connect,
captures the response block whole (never spamming the telemetry log), and
publishes the parsed identity on BOARD_ID.
"""
import json

import pytest

import fluorescence_controller.fluorescence_serial_proxy as proxy_mod
from fluorescence_controller.fluorescence_serial_proxy import (
    FluorescenceSerialProxy, parse_led_help_block, HELP_HEADER, HELP_FOOTER,
)

HELP_LINES = [
    "LED Commands:",
    "  led_<index>_<duty>: Set LED duty cycle (0-100)",
    "LED Index Mapping:",
    "  0: blue", "  1: cyan", "  2: green",
    "  3: orange", "  4: red", "  5: deep_red",
]


@pytest.fixture
def published(monkeypatch):
    sink = []
    monkeypatch.setattr(
        proxy_mod, "publish_message",
        lambda message=None, topic=None, **k: sink.append((topic, message)))
    return sink


def _bare_proxy():
    proxy = FluorescenceSerialProxy.__new__(FluorescenceSerialProxy)
    proxy._help_lines = None
    return proxy


def test_parse_led_help_block_extracts_channels():
    identity = parse_led_help_block(HELP_LINES)
    assert identity == {"name": "LED Controller",
                        "leds": ["blue", "cyan", "green",
                                 "orange", "red", "deep_red"]}


def test_help_block_becomes_board_id_not_log_spam(published):
    proxy = _bare_proxy()
    proxy._handle_line("LED 0 set to 38% duty cycle")   # normal ack
    proxy._handle_line(HELP_HEADER)
    for line in HELP_LINES:
        proxy._handle_line(line)
    proxy._handle_line(HELP_FOOTER)
    proxy._handle_line("All LEDs turned off")           # normal ack

    topics = [topic for topic, _ in published]
    assert topics == ["Fluorescence/signals/telemetry",
                      "Fluorescence/signals/board_id",
                      "Fluorescence/signals/telemetry"]
    identity = json.loads(published[1][1])
    assert identity["name"] == "LED Controller" and len(identity["leds"]) == 6
