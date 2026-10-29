# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

# (C) Copyright 2026-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for a protocol run's capture session on the pane side:
the message handler marshals the camera session onto the GUI thread and
ferries the flag to live_state, and the controller turns the Device View
Camera Feed on for the run, then back off at the end only if the run turned
it on. `GUI.invoke_later` is patched, so no camera ever opens."""

# Standard library imports.
import json
from types import SimpleNamespace

# Third-party imports.
import pytest

# Enthought library imports.
from apptools.preferences.api import Preferences
from traits.api import HasTraits, Instance, List, observe

# Microdrop package imports.
from fluorescence_controls_ui import camera_session
from fluorescence_controls_ui.cameras.camera_settings import asi_camera_settings
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.live_state import (
    FluorescenceLiveState,
    fluorescence_live_state,
)
from fluorescence_controls_ui.message_handler import FluorescenceMessageHandler
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences


@pytest.fixture(autouse=True)
def _isolate_singletons():
    # The run bookkeeping and the camera settings are module singletons.
    stream = asi_camera_settings.device_viewer_stream
    fluorescence_live_state.device_viewer_stream_enabled_by_run = False
    yield
    fluorescence_live_state.device_viewer_stream_enabled_by_run = False
    asi_camera_settings.device_viewer_stream = stream


def _controller(device_viewer_stream):
    """A running-protocol controller/model pair (the run suppresses the
    pane's own board publishes) with the given Device View Camera Feed."""
    # In-memory preferences: device_viewer_stream is a persisted control,
    # restored from them on construction — so it is set afterwards.
    model = FluorescenceStatusModel(
        preferences=FluorescencePreferences(preferences=Preferences())
    )
    controller = FluorescenceControlsController(model=model)
    model.trait_set(protocol_running=True, device_viewer_stream=device_viewer_stream)

    return controller, model


def _session(controller, active):
    controller._on_protocol_session_active(SimpleNamespace(new=active))


# --- controller: Device View Camera Feed bookkeeping --------------------------


def test_session_start_turns_the_stream_on_and_remembers_it():
    controller, model = _controller(device_viewer_stream=False)

    _session(controller, True)

    assert model.device_viewer_stream is True
    assert asi_camera_settings.device_viewer_stream is True
    assert fluorescence_live_state.device_viewer_stream_enabled_by_run is True


def test_session_end_restores_the_stream_the_run_turned_on():
    controller, model = _controller(device_viewer_stream=False)
    _session(controller, True)

    _session(controller, False)

    assert model.device_viewer_stream is False
    assert asi_camera_settings.device_viewer_stream is False
    assert fluorescence_live_state.device_viewer_stream_enabled_by_run is False


def test_stream_already_on_is_left_on_at_the_end():
    controller, model = _controller(device_viewer_stream=True)

    _session(controller, True)

    assert fluorescence_live_state.device_viewer_stream_enabled_by_run is False

    _session(controller, False)

    assert model.device_viewer_stream is True


def test_a_repeated_session_start_keeps_the_restore():
    # A second start (e.g. the previous run's end never arrived) finds the
    # stream on — but the run still owes the operator its restore.
    controller, model = _controller(device_viewer_stream=False)
    _session(controller, True)
    _session(controller, True)

    _session(controller, False)

    assert model.device_viewer_stream is False


def test_session_end_drops_the_live_mirror():
    controller, model = _controller(device_viewer_stream=True)
    _session(controller, True)

    assert model.stream_active is True

    model.light_on = True

    _session(controller, False)

    assert model.stream_active is False
    assert model.light_on is False
    assert model.chain_selection is None


# --- message handler: GUI marshalling + live_state ferry ----------------------


@pytest.fixture
def invoked(monkeypatch):
    from pyface.api import GUI

    calls = []
    monkeypatch.setattr(
        GUI, "invoke_later", lambda func, *args, **kwargs: calls.append(func)
    )

    return calls


class _SessionRecorder(HasTraits):
    """Records every session flag ferried to live_state."""

    live_state = Instance(FluorescenceLiveState)

    received = List()

    @observe("live_state:protocol_session_active")
    def _record(self, event):
        self.received.append(event.new)


@pytest.fixture
def sessions():
    recorder = _SessionRecorder(live_state=fluorescence_live_state)
    yield recorder.received
    recorder.live_state = None


def _handler():
    return FluorescenceMessageHandler(
        model=FluorescenceStatusModel(), name="fluorescence_controls_ui_listener"
    )


@pytest.mark.parametrize(
    "active, camera_call", [(True, "activate"), (False, "deactivate")]
)
def test_session_message_marshals_camera_and_ferries_flag(
    invoked, sessions, active, camera_call
):
    _handler()._on_protocol_fluorescence_session_triggered(
        json.dumps({"active": active})
    )

    assert invoked == [getattr(camera_session, camera_call)]
    assert sessions == [active]


def test_unparseable_session_message_does_nothing(invoked, sessions):
    _handler()._on_protocol_fluorescence_session_triggered("not json")
    _handler()._on_protocol_fluorescence_session_triggered(json.dumps({}))

    assert invoked == []
    assert sessions == []
