"""Generate a synthetic experiment for testing the AI drift tracker
against droplets that MOVE and CHANGE SHAPE over the series.

Creates ``<output>/drift_demo/captures/16bit_raw/`` holding 24 16-bit
frames (10 s apart) on a mildly uneven background. Four droplets, each
exercising a different part of the tracker:

- ``drifter``:   a circle of constant size gliding steadily right —
  the plain case: the re-segmented center must follow it.
- ``stretcher``: nearly stationary, but a circle that elongates into a
  rotating ellipse — the polygon/ellipse the tracker writes per frame
  must follow the changing outline, not just the center.
- ``wobbler``:   drifts diagonally while its radius breathes ±25% —
  center AND size change together.
- ``shrinker``:  drifts slowly while shrinking from r=28 to r=12 —
  late frames approach the size-filter floor and the segmenter's
  small-mask limit; a tracker that loses it should keep the previous
  geometry rather than inventing one (frames where the model finds
  nothing keep the last shape by design).

Every droplet is drawn as a filled rotated ellipse ~1400 counts above
background, Gaussian-softened so SAM sees a defined but natural edge.

Run:
    pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && \\
        python examples/generate_drift_demo.py [output_dir]"

Then in MicroDrop: Image Viewer pane -> folder button -> select
``<output>/drift_demo/captures``. Workflow to exercise the tracker:
on the FIRST frame run Detect all (or AI-pick each droplet), Accept,
then press Track drift and step through the frames — the outlines
should follow the motion and shape changes, and dragging any frame's
shape shows the capture-time override the tracker wrote.
"""

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from device_viewer.consts import RAW_CAPTURES_SUBDIR

FRAME_COUNT = 24
FRAME_INTERVAL_S = 10.0
IMAGE_SHAPE = (512, 640)  # (height, width)

BACKGROUND_FLOOR = 600.0
GRADIENT_PER_PX = 0.6  # mild unevenness; not the point here
DROPLET_SIGNAL = 1400.0
EDGE_SOFTEN_SIGMA_PX = 2.0
NOISE_SIGMA = 10.0

#: (name, center_of_t, radii_of_t, angle_of_t) with t = frame index.
#: center in px, radii (rx, ry) in px, angle in degrees.
DEMO_DROPLETS = (
    (
        "drifter",
        lambda t: (90.0 + 16.0 * t, 120.0),
        lambda t: (24.0, 24.0),
        lambda t: 0.0,
    ),
    (
        "stretcher",
        lambda t: (170.0 + 1.5 * t, 360.0),
        lambda t: (22.0 + 0.5 * t, 22.0 - 0.25 * t),
        lambda t: 3.0 * t,
    ),
    (
        "wobbler",
        lambda t: (420.0 + 6.0 * t, 130.0 + 9.0 * t),
        lambda t: (20.0 + 5.0 * math.sin(t / 3.0),) * 2,
        lambda t: 0.0,
    ),
    (
        "shrinker",
        lambda t: (520.0 - 4.0 * t, 400.0),
        lambda t: (28.0 - 0.7 * t, 28.0 - 0.7 * t),
        lambda t: 0.0,
    ),
)


def _frame(frame_index, rng):
    """One 16-bit frame: gradient background + the four droplets."""
    height, width = IMAGE_SHAPE
    y, x = np.mgrid[0:height, 0:width].astype(float)
    frame = BACKGROUND_FLOOR + GRADIENT_PER_PX * x

    droplets = np.zeros(IMAGE_SHAPE, dtype=np.float64)
    for _name, center_of, radii_of, angle_of in DEMO_DROPLETS:
        centre_x, centre_y = center_of(frame_index)
        radius_x, radius_y = radii_of(frame_index)
        if radius_x < 2.0 or radius_y < 2.0:
            continue
        mask = np.zeros(IMAGE_SHAPE, dtype=np.uint8)
        cv2.ellipse(
            mask,
            (int(round(centre_x)), int(round(centre_y))),
            (int(round(radius_x)), int(round(radius_y))),
            angle_of(frame_index),
            0.0,
            360.0,
            255,
            -1,
        )
        droplets += (mask > 0) * DROPLET_SIGNAL
    # Soften the edges so the segmenter sees a natural boundary rather
    # than a 1-px cliff.
    droplets = cv2.GaussianBlur(droplets, ksize=(0, 0), sigmaX=EDGE_SOFTEN_SIGMA_PX)

    frame = frame + droplets + rng.normal(0.0, NOISE_SIGMA, IMAGE_SHAPE)
    return np.clip(frame, 0, 65535).astype(np.uint16)


def _write_frames(captures_dir, start_time):
    """The frames, in the layout the viewer discovers: raws live in
    captures/16bit_raw/, which is the folder name it filters on."""
    raw_dir = captures_dir / RAW_CAPTURES_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260807)
    paths = []
    for index in range(FRAME_COUNT):
        stamp = time.strftime(
            "%Y_%m_%d-%H_%M_%S", time.localtime(start_time + index * FRAME_INTERVAL_S)
        )
        path = raw_dir / f"green_540nm_{stamp}_raw.png"
        cv2.imwrite(str(path), _frame(index, rng))
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic moving/shape-changing droplet series "
        "for testing the AI drift tracker."
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=".",
        help="Folder the drift_demo experiment is "
        "created in (default: current directory)",
    )
    arguments = parser.parse_args()

    experiment_dir = Path(arguments.output_dir).resolve() / "drift_demo"
    captures_dir = experiment_dir / "captures"
    # Backdate the series so it reads as a finished experiment.
    start_time = time.time() - FRAME_COUNT * FRAME_INTERVAL_S
    paths = _write_frames(captures_dir, start_time)

    print(f"Wrote {len(paths)} frames to {paths[0].parent}")
    print(f"Browse to: {captures_dir}")
    print("Detect all on the first frame, Accept, then Track drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
