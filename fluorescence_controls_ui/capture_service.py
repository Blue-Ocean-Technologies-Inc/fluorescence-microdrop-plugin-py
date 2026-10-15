# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Burst capture service: fires a capture chain's ticked entries against
the shared fluorescence hardware and the active ASI feed, off the GUI
thread. The controls pane's Run Capture button (`controller.run_capture`)
runs `run_burst`; the protocol column's per-step capture bucket drives the
same `apply_camera_settings` / `save_entry_capture` steps itself. Every PNG
`save_entry_capture` writes carries its capture settings
(`capture_metadata`) as JSON text under CAPTURE_METADATA_KEY.

Two small synchronization primitives live here too:
  * the applied-ack `Event`, set by `message_handler.py`'s
    FLUORESCENCE_APPLIED listener (worker thread) and waited on here
    (also off the GUI thread) between an LED publish and its capture;
  * `burst_folder`, the per-burst capture directory naming shared by both
    call sites.
"""

# Standard library imports.
import json
import math
import os
import threading
import time
from pathlib import Path

# Third-party imports.
import pint

# Enthought library imports.
from pyface.gui import GUI

# Microdrop package imports.
from device_viewer.consts import CAPTURES_DIR_NAME, RAW_CAPTURES_SUBDIR
from fluorescence_controller.consts import ALL_LEDS_OFF
from fluorescence_controller.datamodels import (
    protocol_set_fluorescence_publisher,
)
from fluorescence_protocol_controls.capture_chain import sanitize_label, ticked
from fluorescence_protocol_controls.consts import LED_STABILIZATION_S
from microdrop_application.helpers import get_current_experiment_directory

# Microdrop utils imports.
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message

# Local imports.
from .cameras.asi_thread import (
    debayered_to_rgb,
    frame_to_qimage,
    raw_to_qimage,
    to_display_8bit,
)
from .cameras.camera_settings import asi_camera_settings
from .cameras.provider import current_feed
from .consts import (
    CAPTURE_FIELD_DESCRIPTIONS,
    CAPTURE_METADATA_KEY,
    CAPTURE_METADATA_VERSION,
    CAPTURE_PARTIAL_SUFFIX,
    CAPTURE_PNG_QUALITY,
    CAPTURE_TIMESTAMP_FORMAT,
)

# Logger import.
from logger.logger_service import get_logger

logger = get_logger(__name__)

#: Formats capture-metadata quantities. Offset units (°C) autoconvert so
#: that ``unit_registry.Quantity(text)`` parses every stored value back,
#: temperatures included — a plain registry rejects "24.6 °C".
unit_registry = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)

#: Twelve significant digits keep every value in these ranges exact
#: (e.g. "12345.678 ms") and out of exponent form; pint's bare "g" rounds
#: to six digits and switches to "2×10⁶" for large values.
_QUANTITY_FORMAT = ".12g~P"

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


# TODO: check for existing utc time method.
def utc_stamp() -> str:
    """UTC timestamp in the shared capture-filename format."""
    return time.strftime(CAPTURE_TIMESTAMP_FORMAT, time.gmtime())


def burst_folder(step_desc: str | None, dotted_id: str | None) -> Path:
    """The per-burst capture directory: `<description>_<dotted>_<utc>`
    from whatever of the step's description and dotted position are
    known; "free_mode" for the pane's untethered chain. Creates the
    folder and its 16-bit raw subdirectory."""
    parts = []
    if step_desc:
        parts.append(sanitize_label(step_desc))
    if dotted_id:
        parts.append(dotted_id)
    name = "_".join(parts) or "free_mode"
    folder = (
        get_current_experiment_directory() / CAPTURES_DIR_NAME / f"{name}_{utc_stamp()}"
    )
    (folder / RAW_CAPTURES_SUBDIR).mkdir(parents=True, exist_ok=True)
    return folder


def apply_camera_settings(entry) -> None:
    """Apply the entry's exposure/gain straight to the active feed's camera
    thread (the burst runs off the GUI thread, and a GUI stall must not
    delay — or outlast — the capture), then mirror them into the shared ASI
    settings ON THE GUI THREAD, where the singleton and the pane live.

    The entry's per-row auto modes ride along: with auto on, the capture
    thread's brightness loop owns exposure/gain during the settle window
    and the stored values are only the starting point."""
    settings = dict(
        exposure=int(entry.exposure_ms * 1000),
        gain=entry.gain,
        auto_exposure=entry.auto_exposure,
        auto_gain=entry.auto_gain,
    )
    feed = current_feed()

    if feed is not None:
        feed.apply_capture_settings(**settings)

    GUI.invoke_later(asi_camera_settings.trait_set, **settings)


def _quantity_text(value, unit, *, display_unit=None) -> str:
    """``value`` in ``unit`` as display text with an abbreviated unit, e.g.
    "120 ms" or "24.6 °C", converted to ``display_unit`` when given."""
    quantity = unit_registry.Quantity(value, unit)

    if display_unit is not None:
        quantity = quantity.to(display_unit)

    return f"{quantity:{_QUANTITY_FORMAT}}"


def capture_metadata(
    entry, camera_settings, *, stamp, step_desc=None, dotted_id=None
) -> dict:
    """The capture settings embedded in both of an entry's PNGs: the step
    context, the LED request, and ``camera_settings`` — the exposure/gain
    and readout format the saved frame was exposed with (paired with it by
    `AsiCameraFeed.latest_capture`). With an auto mode on they differ from
    the entry's requested starting values, which ride along too.
    ``stamp`` is the UTC stamp of the capture's filenames. The fields'
    meanings close it (CAPTURE_FIELD_DESCRIPTIONS), for the image viewer's
    tooltips.

    Dimensioned values are pint quantity strings carrying their unit, one
    unit per kind — times in ms, frequency in Hz, LED duty in %,
    temperature in °C — so they display as stored and parse back with
    ``unit_registry.Quantity(text)``."""
    temperature = asi_camera_settings.camera_temperature

    if entry.multi_channel:
        leds = dict(
            led_intensities={
                index: _quantity_text(duty, "percent")
                for index, duty in entry.led_intensities().items()
            }
        )
    else:
        leds = dict(led_index=entry.led_index)

    # Key order is display order — the image viewer lists the fields as
    # stored — so related settings sit together: the capture, its step,
    # the light, the exposure, the gain, then the sensor readout.
    return dict(
        version=CAPTURE_METADATA_VERSION,
        timestamp_utc=stamp,
        label=entry.label,
        image_tag=entry.image_tag,
        step_description=step_desc,
        step_dotted_id=dotted_id,
        wavelength=entry.wavelength,
        **leds,
        intensity=_quantity_text(entry.intensity, "percent"),
        frequency=_quantity_text(entry.frequency, "Hz"),
        exposure=_quantity_text(
            camera_settings["exposure_us"], "us", display_unit="ms"
        ),
        requested_exposure=_quantity_text(entry.exposure_ms, "ms"),
        auto_exposure=entry.auto_exposure,
        camera_lead_time=_quantity_text(entry.camera_lead_time_ms, "ms"),
        gain=camera_settings["gain"],
        requested_gain=entry.gain,
        auto_gain=entry.auto_gain,
        binning=camera_settings["binning"],
        image_type=camera_settings["image_type"],
        # NaN until the camera reports a reading, and JSON has no NaN.
        sensor_temperature=(
            None if math.isnan(temperature) else _quantity_text(temperature, "degC")
        ),
        field_descriptions=CAPTURE_FIELD_DESCRIPTIONS,
    )


def save_entry_capture(entry, folder: Path, *, step_desc=None, dotted_id=None) -> Path:
    """Wait for a fresh frame from the active feed and save it: the raw
    16-bit sensor frame (lossless) under `16bit_raw/`, plus an 8-bit
    display conversion next to it — the SAME conversion chain
    `AsiCameraFeed._on_preview_ready` uses for previews (`to_display_8bit`
    -> `debayered_to_rgb` -> the QImage constructor helper), minus the
    preview-only gamma/contrast/brightness adjustment and timestamp stamp,
    which never touch saved captures either. Both PNGs carry
    `capture_metadata` as JSON text under CAPTURE_METADATA_KEY, with the
    camera settings taken atomically with the frame (the step context is
    None in free mode). Returns the display path."""
    feed = current_feed()

    if feed is None:
        raise RuntimeError("no active camera feed")

    seq = feed.frame_seq
    timeout = entry.exposure_ms / 1000.0 * 2 + 2.0

    if not feed.wait_for_frame_after(seq, timeout):
        raise TimeoutError(f"No new frame for {entry.label!r} within {timeout}s")

    raw, camera_settings = feed.latest_capture()
    stamp = utc_stamp()
    metadata = json.dumps(
        capture_metadata(
            entry,
            camera_settings,
            stamp=stamp,
            step_desc=step_desc,
            dotted_id=dotted_id,
        )
    )

    # Per-capture timestamp in every filename — the regular capture
    # pipeline's naming convention, so a file is traceable to its moment
    # even outside its burst folder.
    label = f"{sanitize_label(entry.label)}_{stamp}"

    raw_path = folder / RAW_CAPTURES_SUBDIR / f"{label}_raw.png"
    raw_image = raw_to_qimage(raw)
    raw_image.setText(CAPTURE_METADATA_KEY, metadata)
    save_png_atomically(raw_image, raw_path)

    display_path = folder / f"{label}.png"
    display_image = frame_to_qimage(debayered_to_rgb(to_display_8bit(raw)))
    display_image.setText(CAPTURE_METADATA_KEY, metadata)
    save_png_atomically(display_image, display_path)

    return display_path


def save_png_atomically(image, path: Path) -> None:
    """Encode ``image`` as a lossless PNG under a partial name beside
    ``path``, then rename it into place: the image viewer's discovery poll
    only ever sees complete files (it never retries a file that failed to
    decode)."""
    partial_path = path.with_name(f"{path.name}{CAPTURE_PARTIAL_SUFFIX}")

    if not image.save(str(partial_path), "PNG", CAPTURE_PNG_QUALITY):
        partial_path.unlink(missing_ok=True)
        raise OSError(f"Could not write capture {path}")

    os.replace(partial_path, path)


def run_burst(
    entries, *, step_desc=None, dotted_id=None, applied_timeout: float = 5.0
) -> Path:
    """Fire the chain's ticked entries in order: apply camera settings,
    publish the LED state, wait for the backend's applied ack, wait out the
    entry's camera lead time, capture. Runs on the pane's burst worker
    thread, so the lead-time sleep never blocks the GUI. ALL_LEDS_OFF
    always fires on the way out — even on error/timeout — so a failed
    burst can never leave a light on."""
    folder = burst_folder(step_desc, dotted_id)

    try:
        for entry in ticked(entries):
            apply_camera_settings(entry)
            arm_applied()
            protocol_set_fluorescence_publisher.publish(
                light_on=True,
                frequency=entry.frequency,
                settle_s=LED_STABILIZATION_S,
                **entry.led_request(),
            )

            if not wait_applied(applied_timeout):
                raise TimeoutError(f"LED apply not acknowledged for {entry.label!r}")

            if entry.camera_lead_time_ms:
                time.sleep(entry.camera_lead_time_ms / 1000.0)

            save_entry_capture(entry, folder, step_desc=step_desc, dotted_id=dotted_id)
    finally:
        publish_message(topic=ALL_LEDS_OFF, message="")

    return folder
