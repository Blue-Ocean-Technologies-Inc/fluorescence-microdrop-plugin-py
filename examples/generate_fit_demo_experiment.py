"""Generate a synthetic experiment for eyeballing the ROI curve-fitting
features against known ground truth.

Creates ``<output>/fit_demo_experiment/`` holding 20 16-bit frames
(10 s apart), built as background + signal + Gaussian noise. Every
curve below is the signal ABOVE a background of 100, so the mean reads
100 higher and ``bg_corrected`` recovers the stated equation — which is
why the demo session plots the corrected series.

Seven disks: five following known curves, and a pair that checks the
background correction itself.

- ``decay``  : mean = 3000·e^(-0.05·t) + 500   (exponential; d² max at
  t=0, min at the end — both markers should appear at the span edges)
- ``cubic``  : mean = 0.001·t³ - 0.25·t² + 15·t + 800  (d² is linear:
  max at the far edge, min at t=0)
- ``linear`` : mean = 5·t + 600   (flat d² — NO extremum markers may
  appear; their absence is the correct behavior)
- ``sigmoid``: mean = 3000/(1+e^(-0.08·(t-95))) + 500  (fluorescence
  onset; fastest change / inflection at t=95, interior d² max/min at
  ~78.5 / ~111.5 s — markers land mid-plot, and the fastest-change
  view's bar should read 95)
- ``plain`` and ``on_glow``: two disks carrying the same constant
  signal, but ``on_glow`` sits in a patch of background raised by 300.
  Their means differ by that 300; their corrected values must agree,
  and the generator fails loudly if they do not
- ``bleached``: that same sigmoid times e^(-0.015·(t-120)) past t=120
  (photobleached plateau). It exists to exercise "Trim poor tail":
  with the box off the fit lands ~12 s early on an R² of ~0.75, with
  it on the fit retreats to the leading points, R² clears 0.99, the
  bar returns to ~95, and the dropped tail is shaded

The ROIs, computed stats and figure settings (sigmoid fit, corner
equations, d² max+min with v-line and coords) are pre-written through
the app's own persistence/compute functions, so browsing to the folder
shows the fitted plot immediately — no Calculate needed. The script
prints the expected fitted equations; compare them against the
equations popup (ƒ button) and the on-figure corner box.

Run:
    pixi run bash -c "cd src/fluorescence-microdrop-plugin-py && \\
        python examples/generate_fit_demo_experiment.py [output_dir]"

Then in MicroDrop: Image Viewer pane -> folder button ->
select ``<output>/fit_demo_experiment/captures``.
"""

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from fluorescence_controls_ui.image_viewer.analysis.curve_fit import (
    fastest_change_time,
    fit_series,
    second_derivative_extrema,
    trimmed_note,
)
from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    derive_series,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession,
    Roi,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_stats,
    load_session,
    save_roi_stats,
    save_session,
)
from fluorescence_controls_ui.image_viewer.discovery import (
    discover_captures,
)

FRAME_COUNT = 20
FRAME_INTERVAL_S = 10.0
IMAGE_SHAPE = (400, 420)  # (height, width)

#: The frames are built as background + signal + noise, so every curve
#: below is the signal ABOVE background: the mean reads BACKGROUND_LEVEL
#: higher, and bg_corrected recovers the stated equation.
BACKGROUND_LEVEL = 100
NOISE_SIGMA = 15.0

#: A patch of raised background under one of the paired disks, to prove
#: the correction removes it: 300 counts over an area comfortably wider
#: than that ROI's ring.
GLOW_CENTRE = (180, 320)
GLOW_RADIUS = 65
GLOW_LEVEL = 300

#: The paired disks carry the same signal on different backgrounds, so
#: their corrected values must agree.
PAIR_SIGNAL = 1200.0
PAIR_TOLERANCE = 5.0

#: (name, circle geometry (cx, cy, r), mean_of_t callable, truth text).
DEMO_ROIS = (
    (
        "decay",
        (60.0, 60.0, 30.0),
        lambda t: 3000.0 * math.exp(-0.05 * t) + 500.0,
        "y = 3000·e^(-0.05·t) + 500",
    ),
    (
        "cubic",
        (160.0, 60.0, 30.0),
        lambda t: 0.001 * t**3 - 0.25 * t**2 + 15.0 * t + 800.0,
        "y = 0.001·t^3 - 0.25·t^2 + 15·t + 800",
    ),
    ("linear", (260.0, 60.0, 30.0), lambda t: 5.0 * t + 600.0, "y = 5·t + 600"),
    (
        "sigmoid",
        (60.0, 170.0, 30.0),
        lambda t: 3000.0 / (1.0 + math.exp(-0.08 * (t - 95.0))) + 500.0,
        "y = 3000/(1+e^(-0.08·(t-95))) + 500",
    ),
    (
        "bleached",
        (160.0, 170.0, 30.0),
        lambda t: (
            (3000.0 / (1.0 + math.exp(-0.08 * (t - 95.0))) + 500.0)
            * math.exp(-0.015 * max(t - 120.0, 0.0))
        ),
        "the same sigmoid, bleaching at 1.5%/s past t=120",
    ),
    (
        "plain",
        (60.0, 320.0, 30.0),
        lambda t: PAIR_SIGNAL,
        f"constant {PAIR_SIGNAL:.0f} on plain background",
    ),
    (
        "on_glow",
        (180.0, 320.0, 30.0),
        lambda t: PAIR_SIGNAL,
        f"constant {PAIR_SIGNAL:.0f} on background raised by {GLOW_LEVEL}",
    ),
)

#: The two ROIs whose corrected values must match: same signal, one of
#: them sitting in the glow.
PAIR_NAMES = ("plain", "on_glow")


def _background_map():
    """The background each pixel sits on: flat, plus the glow patch
    under one of the paired disks. Signal is added on top of this, so
    a background correction has something real to remove."""
    background = np.full(IMAGE_SHAPE, float(BACKGROUND_LEVEL))
    cv2.circle(
        background, GLOW_CENTRE, GLOW_RADIUS, float(BACKGROUND_LEVEL + GLOW_LEVEL), -1
    )
    return background


def write_frames(raw_dir):
    """The 16-bit frames, one per time step: background + each disk's
    signal + Gaussian noise. mtimes ascend so discovery order is
    stable, and the noise is seeded per frame so a regenerated demo
    reproduces exactly."""
    base_epoch = time.time() - FRAME_COUNT * FRAME_INTERVAL_S
    background = _background_map()
    paths = []
    for index in range(FRAME_COUNT):
        elapsed = index * FRAME_INTERVAL_S
        signal = np.zeros(IMAGE_SHAPE, dtype=float)
        for _, (center_x, center_y, radius), mean_of_t, _ in DEMO_ROIS:
            cv2.circle(
                signal,
                (int(center_x), int(center_y)),
                int(radius),
                float(mean_of_t(elapsed)),
                -1,
            )
        noise = np.random.default_rng(index).normal(0.0, NOISE_SIGMA, IMAGE_SHAPE)
        frame = np.clip(background + signal + noise, 0, 65535)
        stamp = time.strftime("%Y_%m_%d-%H_%M_%S", time.gmtime(base_epoch + elapsed))
        path = raw_dir / f"frame{index:02d}_{stamp}_raw.png"
        cv2.imwrite(str(path), frame.astype(np.uint16))
        paths.append(path)
    return paths


def build_session(experiment_dir):
    session = AnalysisSession(directory=str(experiment_dir))
    session.rois = [
        # DEMO_ROIS keeps the (cx, cy, r) tuples cv2.circle draws the
        # frames from; the ROI itself takes canonical ellipse geometry.
        Roi(
            roi_id=f"demo-{name}",
            name=name,
            kind="ellipse",
            geometry=[geometry[0], geometry[1], geometry[2], geometry[2], 0.0],
            base_anchor=0.0,
        )
        for name, geometry, _, _ in DEMO_ROIS
    ]
    # The curves above are signal over background, so the corrected
    # series is the one that reproduces them; plain "mean" reads
    # BACKGROUND_LEVEL higher (and 300 higher again inside the glow).
    session.plot_stat = "bg_corrected"
    figure_settings = session.figure
    figure_settings.fit_method = "sigmoid"
    figure_settings.trim_poor_fit = True
    figure_settings.show_fit_equations = True
    figure_settings.show_second_derivative_max = True
    figure_settings.show_second_derivative_min = True
    # defaults already: v-line + coords on, h-line off, legend on
    return session


def compute_store(session, paths):
    """The stats store exactly as the app's batch would build it, via
    the same worker function and cache keys."""
    store, stat_cache = {}, {}
    for path in paths:
        effective = {
            roi.roi_id: (roi.kind, tuple(roi.geometry)) for roi in session.rois
        }
        result = compute_image_stats(path, effective)
        if result["error"] is not None:
            sys.exit(f"stats failed for {path}: {result['error']}")
        for roi in session.rois:
            store[session.cache_key(path, roi, stat_cache)] = result["stats"][
                roi.roi_id
            ]
    return store


def _report_pair(session, series):
    """The background-correction check: two disks carrying the same
    signal, one of them in the glow, must correct to the same value."""
    by_name = {
        name: (roi_id, values) for roi_id, (name, _elapsed, values) in series.items()
    }
    print()
    print("Background-correction check (same signal, different backgrounds):")
    corrected = {}
    for name in PAIR_NAMES:
        roi_id, values = by_name[name]
        raw = [
            session.stats[key].get("mean") for key in session.stats if key[2] == roi_id
        ]
        corrected[name] = values[0]
        print(f"  {name:8s} bg_corrected={values[0]:8.1f}  (raw mean {max(raw):8.1f})")
    difference = abs(corrected[PAIR_NAMES[0]] - corrected[PAIR_NAMES[1]])
    print(
        f"  difference {difference:.1f} counts "
        f"(signal is {PAIR_SIGNAL:.0f}, tolerance {PAIR_TOLERANCE:.0f})"
    )
    if difference > PAIR_TOLERANCE:
        sys.exit(
            f"background correction is off by {difference:.1f} "
            f"counts between {PAIR_NAMES[0]} and {PAIR_NAMES[1]}"
        )


def verify_and_report(experiment_dir):
    """Reload everything through the app's own loaders and print the
    fitted equations the GUI must reproduce."""
    session = load_session(experiment_dir)
    session.stats = load_roi_stats(experiment_dir)
    paths = [str(path) for path in discover_captures(experiment_dir / "captures")]
    series = derive_series(session, paths)
    if len(series) != len(DEMO_ROIS):
        sys.exit(f"expected {len(DEMO_ROIS)} series, got {len(series)}")
    print(f"\nDemo experiment: {experiment_dir}")
    print(f"Browse to: {experiment_dir / 'captures'}\n")
    _report_pair(session, series)
    print(
        "Expected results (sigmoid fit and 'Trim poor tail' are "
        "preselected; switch the Fit dropdown to try the others, and "
        "the View dropdown for the d² and fastest-change charts):"
    )
    for (name, _, _, truth), (roi_id, (_, elapsed, values)) in zip(
        DEMO_ROIS, series.items()
    ):
        gap_count = sum(1 for value in values if math.isnan(value))
        if gap_count:
            sys.exit(
                f"{name}: {gap_count} NaN points — cache keys "
                f"did not match, the plot would show gaps"
            )
        print(f"\n  {name}  (truth: {truth})")
        for method in ("linear", "poly2", "poly3", "exponential", "sigmoid"):
            fit = fit_series(elapsed, values, method, session.figure.trim_poor_fit)
            if fit is None:
                print(f"    {method:12s}: fit failed")
                continue
            line = (
                f"    {method:12s}: {fit.equation}"
                f"{trimmed_note(fit, max(elapsed))}  "
                f"R²={fit.r_squared:.4f}"
            )
            extrema = second_derivative_extrema(fit, min(elapsed), max(elapsed))
            if extrema:
                t_max, y_max = extrema["max"]
                t_min, y_min = extrema["min"]
                line += (
                    f"  d²max@({t_max:.3g}, {y_max:.3g})"
                    f"  d²min@({t_min:.3g}, {y_min:.3g})"
                )
            else:
                line += "  (flat d² -> no markers)"
            t_fastest = fastest_change_time(fit, min(elapsed), max(elapsed))
            line += (
                f"  fastest@{t_fastest:.3g}s"
                if t_fastest is not None
                else "  (constant rate -> no bar)"
            )
            print(line)


def main():
    # The report is full of ·, ², ≤; a cp1252 console would die on it.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Generate the curve-fitting demo experiment."
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=str(Path.home() / "Documents"),
        help="Folder to create fit_demo_experiment/ in "
        "(default: your Documents folder)",
    )
    arguments = parser.parse_args()
    experiment_dir = Path(arguments.output_dir).resolve() / "fit_demo_experiment"
    raw_dir = experiment_dir / "captures" / "16bit_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale in raw_dir.glob("*.png"):
        stale.unlink()

    paths = write_frames(raw_dir)
    session = build_session(experiment_dir)
    save_session(experiment_dir, session)
    save_roi_stats(experiment_dir, compute_store(session, paths))
    verify_and_report(experiment_dir)


if __name__ == "__main__":
    main()
