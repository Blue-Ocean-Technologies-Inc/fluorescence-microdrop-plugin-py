"""Hardware-free tests for the per-mode camera exposure/gain controls.

The controls pane is the ONLY editor (no device-viewer settings row): the
current mode's br_/fl_ pair is mirrored into the shared asi_camera_settings,
which a running ASI feed applies to the camera live — mode switches swap the
camera settings exactly like the standalone UI did.
"""
from fluorescence_controls_ui.cameras.camera_settings import asi_camera_settings
from fluorescence_controls_ui.controller import FluorescenceControlsController
from fluorescence_controls_ui.model import FluorescenceStatusModel


def _controller():
    model = FluorescenceStatusModel()
    controller = FluorescenceControlsController(model=model)
    controller._push_active_camera_settings(None)   # initial mirror
    return controller, model


def test_defaults_match_standalone_config():
    # milliseconds in the pane (the standalone stored 10_000 / 20_000 us)
    model = FluorescenceStatusModel()
    assert (model.br_exposure, model.br_gain) == (10, 0)
    assert (model.fl_exposure, model.fl_gain) == (20, 300)


def test_pane_edit_reaches_shared_settings_in_microseconds():
    controller, model = _controller()
    model.br_exposure = 12                       # ms
    assert asi_camera_settings.exposure == 12_000  # us at the camera


def test_mode_switch_swaps_camera_settings():
    controller, model = _controller()
    model.br_exposure = 11
    model.mode = "fl"
    assert (asi_camera_settings.exposure, asi_camera_settings.gain) == (
        model.fl_exposure * 1000, model.fl_gain)
    model.mode = "br"
    assert asi_camera_settings.exposure == 11_000


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
    model.br_exposure = 15                       # ms
    assert applied[-1][0] == 15_000              # us at the camera

    # ...and stop() unregisters them (and must not raise, or the camera
    # thread would never be stopped and the camera would stay locked).
    feed.stop()
    applied.clear()
    model.br_exposure = 16
    assert applied == []


def test_no_device_viewer_settings_row():
    from fluorescence_controls_ui.cameras.provider import AsiCameraFeed
    assert not hasattr(AsiCameraFeed, "create_controls")
