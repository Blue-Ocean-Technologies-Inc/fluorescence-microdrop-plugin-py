"""Generate a synthetic experiment for testing outlier removal and
smoothing against known ground truth.

Creates ``<output>/outlier_demo/`` holding 24 16-bit frames (10 s
apart). Every ROI follows the SAME sigmoid — 100 rising to 900 above
background, midpoint at t = 120 s — so any difference between them is
the fault that was planted in it:

- ``clean``          : nothing planted. Must never be flagged; it is
                       the false-positive check.
- ``spike_one``      : frame 8 flashes to 5000. The headline case —
                       one bad frame drags the fit badly, and dropping
                       it recovers the true parameters.
- ``spike_spread``   : frames 3, 12 and 21 flash. Well separated, so
                       all three are found.
- ``spike_cluster``  : frames 10, 11 and 12 flash. Packed inside one
                       window, so the test goes quiet — the documented
                       limit of a windowed test, planted here so it can
                       be seen rather than discovered later.
- ``dropout``        : frame 15 falls to the background (a shutter or
                       illumination glitch). Outliers cut both ways.
- ``noisy``          : heavy per-frame noise and nothing planted. The
                       smoothing case: the curve is unreadable raw and
                       obvious smoothed, and the fit must not change,
                       smoothing being display-only. At 3 MADs a curve
                       this noisy will have the odd point flagged —
                       which is what a 3-sigma threshold means, and a
                       reason to raise it rather than a fault.

The experiment is written with outlier removal ON (3 MADs, window 5)
and a sigmoid fit, so browsing to it shows the recovered curves at
once. Turn Outliers off in the plot controls to watch the spikes drag
the fits back.

Run:
    pixi run --manifest-path ../../pyproject.toml \\
        python examples/generate_outlier_demo.py [output_dir]

Then in MicroDrop: Image Viewer pane -> folder button ->
select ``<output>/outlier_demo/captures``.
"""

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from device_viewer.consts import RAW_CAPTURES_SUBDIR
from fluorescence_controls_ui.image_viewer.analysis.curve_fit import (
    fit_series,
)
from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    analysed_series,
    outlier_mask,
    smoothed_series,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession,
    Roi,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    save_roi_stats,
    save_session,
)
from fluorescence_controls_ui.image_viewer.discovery import (
    discover_captures,
)

FRAME_COUNT = 24
FRAME_INTERVAL_S = 10.0
IMAGE_SHAPE = (420, 640)  # (height, width)

BACKGROUND_LEVEL = 200.0
NOISE_SIGMA = 8.0

#: The curve every ROI follows, as signal above background.
SIGMOID_LOW = 100.0
SIGMOID_HIGH = 900.0
SIGMOID_MIDPOINT_S = 120.0
SIGMOID_RATE = 0.05

#: What a planted spike and a planted dropout read.
SPIKE_LEVEL = 5000.0
DROPOUT_LEVEL = 5.0
#: Extra per-frame noise inside the ``noisy`` ROI.
NOISY_SIGMA = 130.0

#: The settings the demo is written with.
OUTLIER_THRESHOLD = 3.0
OUTLIER_WINDOW = 5

#: (name, (cx, cy, r), planted frame indices, what it is for)
DEMO_ROIS = (
    ("clean", (90.0, 110.0, 20.0), (), "nothing planted: the false-positive check"),
    ("spike_one", (250.0, 110.0, 20.0), (8,), "one bad frame — the headline case"),
    (
        "spike_spread",
        (410.0, 110.0, 20.0),
        (3, 12, 21),
        "three, well separated: all found",
    ),
    (
        "spike_cluster",
        (570.0, 110.0, 20.0),
        (10, 11, 12),
        "three inside one window: the documented limit",
    ),
    (
        "dropout",
        (170.0, 300.0, 20.0),
        (15,),
        "a frame that fell to background, not rose",
    ),
    ("noisy", (410.0, 300.0, 20.0), (), "no outliers, heavy noise: the smoothing case"),
)

DROPOUT_NAMES = ("dropout",)
NOISY_NAMES = ("noisy",)


def signal_at(elapsed):
    """The curve every ROI follows, above background."""
    return SIGMOID_LOW + (SIGMOID_HIGH - SIGMOID_LOW) / (
        1.0 + math.exp(-SIGMOID_RATE * (elapsed - SIGMOID_MIDPOINT_S))
    )


def _roi_level(name, planted, frame_index, rng):
    """What this ROI's disk reads on this frame, above background."""
    elapsed = frame_index * FRAME_INTERVAL_S
    if frame_index in planted:
        return DROPOUT_LEVEL if name in DROPOUT_NAMES else SPIKE_LEVEL
    level = signal_at(elapsed)
    if name in NOISY_NAMES:
        level += rng.normal(0.0, NOISY_SIGMA)
    return max(level, 0.0)


def _frame(frame_index, rng):
    """One 16-bit frame: a flat background with the ROI disks on it."""
    height, width = IMAGE_SHAPE
    y, x = np.mgrid[0:height, 0:width].astype(float)
    frame = np.full(IMAGE_SHAPE, BACKGROUND_LEVEL)
    for name, (cx, cy, radius), planted, _what in DEMO_ROIS:
        inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius**2
        frame = frame + inside * _roi_level(name, planted, frame_index, rng)
    frame = frame + rng.normal(0.0, NOISE_SIGMA, IMAGE_SHAPE)
    return np.clip(frame, 0, 65535).astype(np.uint16)


def _write_frames(captures_dir, start_time):
    raw_dir = captures_dir / RAW_CAPTURES_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Frame names carry the wall-clock time they were written at, so
    # without this a second run would leave the first run's frames
    # beside it and the series would be two experiments interleaved.
    for existing in raw_dir.glob("*_raw.png"):
        existing.unlink()
    rng = np.random.default_rng(20260806)
    paths = []
    for index in range(FRAME_COUNT):
        stamp = time.strftime(
            "%Y_%m_%d-%H_%M_%S", time.localtime(start_time + index * FRAME_INTERVAL_S)
        )
        path = raw_dir / f"green_540nm_{stamp}_raw.png"
        cv2.imwrite(str(path), _frame(index, rng))
        paths.append(path)
    return paths


def _session(experiment_dir):
    session = AnalysisSession(directory=str(experiment_dir))
    session.rois = [
        Roi(name=name, kind="ellipse", geometry=[cx, cy, radius, radius, 0.0])
        for name, (cx, cy, radius), _planted, _what in DEMO_ROIS
    ]
    session.plot_stat = "mean"
    session.figure.remove_outliers = True
    session.figure.outlier_threshold = OUTLIER_THRESHOLD
    session.figure.outlier_window = OUTLIER_WINDOW
    session.figure.fit_method = "sigmoid"
    session.figure.show_legend = True
    return session


def _stats(session, paths):
    store = {}
    effective = {roi.roi_id: (roi.kind, tuple(roi.geometry)) for roi in session.rois}
    for path in paths:
        result = compute_image_stats(
            str(path), effective, session.ring.gap_px, session.ring.thickness_px
        )
        for roi in session.rois:
            store[session.cache_key(str(path), roi)] = result["stats"][roi.roi_id]
    return store


def _series(session, paths):
    """{name: values} straight from the stats, before any cleaning."""
    from fluorescence_controls_ui.image_viewer.analysis.plot_series import derive_series

    return {
        name: values
        for name, values in (
            (entry[0], entry[2]) for entry in derive_series(session, paths).values()
        )
    }


def _report(session, paths):
    """Which frames were planted, which were found, and what the fits
    make of it with the removal off and on."""
    raw = _series(session, paths)
    print(f"\n{'ROI':15s} {'planted':>16s} {'found':>16s}   what it shows")
    ok = True
    for name, _geometry, planted, what in DEMO_ROIS:
        found = tuple(
            index
            for index, flag in enumerate(
                outlier_mask(raw[name], OUTLIER_THRESHOLD, OUTLIER_WINDOW)
            )
            if flag
        )
        print(f"{name:15s} {str(planted):>16s} {str(found):>16s}   {what}")
        if name == "clean" and found:
            print("  FAILED: the clean ROI must never be flagged")
            ok = False
        if name in ("spike_one", "spike_spread", "dropout") and found != planted:
            print(f"  FAILED: expected {planted}, found {found}")
            ok = False

    print(
        f"\nfits of {'spike_one':15s} (true midpoint "
        f"{SIGMOID_MIDPOINT_S:.0f} s, plateaus "
        f"{BACKGROUND_LEVEL + SIGMOID_LOW:.0f} and "
        f"{BACKGROUND_LEVEL + SIGMOID_HIGH:.0f}):"
    )
    fits = {}
    for remove in (False, True):
        session.figure.remove_outliers = remove
        series, _flags = analysed_series(session, paths, visible_only=False)
        entry = next(value for value in series.values() if value[0] == "spike_one")
        fit = fit_series(entry[1], entry[2], "sigmoid")
        fits[remove] = fit
        print(
            f"  outliers {'on ' if remove else 'off'}: "
            f"R²={fit.r_squared:.4f}  "
            f"midpoint={fit.params['midpoint']:7.1f}  "
            f"initial={fit.params['initial']:7.1f}  "
            f"final={fit.params['final']:7.1f}"
        )
    if abs(fits[True].params["midpoint"] - SIGMOID_MIDPOINT_S) > 5.0:
        print("  FAILED: removal did not recover the midpoint")
        ok = False
    if fits[True].r_squared <= fits[False].r_squared:
        print("  FAILED: removal did not improve the fit")
        ok = False

    # Smoothing must change the picture, and the numbers show why it
    # must not change the fit.
    session.figure.remove_outliers = True
    series, _flags = analysed_series(session, paths, visible_only=False)
    noisy = next(key for key, value in series.items() if value[0] == "noisy")
    smoothed = smoothed_series(series, "savgol", 7, 2)
    raw_fit = fit_series(series[noisy][1], series[noisy][2], "sigmoid")
    smooth_fit = fit_series(smoothed[noisy][1], smoothed[noisy][2], "sigmoid")
    # nan-aware: an outlier dropped from this curve leaves a gap.
    spread_raw = float(np.nanstd(np.diff(series[noisy][2])))
    spread_smooth = float(np.nanstd(np.diff(smoothed[noisy][2])))
    print("")
    print(f"smoothing the {'noisy':15s} curve (Savitzky-Golay 7/2):")
    print(f"  point-to-point scatter {spread_raw:7.1f} -> {spread_smooth:7.1f}")
    print(f"  the app fits the RAW curve: R²={raw_fit.r_squared:.4f}")
    print(
        f"  fitting the smoothed one would read "
        f"R²={smooth_fit.r_squared:.4f} — the same data, flattered by "
        f"a display setting"
    )
    if spread_smooth >= spread_raw:
        print("  FAILED: smoothing did not settle the curve")
        ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", default=".", help="where to create outlier_demo/"
    )
    arguments = parser.parse_args()
    experiment_dir = Path(arguments.output).resolve() / "outlier_demo"
    captures_dir = experiment_dir / "captures"
    paths = _write_frames(captures_dir, time.time() - FRAME_COUNT * FRAME_INTERVAL_S)
    print(
        f"wrote {len(paths)} frames of {IMAGE_SHAPE[1]}x"
        f"{IMAGE_SHAPE[0]} uint16 to {captures_dir}"
    )
    session = _session(experiment_dir)
    discovered = [str(path) for path in discover_captures(captures_dir)]
    # On the session as well as on disk: the report below reads the
    # series through it, exactly as the app does.
    session.stats = _stats(session, discovered)
    save_session(experiment_dir, session)
    save_roi_stats(experiment_dir, session.stats)
    if not _report(session, discovered):
        return 1
    # Written last: the report moves the flag about while it works.
    session.figure.remove_outliers = True
    save_session(experiment_dir, session)
    print(f"\nbrowse to: {captures_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
