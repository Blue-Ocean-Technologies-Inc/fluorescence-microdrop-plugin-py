"""Hardware-free tests for the burst capture service (issue #6, Task 6):
the active-feed registry on `AsiCameraFeed`, the applied-ack Event,
`burst_folder` naming, and `run_burst`'s per-entry apply/publish/wait/save
sequence — including the finally-block ALL_LEDS_OFF on both the happy and
timeout paths.

No real ASI hardware anywhere: `ASIVideoThread` is replaced with a fake
(mirrors test_camera_settings.py's `FakeThread` convention) for the
registry tests, and `run_burst`'s feed is a tiny stub carrying the two
attributes `wait_for_frame_after` needs (`frame_seq`, `_last_raw`).
"""
import sys
import time

import numpy as np
import pytest

import fluorescence_controls_ui
from fluorescence_controller.consts import ALL_LEDS_OFF, LED_WAVELENGTHS
from fluorescence_protocol_controls.capture_chain import ChainEntry

ENTRY_KW = dict(wavelength=LED_WAVELENGTHS[0], intensity=50, frequency=1000,
                exposure_ms=10.0, gain=0)

capture_service = None   # populated by _capture_service_module below


@pytest.fixture(autouse=True, scope="module")
def _capture_service_module():
    """Import `capture_service` for this module's own tests, then undo the
    package-attribute binding the import creates.

    `import fluorescence_controls_ui.capture_service` binds `capture_service`
    onto the `fluorescence_controls_ui` package object as a side effect. Left
    in place, that binding outlives this module: CPython's `IMPORT_FROM`
    resolves `from fluorescence_controls_ui import capture_service` (as
    controller.py's `run_capture` does) via `getattr(package,
    "capture_service")` FIRST, only falling back to `sys.modules` on
    AttributeError. So a leftover attribute silently shadows the
    `sys.modules["fluorescence_controls_ui.capture_service"]` fake module
    that test_led_controls.py's `fake_capture_service` fixture installs,
    and controller.py ends up calling the real `run_burst` instead of the
    fake — deterministically breaking whichever test_led_controls case runs
    after this module. Deleting the attribute (and the cached module) here
    restores the clean-slate precondition that mocking strategy needs.
    """
    global capture_service
    import fluorescence_controls_ui.capture_service as _capture_service
    capture_service = _capture_service
    yield
    if hasattr(fluorescence_controls_ui, "capture_service"):
        delattr(fluorescence_controls_ui, "capture_service")
    sys.modules.pop("fluorescence_controls_ui.capture_service", None)


def _entry(label, run=True, **overrides):
    kw = dict(ENTRY_KW, **overrides)
    return ChainEntry(label=label, run=run, **kw)


# --- provider registry (_ACTIVE_FEED / current_feed / frame_seq) -------

class _FakeSignal:
    def connect(self, *args):
        pass


class _FakeThread:
    change_pixmap_signal = _FakeSignal()
    camera_caps_signal = _FakeSignal()
    temperature_signal = _FakeSignal()
    auto_values_signal = _FakeSignal()
    error_signal = _FakeSignal()

    def __init__(self, *args, **kwargs):
        pass

    def set_auto_settings(self, **settings):
        pass

    def stop(self):
        pass

    def wait(self, timeout):
        pass


@pytest.fixture
def provider_module(monkeypatch):
    from fluorescence_controls_ui.cameras import provider
    monkeypatch.setattr(provider, "ASIVideoThread", _FakeThread)
    return provider


def test_current_feed_is_none_before_any_feed(provider_module):
    assert provider_module.current_feed() is None


def test_init_registers_feed_as_active(provider_module):
    feed = provider_module.AsiCameraFeed("sdk", 0)
    try:
        assert provider_module.current_feed() is feed
    finally:
        feed.stop()


def test_stop_clears_registry_when_still_active(provider_module):
    feed = provider_module.AsiCameraFeed("sdk", 0)
    feed.stop()
    assert provider_module.current_feed() is None


def test_stop_does_not_clear_registry_when_superseded(provider_module):
    feed1 = provider_module.AsiCameraFeed("sdk", 0)
    feed2 = provider_module.AsiCameraFeed("sdk", 1)
    try:
        assert provider_module.current_feed() is feed2
        feed1.stop()
        assert provider_module.current_feed() is feed2
    finally:
        feed2.stop()


def test_frame_seq_increments_before_last_raw_is_stored(provider_module):
    feed = provider_module.AsiCameraFeed("sdk", 0)
    try:
        assert feed.frame_seq == 0
        assert feed._last_raw is None
        raw = np.zeros((2, 2), dtype=np.uint16)
        feed._on_thread_frame(raw)
        assert feed.frame_seq == 1
        assert feed._last_raw is raw
        feed._on_thread_frame(raw)
        assert feed.frame_seq == 2
    finally:
        feed.stop()


# --- wait_for_frame_after (real method, bound onto a plain stub) -------

@pytest.fixture
def frame_stub_cls(provider_module):
    class _Stub:
        wait_for_frame_after = provider_module.AsiCameraFeed.wait_for_frame_after

        def __init__(self, frame_seq=0, raw=None):
            self.frame_seq = frame_seq
            self._last_raw = raw
    return _Stub


def test_wait_for_frame_after_returns_true_once_seq_advances(frame_stub_cls):
    stub = frame_stub_cls(frame_seq=5, raw=np.zeros((2, 2), dtype=np.uint16))
    assert stub.wait_for_frame_after(4, timeout=0.5) is True


def test_wait_for_frame_after_times_out_when_seq_does_not_advance(frame_stub_cls):
    stub = frame_stub_cls(frame_seq=4, raw=np.zeros((2, 2), dtype=np.uint16))
    assert stub.wait_for_frame_after(4, timeout=0.05) is False


def test_wait_for_frame_after_requires_a_stored_raw_frame(frame_stub_cls):
    # seq advanced but no frame landed yet: must still time out.
    stub = frame_stub_cls(frame_seq=5, raw=None)
    assert stub.wait_for_frame_after(4, timeout=0.05) is False


# --- notify_applied / arm_applied / wait_applied ------------------------

def test_wait_applied_false_until_notified():
    capture_service.arm_applied()
    assert capture_service.wait_applied(0.05) is False


def test_notify_applied_unblocks_wait_applied():
    capture_service.arm_applied()
    capture_service.notify_applied()
    assert capture_service.wait_applied(0.5) is True


def test_arm_applied_clears_a_previous_notification():
    capture_service.notify_applied()
    capture_service.arm_applied()
    assert capture_service.wait_applied(0.05) is False


# --- burst_folder --------------------------------------------------------

FIXED_UTC = time.struct_time((2026, 7, 16, 12, 30, 45, 0, 0, 0))


@pytest.fixture
def frozen_time(monkeypatch):
    monkeypatch.setattr(capture_service.time, "gmtime", lambda: FIXED_UTC)


@pytest.fixture
def experiment_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        capture_service, "get_current_experiment_directory",
        lambda: tmp_path)
    return tmp_path


def test_burst_folder_uses_step_desc_and_dotted_id_when_both_given(
        experiment_dir, frozen_time):
    folder = capture_service.burst_folder("My Step!", "1.2")
    expected = experiment_dir / "captures" / "My_Step_1.2_2026_07_16-12_30_45"
    assert folder == expected
    assert folder.is_dir()
    assert (folder / "16bit_raw").is_dir()


def test_burst_folder_dotted_id_alone_names_the_folder(
        experiment_dir, frozen_time):
    folder = capture_service.burst_folder(None, "1.2")
    expected = experiment_dir / "captures" / "1.2_2026_07_16-12_30_45"
    assert folder == expected


def test_burst_folder_falls_back_to_free_mode(experiment_dir, frozen_time):
    folder = capture_service.burst_folder(None, None)
    expected = experiment_dir / "captures" / "free_mode_2026_07_16-12_30_45"
    assert folder == expected


def test_burst_folder_desc_alone_names_the_folder(
        experiment_dir, frozen_time):
    folder = capture_service.burst_folder("Desc", None)
    expected = experiment_dir / "captures" / "Desc_2026_07_16-12_30_45"
    assert folder == expected


# --- run_burst -----------------------------------------------------------

class _RunFeed:
    """Minimal feed stub for run_burst/save_entry_capture: every
    `wait_for_frame_after` call simulates a fresh frame landing."""

    def __init__(self):
        self.frame_seq = 0
        self._last_raw = None

    def wait_for_frame_after(self, seq, timeout):
        self.frame_seq += 1
        self._last_raw = np.full((2, 2), 1000, dtype=np.uint16)
        return True


@pytest.fixture
def run_feed(monkeypatch):
    feed = _RunFeed()
    monkeypatch.setattr(capture_service, "current_feed", lambda: feed)
    return feed


@pytest.fixture
def publish_recorder(monkeypatch):
    """Records protocol_set_fluorescence_publisher.publish calls and
    auto-acks each one (like the backend would after settling)."""
    calls = []

    def fake_publish(*, light_on, led, duty, frequency, settle_s, **kw):
        calls.append(dict(light_on=light_on, led=led, duty=duty,
                          frequency=frequency, settle_s=settle_s))
        capture_service.notify_applied()

    monkeypatch.setattr(
        capture_service.protocol_set_fluorescence_publisher,
        "publish", fake_publish)
    return calls


@pytest.fixture
def off_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        capture_service, "publish_message",
        lambda topic, message: calls.append((topic, message)))
    return calls


@pytest.fixture
def sync_gui(monkeypatch):
    monkeypatch.setattr(
        capture_service.GUI, "invoke_later",
        lambda func, *args, **kwargs: func(*args, **kwargs))


def test_run_burst_happy_path_saves_only_ticked_entries(
        experiment_dir, frozen_time, run_feed, publish_recorder, off_calls,
        sync_gui):
    entries = [
        _entry("A"),
        _entry("B", run=False),
    ]
    folder = capture_service.run_burst(
        entries, step_desc="My Step", dotted_id="1.1")

    assert folder.name.startswith("My_Step_1.1_")
    assert len(publish_recorder) == 1
    assert publish_recorder[0]["led"] == entries[0].led_index
    assert publish_recorder[0]["duty"] == entries[0].intensity
    assert publish_recorder[0]["frequency"] == entries[0].frequency

    # Per-capture timestamps in every filename (regular-capture parity).
    assert (folder / "A_2026_07_16-12_30_45.png").exists()
    assert (folder / "16bit_raw" / "A_2026_07_16-12_30_45_raw.png").exists()
    assert not list(folder.glob("B_*.png"))
    assert not list((folder / "16bit_raw").glob("B_*_raw.png"))

    assert off_calls == [(ALL_LEDS_OFF, "")]


def test_run_burst_empty_ticked_chain_still_turns_leds_off(
        experiment_dir, frozen_time, run_feed, publish_recorder, off_calls,
        sync_gui):
    entries = [_entry("A", run=False)]
    capture_service.run_burst(entries, step_desc=None, dotted_id=None)
    assert publish_recorder == []
    assert off_calls == [(ALL_LEDS_OFF, "")]


def test_run_burst_timeout_raises_and_still_turns_leds_off(
        experiment_dir, frozen_time, run_feed, off_calls, sync_gui,
        monkeypatch):
    # Publisher that never acks -> wait_applied must time out.
    calls = []
    monkeypatch.setattr(
        capture_service.protocol_set_fluorescence_publisher,
        "publish", lambda **kw: calls.append(kw))
    capture_service.arm_applied()   # ensure no stray ack from another test

    entries = [_entry("SlowOne")]
    with pytest.raises(TimeoutError, match="SlowOne"):
        capture_service.run_burst(
            entries, step_desc=None, dotted_id=None, applied_timeout=0.05)

    assert len(calls) == 1
    assert off_calls == [(ALL_LEDS_OFF, "")]


def test_apply_camera_settings_forwards_auto_flags(sync_gui):
    """Per-row auto modes ride into the shared ASI settings alongside
    exposure/gain (with auto on, the capture thread's brightness loop
    owns the values during the settle window)."""
    from fluorescence_controls_ui.cameras.camera_settings import (
        asi_camera_settings,
    )
    entry = _entry("A")
    entry.auto_exposure = True
    entry.auto_gain = True
    capture_service.apply_camera_settings(entry)
    assert asi_camera_settings.auto_exposure is True
    assert asi_camera_settings.auto_gain is True
    entry.auto_exposure = False
    entry.auto_gain = False
    capture_service.apply_camera_settings(entry)
    assert asi_camera_settings.auto_exposure is False
    assert asi_camera_settings.auto_gain is False
