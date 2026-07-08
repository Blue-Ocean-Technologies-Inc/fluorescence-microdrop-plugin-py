"""Hardware-free tests for the whoami identity probe.

The proxy sends whoami on connect; the board's WHOAMI frame is published as
BOARD_ID (never as log telemetry), and the monitor claims only ports whose
device_id matches this plugin (the heater board shares the same VID:PID).
"""
import json

import pytest

import fluorescence_controller.fluorescence_serial_proxy as proxy_mod
from fluorescence_controller.fluorescence_serial_proxy import (
    FluorescenceSerialProxy, parse_whoami_line,
)
import fluorescence_controller.services.fluorescence_monitor_mixin_service as monitor_mod
from fluorescence_controller.services.fluorescence_monitor_mixin_service import (
    FluorescenceMonitorMixinService,
)

WHOAMI_LINE = '\u00a7WHOAMI{"uid": "a1b2c3d4", "device_id": "fluo_board"}'


@pytest.fixture
def published(monkeypatch):
    sink = []
    monkeypatch.setattr(
        proxy_mod, "publish_message",
        lambda message=None, topic=None, **k: sink.append((topic, message)))
    return sink


def test_parse_whoami_line():
    assert parse_whoami_line(WHOAMI_LINE) == {"uid": "a1b2c3d4",
                                              "device_id": "fluo_board"}
    assert parse_whoami_line("LED 0 set to 38% duty cycle") is None
    assert parse_whoami_line("\u00a7WHOAMI{broken") is None


def test_whoami_becomes_board_id_not_log_spam(published):
    proxy = FluorescenceSerialProxy.__new__(FluorescenceSerialProxy)
    proxy._handle_line("LED 0 set to 38% duty cycle")   # normal ack
    proxy._handle_line(WHOAMI_LINE)
    proxy._handle_line("All LEDs turned off")           # normal ack

    topics = [topic for topic, _ in published]
    assert topics == ["Fluorescence/signals/telemetry",
                      "Fluorescence/signals/board_id",
                      "Fluorescence/signals/telemetry"]
    assert json.loads(published[1][1])["device_id"] == "fluo_board"


def test_monitor_claims_only_fluo_identified_port(monkeypatch):
    claimed = {}
    monkeypatch.setattr(
        monitor_mod, "find_port_by_device_id",
        lambda hwids, fragment: claimed.setdefault("args", (list(hwids), fragment)) and "COM7"
        or "COM7")
    service = FluorescenceMonitorMixinService()
    port = service._find_port(["VID:PID=2E8A:0005"])
    assert port == "COM7"
    assert claimed["args"] == (["VID:PID=2E8A:0005"], "fluo")
