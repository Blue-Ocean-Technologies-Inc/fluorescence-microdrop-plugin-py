"""Hardware-free tests for the single-set camera exposure/gain controls.

The controls pane is the ONLY editor (no device-viewer settings row): the
single param set's exposure/gain pair is mirrored into the shared
asi_camera_settings, which a running ASI feed applies to the camera live.
Reworked for the single param set (issue #6, no more br/fl mode split).
"""
from apptools.preferences.api import Preferences

from fluorescence_controls_ui.cameras.camera_settings import asi_camera_settings
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences


def _controller():
    # In-memory preferences: the model's preferences default to the
    # process-wide "microdrop.peripheral_settings" node, which would
    # otherwise leak exposure/gain edits across tests.
    model = FluorescenceStatusModel(
        preferences=FluorescencePreferences(preferences=Preferences()))
    controller = FluorescenceControlsController(model=model)
    return controller, model


def test_defaults_match_standalone_config():
    # milliseconds in the pane (the standalone stored 10_000 us)
    model = FluorescenceStatusModel()
    assert (model.exposure, model.gain) == (10, 0)


def test_pane_edit_reaches_shared_settings_in_microseconds():
    controller, model = _controller()
    model.exposure = 12                       # ms
    assert asi_camera_settings.exposure == 12_000  # us at the camera


def test_gain_edit_reaches_shared_settings():
    controller, model = _controller()
    model.gain = 42
    assert asi_camera_settings.gain == 42


def test_camera_push_gated_off_during_protocol_run():
    controller, model = _controller()
    model.protocol_running = True
    model.exposure = 33
    assert asi_camera_settings.exposure != 33_000


def test_running_feed_applies_pane_edits(monkeypatch):
    from fluorescence_controls_ui.cameras import provider

    applied = []

    class FakeSignal:
        def connect(self, *args):
            pass

    class FakeThread:
        change_pixmap_signal = FakeSignal()
        camera_caps_signal = FakeSignal()
        temperature_signal = FakeSignal()
        auto_values_signal = FakeSignal()
        error_signal = FakeSignal()

        def __init__(self, sdk_dir, camera_id, exposure=None, gain=None,
                     advanced=None):
            pass

        def set_camera_settings(self, exposure=None, gain=None):
            applied.append((exposure, gain))

        def set_auto_settings(self, **settings):
            pass

        def stop(self):
            pass

        def wait(self, timeout):
            pass

    monkeypatch.setattr(provider, "ASIVideoThread", FakeThread)
    controller, model = _controller()

    # The feed registers its own observers on construction...
    feed = provider.AsiCameraFeed("sdk", 0)
    model.exposure = 15                       # ms
    assert applied[-1][0] == 15_000              # us at the camera

    # ...and stop() unregisters them (and must not raise, or the camera
    # thread would never be stopped and the camera would stay locked).
    feed.stop()
    applied.clear()
    model.exposure = 16
    assert applied == []


def test_no_device_viewer_settings_row():
    from fluorescence_controls_ui.cameras.provider import AsiCameraFeed
    assert not hasattr(AsiCameraFeed, "create_controls")
