# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for the whoami identity probe.

The proxy sends whoami on connect; the board's WHOAMI frame is published as
BOARD_ID (never as log telemetry), and the monitor claims only ports whose
device_id matches this plugin (the heater board shares the same VID:PID).
"""

# Standard library imports.
import json

# Third-party imports.
import pytest

# Microdrop package imports.
import fluorescence_controller.fluorescence_serial_proxy as proxy_mod
import peripheral_device_controller_base.services.peripheral_device_monitor_mixin_service as base_monitor_mod  # noqa: E501 -- dotted module path can't be shortened
from fluorescence_controller.fluorescence_serial_proxy import (
    FluorescenceSerialProxy,
    parse_whoami_line,
)
from fluorescence_controller.services.fluorescence_monitor_mixin_service import (
    FluorescenceMonitorMixinService,
)

WHOAMI_LINE = '\u00a7WHOAMI{"uid": "a1b2c3d4", "device_id": "fluo_board"}'


@pytest.fixture
def published(monkeypatch):
    sink = []
    monkeypatch.setattr(
        proxy_mod,
        "publish_message",
        lambda message=None, topic=None, **k: sink.append((topic, message)),
    )
    return sink


def test_parse_whoami_line():
    assert parse_whoami_line(WHOAMI_LINE) == {
        "uid": "a1b2c3d4",
        "device_id": "fluo_board",
    }
    assert parse_whoami_line("LED 0 set to 38% duty cycle") is None
    assert parse_whoami_line("\u00a7WHOAMI{broken") is None


def _bare_proxy(expected_fragment=None):
    proxy = FluorescenceSerialProxy.__new__(FluorescenceSerialProxy)
    proxy.port = "COM7"
    proxy._expected_device_id_fragment = expected_fragment
    return proxy


def test_whoami_becomes_board_id_not_log_spam(published):
    proxy = _bare_proxy()
    proxy._handle_line("LED 0 set to 38% duty cycle")  # normal ack
    proxy._handle_line(WHOAMI_LINE)
    proxy._handle_line("All LEDs turned off")  # normal ack

    topics = [topic for topic, _ in published]
    assert topics == [
        "Fluorescence/signals/telemetry",
        "Fluorescence/signals/board_id",
        "Fluorescence/signals/telemetry",
    ]
    assert json.loads(published[1][1])["device_id"] == "fluo_board"


def test_wrong_board_whoami_relinquishes_port(published):
    proxy = _bare_proxy(expected_fragment="fluo")
    terminated = []
    proxy.terminate = lambda: terminated.append(True)
    proxy._handle_line('§WHOAMI{"uid": "e5f6a7b8", "device_id": "heater_board"}')

    assert terminated == [True]
    assert published == []  # the foreign identity is never published


def test_monitor_claims_only_fluo_identified_port(monkeypatch):
    claimed = {}

    def fake_claim(hwids, fragment, *, min_unidentified_scans=1):
        claimed["args"] = (list(hwids), fragment, min_unidentified_scans)
        return "COM7"

    monkeypatch.setattr(base_monitor_mod, "claim_port_by_device_id", fake_claim)
    service = FluorescenceMonitorMixinService()
    port = service._find_port(["VID:PID=2E8A:0005"])
    assert port == "COM7"
    assert claimed["args"] == (["VID:PID=2E8A:0005"], "fluo", 3)
