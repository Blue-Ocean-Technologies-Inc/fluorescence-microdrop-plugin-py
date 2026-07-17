"""Burst capture service: fires a capture chain's ticked entries against
the shared fluorescence hardware and the active ASI feed, off the GUI
thread. The controls pane's Run Capture button (`controller.run_capture`)
and the protocol column's per-step capture bucket both funnel through
`run_burst`.

Two small synchronization primitives live here too:
  * the applied-ack `Event`, set by `message_handler.py`'s
    FLUORESCENCE_APPLIED listener (worker thread) and waited on here
    (also off the GUI thread) between an LED publish and its capture;
  * `burst_folder`, the per-burst capture directory naming shared by both
    call sites.
"""
import threading
import time
from pathlib import Path

from pyface.gui import GUI

from logger.logger_service import get_logger
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message

from device_viewer.consts import CAPTURES_DIR_NAME, RAW_CAPTURES_SUBDIR
from microdrop_application.helpers import get_current_experiment_directory

from fluorescence_controller.consts import ALL_LEDS_OFF
from fluorescence_controller.datamodels import (
    protocol_set_fluorescence_publisher,
)
from fluorescence_protocol_controls.capture_chain import sanitize_label, ticked
from fluorescence_protocol_controls.consts import LED_STABILIZATION_S

from .cameras.asi_thread import (
    debayered_to_rgb, frame_to_qimage, raw_to_qimage, to_display_8bit,
)
from .cameras.camera_settings import asi_camera_settings
from .cameras.provider import current_feed

logger = get_logger(__name__)

#: Set by message_handler.py's FLUORESCENCE_APPLIED listener (worker
#: thread) on every backend ack; waited on here between an LED publish
#: and its capture. Clear-before-publish (`arm_applied`) so a stale ack
#: from a previous entry can never be mistaken for the current one's.
_APPLIED = threading.Event()


def notify_applied():
    """Worker-thread listener callback: the backend acked the last LED
    apply + settle."""
    _APPLIED.set()


def arm_applied():
    """Clear the applied-ack before publishing, so `wait_applied` can only
    observe an ack for THIS publish."""
    _APPLIED.clear()


def wait_applied(timeout: float) -> bool:
    """Block (off the GUI thread) for the next applied ack."""
    return _APPLIED.wait(timeout)


def burst_folder(step_desc: str | None, dotted_id: str | None,
                 step_id: str | None = None) -> Path:
    """The per-burst capture directory: named from the step's description
    + dotted position when both are known, else the step's uuid prefix,
    else "free_mode" for the pane's untethered chain. Creates the folder
    and its 16-bit raw subdirectory."""
    if step_desc and dotted_id:
        name = f"{sanitize_label(step_desc)}_{dotted_id}"
    elif step_id:
        name = f"step_{step_id[:8]}"
    else:
        name = "free_mode"
    utc = time.strftime("%Y_%m_%d-%H_%M_%S", time.gmtime())
    folder = (get_current_experiment_directory() / CAPTURES_DIR_NAME
             / f"{name}_{utc}")
    (folder / RAW_CAPTURES_SUBDIR).mkdir(parents=True, exist_ok=True)
    return folder


def apply_camera_settings(entry) -> None:
    """Mirror the entry's exposure/gain into the shared ASI settings ON
    THE GUI THREAD (the burst runs off it; the settings singleton and the
    running feed's observers live with the GUI) — same ms->us marshalling
    the deleted per-step compound column's `_apply_camera_settings` used."""
    GUI.invoke_later(asi_camera_settings.trait_set,
                     exposure=int(entry.exposure_ms * 1000), gain=entry.gain)


def save_entry_capture(entry, folder: Path) -> Path:
    """Wait for a fresh frame from the active feed and save it: the raw
    16-bit sensor frame (lossless) under `16bit_raw/`, plus an 8-bit
    display conversion next to it — the SAME conversion chain
    `AsiCameraFeed._on_thread_frame` uses for previews (`to_display_8bit`
    -> `debayered_to_rgb` -> the QImage constructor helper), minus the
    preview-only gamma/contrast/brightness adjustment and timestamp stamp,
    which never touch saved captures either. Returns the display path."""
    feed = current_feed()
    if feed is None:
        raise RuntimeError("no active camera feed")
    seq = feed.frame_seq
    timeout = entry.exposure_ms / 1000.0 * 2 + 2.0
    if not feed.wait_for_frame_after(seq, timeout):
        raise TimeoutError(
            f"No new frame for {entry.label!r} within {timeout}s")
    raw = feed._last_raw
    label = sanitize_label(entry.label)

    raw_path = folder / RAW_CAPTURES_SUBDIR / f"{label}_raw.png"
    raw_to_qimage(raw).save(str(raw_path))

    display_path = folder / f"{label}.png"
    frame_to_qimage(
        debayered_to_rgb(to_display_8bit(raw))).save(str(display_path))
    return display_path


def run_burst(entries, *, step_desc=None, dotted_id=None, step_id=None,
              applied_timeout: float = 5.0) -> Path:
    """Fire the chain's ticked entries in order: apply camera settings,
    publish the LED state, wait for the backend's applied ack, capture.
    ALL_LEDS_OFF always fires on the way out — even on error/timeout — so
    a failed burst can never leave a light on."""
    folder = burst_folder(step_desc, dotted_id, step_id)
    try:
        for entry in ticked(entries):
            apply_camera_settings(entry)
            arm_applied()
            protocol_set_fluorescence_publisher.publish(
                light_on=True, led=entry.led_index, duty=entry.intensity,
                frequency=entry.frequency, settle_s=LED_STABILIZATION_S)
            if not wait_applied(applied_timeout):
                raise TimeoutError(
                    f"LED apply not acknowledged for {entry.label!r}")
            save_entry_capture(entry, folder)
    finally:
        publish_message(topic=ALL_LEDS_OFF, message="")
    return folder
