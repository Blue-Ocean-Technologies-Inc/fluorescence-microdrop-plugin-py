# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for the burst capture service (issue #6, Task 6):
the active-feed registry on `AsiCameraFeed`, the applied-ack Event,
`burst_folder` naming, and `run_burst`'s per-entry apply/publish/wait/save
sequence — including the finally-block ALL_LEDS_OFF on both the happy and
timeout paths.

No real ASI hardware anywhere: `ASIVideoThread` is replaced with a fake
(mirrors test_camera_settings.py's `FakeThread` convention) for the
registry tests, and `run_burst`'s feed is a tiny stub carrying the two
attributes `wait_for_frame_after` needs (`frame_seq`, `_last_raw`). The
frame-handoff tests drive a real, never-started `ASIVideoThread` from a
plain Python thread: no camera and no GUI event loop.
"""

# Standard library imports.
import sys
import threading
import time

# Third-party imports.
import numpy as np
import pytest

# Microdrop package imports.
import fluorescence_controls_ui
from fluorescence_controller.consts import ALL_LEDS_OFF, LED_WAVELENGTHS
from fluorescence_controls_ui.consts import (
    CAPTURE_PARTIAL_SUFFIX,
    CAPTURE_PNG_QUALITY,
)
from fluorescence_protocol_controls.capture_chain import ChainEntry

ENTRY_KW = dict(
    wavelength=LED_WAVELENGTHS[0],
    intensity=50,
    frequency=1000,
    exposure_ms=10.0,
    gain=0,
)

capture_service = None  # populated by _capture_service_module below


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
    preview_ready_signal = _FakeSignal()
    camera_caps_signal = _FakeSignal()
    temperature_signal = _FakeSignal()
    auto_values_signal = _FakeSignal()
    error_signal = _FakeSignal()

    def __init__(self, *args, **kwargs):
        from fluorescence_controls_ui.cameras.asi_thread import FrameMailbox

        self.frames = FrameMailbox()

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


def test_feed_reads_frames_from_the_thread_mailbox(provider_module):
    feed = provider_module.AsiCameraFeed("sdk", 0)

    try:
        assert feed.frame_seq == 0
        assert feed._last_raw is None

        raw = np.zeros((2, 2), dtype=np.uint16)
        feed._thread.frames.put(raw)
        assert feed.frame_seq == 1
        assert feed._last_raw is raw

        feed._thread.frames.put(raw)
        assert feed.frame_seq == 2
    finally:
        feed.stop()


# --- FrameMailbox --------------------------------------------------------


@pytest.fixture
def mailbox():
    from fluorescence_controls_ui.cameras.asi_thread import FrameMailbox

    return FrameMailbox()


def test_wait_after_returns_true_once_seq_advances(mailbox):
    mailbox.put(np.zeros((2, 2), dtype=np.uint16))
    assert mailbox.wait_after(0, timeout=0.5) is True


def test_wait_after_times_out_when_seq_does_not_advance(mailbox):
    mailbox.put(np.zeros((2, 2), dtype=np.uint16))
    assert mailbox.wait_after(1, timeout=0.05) is False


def test_wait_after_requires_a_stored_raw_frame(mailbox):
    # Nothing landed yet: even a wait for "anything newer" times out.
    assert mailbox.wait_after(-1, timeout=0.05) is False


# --- camera-thread frame handoff (no GUI event loop) ---------------------


@pytest.fixture
def video_thread():
    """A real ASIVideoThread that is never started: tests call its
    capture-loop steps directly, from whichever thread they choose."""
    from fluorescence_controls_ui.cameras.asi_thread import ASIVideoThread

    return ASIVideoThread("sdk", 0)


def test_frame_seq_advances_on_the_camera_thread_without_a_gui_loop():
    from fluorescence_controls_ui.cameras import provider

    feed = provider.AsiCameraFeed("sdk", 0)
    # Captures alone: no preview notification is ever queued to the GUI.
    feed._thread.preview_enabled = False
    raw = np.full((2, 2), 7, dtype=np.uint16)

    try:
        camera_thread = threading.Thread(
            target=feed._thread._hand_off_frame, args=(raw,)
        )
        camera_thread.start()
        camera_thread.join(timeout=2.0)

        assert feed.frame_seq == 1
        assert feed._last_raw is raw
    finally:
        feed.stop()


def test_wait_for_frame_after_wakes_on_the_camera_thread_update():
    from fluorescence_controls_ui.cameras import provider

    feed = provider.AsiCameraFeed("sdk", 0)
    # Captures alone: no preview notification is ever queued to the GUI.
    feed._thread.preview_enabled = False
    raw = np.full((2, 2), 7, dtype=np.uint16)
    seq = feed.frame_seq
    camera_thread = threading.Timer(0.1, feed._thread._hand_off_frame, args=(raw,))

    try:
        camera_thread.start()
        started = time.monotonic()

        assert feed.wait_for_frame_after(seq, timeout=5.0) is True
        assert time.monotonic() - started < 2.0
        assert feed._last_raw is raw
    finally:
        camera_thread.cancel()
        feed.stop()


def test_pending_preview_frames_coalesce_to_the_newest(video_thread):
    notifications = []
    video_thread.preview_ready_signal.connect(lambda: notifications.append(1))
    video_thread.preview_enabled = True
    frames = [np.full((2, 2), value, dtype=np.uint16) for value in (1, 2, 3)]

    for frame in frames:
        video_thread._hand_off_frame(frame)

    # One notification for the whole backlog; the GUI takes the newest.
    assert len(notifications) == 1
    assert video_thread.frames.take_preview() is frames[-1]

    video_thread._hand_off_frame(frames[0])
    assert len(notifications) == 2


def test_no_preview_notification_while_the_stream_is_off(video_thread):
    notifications = []
    video_thread.preview_ready_signal.connect(lambda: notifications.append(1))
    video_thread.preview_enabled = False

    video_thread._hand_off_frame(np.zeros((2, 2), dtype=np.uint16))

    assert notifications == []
    assert video_thread.frames.seq == 1


def test_camera_settings_apply_on_the_capture_loop(video_thread):
    applied = []

    class _Camera:
        def set_camera_settings(self, exposure, gain):
            applied.append((exposure, gain))

    video_thread.camera = _Camera()
    video_thread.set_camera_settings(exposure=5_000)
    assert applied == []

    video_thread._apply_pending_camera_settings()
    assert applied == [(5_000, video_thread.gain)]
    assert video_thread.exposure == 5_000


def test_apply_camera_settings_reaches_the_feed_without_the_gui(monkeypatch):
    """A stalled GUI (invoke_later never runs) must not hold back the
    entry's exposure/gain on their way to the camera."""
    received = []

    class _Feed:
        def apply_capture_settings(self, **settings):
            received.append(settings)

    monkeypatch.setattr(capture_service, "current_feed", lambda: _Feed())
    monkeypatch.setattr(
        capture_service.GUI, "invoke_later", lambda func, *args, **kwargs: None
    )

    capture_service.apply_camera_settings(_entry("A", exposure_ms=12.5, gain=40))

    assert received == [
        dict(exposure=12_500, gain=40, auto_exposure=False, auto_gain=False)
    ]


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
        capture_service, "get_current_experiment_directory", lambda: tmp_path
    )
    return tmp_path


def test_burst_folder_uses_step_desc_and_dotted_id_when_both_given(
    experiment_dir, frozen_time
):
    folder = capture_service.burst_folder("My Step!", "1.2")
    expected = experiment_dir / "captures" / "My_Step_1.2_2026_07_16-12_30_45"
    assert folder == expected
    assert folder.is_dir()
    assert (folder / "16bit_raw").is_dir()


def test_burst_folder_dotted_id_alone_names_the_folder(experiment_dir, frozen_time):
    folder = capture_service.burst_folder(None, "1.2")
    expected = experiment_dir / "captures" / "1.2_2026_07_16-12_30_45"
    assert folder == expected


def test_burst_folder_falls_back_to_free_mode(experiment_dir, frozen_time):
    folder = capture_service.burst_folder(None, None)
    expected = experiment_dir / "captures" / "free_mode_2026_07_16-12_30_45"
    assert folder == expected


def test_burst_folder_desc_alone_names_the_folder(experiment_dir, frozen_time):
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

    def apply_capture_settings(self, **settings):
        pass


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
        calls.append(
            dict(
                light_on=light_on,
                led=led,
                duty=duty,
                frequency=frequency,
                settle_s=settle_s,
            )
        )
        capture_service.notify_applied()

    monkeypatch.setattr(
        capture_service.protocol_set_fluorescence_publisher, "publish", fake_publish
    )
    return calls


@pytest.fixture
def off_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        capture_service,
        "publish_message",
        lambda topic, message: calls.append((topic, message)),
    )
    return calls


@pytest.fixture
def sync_gui(monkeypatch):
    monkeypatch.setattr(
        capture_service.GUI,
        "invoke_later",
        lambda func, *args, **kwargs: func(*args, **kwargs),
    )


def test_run_burst_happy_path_saves_only_ticked_entries(
    experiment_dir, frozen_time, run_feed, publish_recorder, off_calls, sync_gui
):
    entries = [
        _entry("A"),
        _entry("B", run=False),
    ]
    folder = capture_service.run_burst(entries, step_desc="My Step", dotted_id="1.1")

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
    assert not list(folder.rglob(f"*{CAPTURE_PARTIAL_SUFFIX}"))

    assert off_calls == [(ALL_LEDS_OFF, "")]


def test_run_burst_empty_ticked_chain_still_turns_leds_off(
    experiment_dir, frozen_time, run_feed, publish_recorder, off_calls, sync_gui
):
    entries = [_entry("A", run=False)]
    capture_service.run_burst(entries, step_desc=None, dotted_id=None)
    assert publish_recorder == []
    assert off_calls == [(ALL_LEDS_OFF, "")]


def test_run_burst_timeout_raises_and_still_turns_leds_off(
    experiment_dir, frozen_time, run_feed, off_calls, sync_gui, monkeypatch
):
    # Publisher that never acks -> wait_applied must time out.
    calls = []
    monkeypatch.setattr(
        capture_service.protocol_set_fluorescence_publisher,
        "publish",
        lambda **kw: calls.append(kw),
    )
    capture_service.arm_applied()  # ensure no stray ack from another test

    entries = [_entry("SlowOne")]
    with pytest.raises(TimeoutError, match="SlowOne"):
        capture_service.run_burst(
            entries, step_desc=None, dotted_id=None, applied_timeout=0.05
        )

    assert len(calls) == 1
    assert off_calls == [(ALL_LEDS_OFF, "")]


@pytest.fixture
def capture_order(monkeypatch):
    """One ordered log of run_burst's ack wait, lead-time sleep, and frame
    grab: the ack auto-succeeds, the sleep returns at once (patched on
    capture_service's `time`, as `frozen_time` patches gmtime), and the
    grab is recorded instead of saved."""
    order = []

    def wait_applied(timeout):
        order.append("ack")

        return True

    monkeypatch.setattr(capture_service, "wait_applied", wait_applied)
    monkeypatch.setattr(
        capture_service.time, "sleep", lambda seconds: order.append(("lead", seconds))
    )
    monkeypatch.setattr(
        capture_service,
        "save_entry_capture",
        lambda entry, folder: order.append(("grab", entry.label)),
    )

    return order


def test_run_burst_waits_camera_lead_time_after_the_ack_before_the_grab(
    experiment_dir, frozen_time, publish_recorder, off_calls, sync_gui, capture_order
):
    entries = [_entry("A", camera_lead_time_ms=2000), _entry("B")]

    capture_service.run_burst(entries)

    # The entry stores milliseconds; time.sleep takes seconds.
    assert capture_order == [
        "ack",
        ("lead", 2.0),
        ("grab", "A"),
        "ack",
        ("grab", "B"),
    ]


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


# --- save_png_atomically -------------------------------------------------


class _RecordingImage:
    """QImage stand-in: records what the final path looked like while the
    encode was in flight, then writes (or fails to write) the partial
    file."""

    def __init__(self, final_path, succeed=True):
        self.final_path = final_path
        self.succeed = succeed
        self.calls = []

    def save(self, path, image_format, quality):
        self.calls.append(
            dict(
                path=path,
                image_format=image_format,
                quality=quality,
                final_existed=self.final_path.exists(),
            )
        )

        if not self.succeed:
            return False

        with open(path, "wb") as partial_file:
            partial_file.write(b"\x89PNG half")
            # Mid-encode: only the partial name exists.
            assert not self.final_path.exists()
            partial_file.write(b" and the rest")

        return True


def test_save_png_atomically_hides_the_file_until_it_is_complete(tmp_path):
    final_path = tmp_path / "A_2026_07_16-12_30_45.png"
    image = _RecordingImage(final_path)

    capture_service.save_png_atomically(image, final_path)

    (call,) = image.calls
    assert call["final_existed"] is False
    assert call["path"] == str(final_path) + CAPTURE_PARTIAL_SUFFIX
    assert call["image_format"] == "PNG"
    assert call["quality"] == CAPTURE_PNG_QUALITY

    assert final_path.read_bytes() == b"\x89PNG half and the rest"
    assert list(tmp_path.iterdir()) == [final_path]


def test_save_png_atomically_raises_and_leaves_nothing_on_failure(tmp_path):
    final_path = tmp_path / "A_2026_07_16-12_30_45.png"

    with pytest.raises(OSError, match="A_2026_07_16-12_30_45.png"):
        capture_service.save_png_atomically(
            _RecordingImage(final_path, succeed=False), final_path
        )

    assert list(tmp_path.iterdir()) == []
