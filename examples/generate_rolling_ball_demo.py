"""Generate a synthetic experiment for testing the rolling-ball
background correction against known ground truth.

Creates ``<output>/rolling_ball_demo/`` holding 12 16-bit frames (10 s
apart) on a badly uneven background — the kind of vignetting and
stray-light gradient the rolling ball exists to remove:

    background = 500 + a gradient across x
                     + two broad swells that BRIGHTEN over time

so the background spans roughly 500-2600 counts and drifts upward as
the series runs. Nothing about it is flat, and no single number can
correct it.

Six disks sit on it:

- ``level_dim``, ``level_mid``, ``level_bright``, ``level_corner``:
  four disks carrying the SAME constant signal (1000 counts) but
  parked where the background differs by well over a thousand counts.
  Raw, their means disagree wildly and drift with the swells. With the
  ball on, all four must read the same 1000 and stay flat. The script
  fails loudly if they do not — that agreement IS the test.
- ``rising``: a sigmoid, to confirm a real curve survives flattening.
- ``big_blob``: a disk of radius 45, larger than the DEFAULT ball
  would comfortably clear. It is there to show the failure mode: set
  the ball radius near or below the feature size and the ball rolls
  over the signal and subtracts it away. Compare it at r=60 and r=20.

The experiment is written with the ball ON at radius 60 and its stats
already computed through the app's own functions, so browsing to the
folder shows corrected, flat curves immediately. Switch the Rolling
ball toggle off in the plot controls (or change Ball r) to watch the
uneven background come back — the statistics recompute either way,
since the ball is part of the cache key.

Run:
    pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && \\
        python examples/generate_rolling_ball_demo.py [output_dir]"

Then in MicroDrop: Image Viewer pane -> folder button ->
select ``<output>/rolling_ball_demo/captures``.
"""
import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, Roi,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    save_roi_stats, save_session,
)
from device_viewer.consts import RAW_CAPTURES_SUBDIR

from fluorescence_controls_ui.image_viewer.discovery import (
    discover_captures,
)

FRAME_COUNT = 12
FRAME_INTERVAL_S = 10.0
IMAGE_SHAPE = (512, 640)          # (height, width)

#: The uneven background: a floor, a gradient across x, and two broad
#: swells that grow as the series runs. Their width is what makes this
#: a rolling-ball problem — far wider than any droplet, so a ball of
#: the right size rolls under them and traces them out.
BACKGROUND_FLOOR = 500.0
GRADIENT_PER_PX = 1.1
#: Broad on purpose. The ball leaves a residue where the background
#: curves sharply relative to its own radius — measured here, a swell
#: of sigma 150 leaves ~130 counts under a 60px ball, one of sigma 320
#: leaves ~67 — and real illumination unevenness (vignetting, a lamp
#: hot-spot) is broad across the frame rather than sharp.
SWELLS = (((180, 150), 300.0, 900.0),     # (centre xy, sigma, peak)
          ((470, 380), 260.0, 1100.0))
#: How much the swells brighten by the last frame (1.0 = not at all).
SWELL_GROWTH = 1.6
NOISE_SIGMA = 12.0

#: The ball this demo is written with. Comfortably larger than the
#: level disks (r=22) and than the droplets a real experiment measures.
DEMO_BALL_RADIUS = 60

#: Signal carried by the four level disks, and how closely their
#: corrected means must agree for the demo to be considered working.
LEVEL_SIGNAL = 1000.0
LEVEL_TOLERANCE = 60.0

#: (name, (cx, cy, r), signal_of_t, what it is for)
DEMO_ROIS = (
    ("level_dim", (60.0, 460.0, 22.0), lambda t: LEVEL_SIGNAL,
     "same signal, darkest background"),
    ("level_mid", (180.0, 150.0, 22.0), lambda t: LEVEL_SIGNAL,
     "same signal, on the first swell"),
    ("level_bright", (470.0, 380.0, 22.0), lambda t: LEVEL_SIGNAL,
     "same signal, on the brightest swell"),
    ("level_corner", (600.0, 60.0, 22.0), lambda t: LEVEL_SIGNAL,
     "same signal, far end of the gradient"),
    ("rising", (330.0, 120.0, 22.0),
     lambda t: 2000.0 / (1.0 + math.exp(-0.06 * (t - 60.0))) + 300.0,
     "a sigmoid, to show curves survive flattening"),
    ("big_blob", (330.0, 400.0, 45.0), lambda t: LEVEL_SIGNAL,
     "wider than a small ball: shows the over-rolling failure"),
)

LEVEL_NAMES = tuple(name for name, _g, _s, _w in DEMO_ROIS
                    if name.startswith("level_"))


def _background(frame_index):
    """The background of one frame: floor + gradient + swells, the
    swells brightening as the series runs."""
    height, width = IMAGE_SHAPE
    y, x = np.mgrid[0:height, 0:width].astype(float)
    growth = 1.0 + (SWELL_GROWTH - 1.0) * (frame_index
                                           / max(FRAME_COUNT - 1, 1))
    background = BACKGROUND_FLOOR + GRADIENT_PER_PX * x
    for (cx, cy), sigma, peak in SWELLS:
        background += peak * growth * np.exp(
            -(((x - cx) ** 2 + (y - cy) ** 2) / (2.0 * sigma ** 2)))
    return background


def _frame(frame_index, rng):
    """One 16-bit frame: background + the disks' signals + noise."""
    elapsed = frame_index * FRAME_INTERVAL_S
    height, width = IMAGE_SHAPE
    y, x = np.mgrid[0:height, 0:width].astype(float)
    frame = _background(frame_index)
    for _name, (cx, cy, radius), signal_of_t, _what in DEMO_ROIS:
        inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2
        frame = frame + inside * signal_of_t(elapsed)
    frame = frame + rng.normal(0.0, NOISE_SIGMA, IMAGE_SHAPE)
    return np.clip(frame, 0, 65535).astype(np.uint16)


def _write_frames(captures_dir, start_time):
    """The frames, in the layout the viewer discovers: raws live in
    captures/16bit_raw/, which is the folder name it filters on."""
    raw_dir = captures_dir / RAW_CAPTURES_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260806)
    paths = []
    for index in range(FRAME_COUNT):
        stamp = time.strftime(
            "%Y_%m_%d-%H_%M_%S",
            time.localtime(start_time + index * FRAME_INTERVAL_S))
        path = raw_dir / f"green_540nm_{stamp}_raw.png"
        cv2.imwrite(str(path), _frame(index, rng))
        paths.append(path)
    return paths


def _session(experiment_dir):
    session = AnalysisSession(directory=str(experiment_dir))
    session.rois = [
        Roi(name=name, kind="ellipse",
            geometry=[cx, cy, radius, radius, 0.0])
        for name, (cx, cy, radius), _signal, _what in DEMO_ROIS]
    session.plot_stat = "mean"
    session.ball.enabled = True
    session.ball.radius_px = DEMO_BALL_RADIUS
    session.figure.show_legend = True
    return session


def _stats(session, paths, ball_radius):
    """Every frame's stats at one ball radius, keyed the way the app
    keys them — so the app finds them and computes nothing."""
    store = {}
    for path in paths:
        effective = {roi.roi_id: (roi.kind, tuple(roi.geometry))
                     for roi in session.rois}
        result = compute_image_stats(
            str(path), effective, session.ring.gap_px,
            session.ring.thickness_px, ball_radius)
        for roi_id, stats in result["stats"].items():
            roi = session.roi_by_id(roi_id)
            store[session.cache_key(str(path), roi)] = stats
    return store


def _report(session, paths):
    """Print what each ROI reads raw and corrected, and check the four
    level disks agree once the background is gone."""
    raw = _stats_by_name(session, paths, 0)
    corrected = _stats_by_name(session, paths, DEMO_BALL_RADIUS)
    print(f"\n{'ROI':14s} {'raw first':>10s} {'raw last':>10s} "
          f"{'ball first':>11s} {'ball last':>10s}   what it shows")
    for name, _geometry, _signal, what in DEMO_ROIS:
        print(f"{name:14s} {raw[name][0]:10.0f} {raw[name][-1]:10.0f} "
              f"{corrected[name][0]:11.0f} {corrected[name][-1]:10.0f}"
              f"   {what}")

    spread_raw = max(raw[name][0] for name in LEVEL_NAMES) - min(
        raw[name][0] for name in LEVEL_NAMES)
    means = [value for name in LEVEL_NAMES for value in corrected[name]]
    spread = max(means) - min(means)
    error = max(abs(value - LEVEL_SIGNAL) for value in means)
    print(f"\nfour disks, same {LEVEL_SIGNAL:.0f}-count signal:")
    print(f"  raw, they span      {spread_raw:8.0f} counts "
          f"(the background talking)")
    print(f"  ball-corrected      {spread:8.0f} counts spread, "
          f"worst error {error:.0f} from the true {LEVEL_SIGNAL:.0f}")
    if spread > LEVEL_TOLERANCE or error > LEVEL_TOLERANCE:
        print(f"  FAILED: expected agreement within "
              f"{LEVEL_TOLERANCE:.0f} counts")
        return False
    print(f"  OK: within {LEVEL_TOLERANCE:.0f} counts of each other "
          f"and of the truth")

    print("  (the ball leaves a residue where the background "
          "curves sharply relative to its radius;")
    print("   these swells are broad, so it is small)")

    small = _stats_by_name(session, paths, 20)
    print(f"\nover-rolling check — big_blob (r=45) measured with a "
          f"ball of:")
    print(f"  r={DEMO_BALL_RADIUS} (clears it) {corrected['big_blob'][0]:8.0f}"
          f"   r=20 (rolls over it) {small['big_blob'][0]:8.0f}")
    return True


def _stats_by_name(session, paths, ball_radius):
    by_name = {}
    for path in paths:
        effective = {roi.roi_id: (roi.kind, tuple(roi.geometry))
                     for roi in session.rois}
        result = compute_image_stats(
            str(path), effective, session.ring.gap_px,
            session.ring.thickness_px, ball_radius)
        for roi in session.rois:
            by_name.setdefault(roi.name, []).append(
                result["stats"][roi.roi_id]["mean"])
    return by_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default=".",
                        help="where to create rolling_ball_demo/")
    arguments = parser.parse_args()
    experiment_dir = Path(arguments.output).resolve() / \
        "rolling_ball_demo"
    captures_dir = experiment_dir / "captures"
    paths = _write_frames(captures_dir,
                          time.time() - FRAME_COUNT * FRAME_INTERVAL_S)
    print(f"wrote {len(paths)} frames of "
          f"{IMAGE_SHAPE[1]}x{IMAGE_SHAPE[0]} uint16 to {captures_dir}")
    session = _session(experiment_dir)
    discovered = [str(path) for path in discover_captures(captures_dir)]
    save_session(experiment_dir, session)
    save_roi_stats(experiment_dir,
                   _stats(session, discovered, DEMO_BALL_RADIUS))
    print(f"session written with the ball ON at r="
          f"{DEMO_BALL_RADIUS}px")
    if not _report(session, discovered):
        return 1
    print(f"\nbrowse to: {captures_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
