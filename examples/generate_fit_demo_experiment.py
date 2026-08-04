"""Generate a synthetic experiment for eyeballing the ROI curve-fitting
features against known ground truth.

Creates ``<output>/fit_demo_experiment/`` holding 20 16-bit frames
(10 s apart) whose five uniform disks follow known curves:

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

Then in MicroDrop: Fluorescence Images pane -> folder button ->
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
    fastest_change_time, fit_series, second_derivative_extrema,
    trimmed_note,
)
from fluorescence_controls_ui.image_viewer.analysis.plot_series import (
    derive_series,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_compute import (
    compute_image_stats,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, Roi,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_store import (
    load_roi_stats, load_session, save_roi_stats, save_session,
)
from fluorescence_controls_ui.image_viewer.discovery import (
    discover_captures,
)

FRAME_COUNT = 20
FRAME_INTERVAL_S = 10.0
IMAGE_SHAPE = (240, 320)          # (height, width)
BACKGROUND_LEVEL = 100

#: (name, circle geometry (cx, cy, r), mean_of_t callable, truth text).
DEMO_ROIS = (
    ("decay", (60.0, 60.0, 30.0),
     lambda t: 3000.0 * math.exp(-0.05 * t) + 500.0,
     "y = 3000·e^(-0.05·t) + 500"),
    ("cubic", (160.0, 60.0, 30.0),
     lambda t: 0.001 * t ** 3 - 0.25 * t ** 2 + 15.0 * t + 800.0,
     "y = 0.001·t^3 - 0.25·t^2 + 15·t + 800"),
    ("linear", (260.0, 60.0, 30.0),
     lambda t: 5.0 * t + 600.0,
     "y = 5·t + 600"),
    ("sigmoid", (60.0, 170.0, 30.0),
     lambda t: 3000.0 / (1.0 + math.exp(-0.08 * (t - 95.0))) + 500.0,
     "y = 3000/(1+e^(-0.08·(t-95))) + 500"),
    ("bleached", (160.0, 170.0, 30.0),
     lambda t: (3000.0 / (1.0 + math.exp(-0.08 * (t - 95.0))) + 500.0)
     * math.exp(-0.015 * max(t - 120.0, 0.0)),
     "the same sigmoid, bleaching at 1.5%/s past t=120"),
)


def write_frames(raw_dir):
    """The 16-bit frames, one per time step, with each disk filled at
    its curve's value; mtimes ascend so discovery order is stable."""
    base_epoch = time.time() - FRAME_COUNT * FRAME_INTERVAL_S
    paths = []
    for index in range(FRAME_COUNT):
        elapsed = index * FRAME_INTERVAL_S
        frame = np.full(IMAGE_SHAPE, BACKGROUND_LEVEL, dtype=np.uint16)
        for _, (center_x, center_y, radius), mean_of_t, _ in DEMO_ROIS:
            cv2.circle(frame,
                       (int(center_x), int(center_y)), int(radius),
                       int(round(mean_of_t(elapsed))), -1)
        stamp = time.strftime("%Y_%m_%d-%H_%M_%S",
                              time.gmtime(base_epoch + elapsed))
        path = raw_dir / f"frame{index:02d}_{stamp}_raw.png"
        cv2.imwrite(str(path), frame)
        paths.append(path)
    return paths


def build_session(experiment_dir):
    session = AnalysisSession(directory=str(experiment_dir))
    session.rois = [
        Roi(roi_id=f"demo-{name}", name=name, kind="circle",
            geometry=list(geometry), base_anchor=0.0)
        for name, geometry, _, _ in DEMO_ROIS]
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
        effective = {roi.roi_id: (roi.kind, tuple(roi.geometry))
                     for roi in session.rois}
        result = compute_image_stats(path, effective)
        if result["error"] is not None:
            sys.exit(f"stats failed for {path}: {result['error']}")
        for roi in session.rois:
            store[session.cache_key(path, roi, stat_cache)] = \
                result["stats"][roi.roi_id]
    return store


def verify_and_report(experiment_dir):
    """Reload everything through the app's own loaders and print the
    fitted equations the GUI must reproduce."""
    session = load_session(experiment_dir)
    session.stats = load_roi_stats(experiment_dir)
    paths = [str(path) for path in
             discover_captures(experiment_dir / "captures")]
    series = derive_series(session, paths)
    if len(series) != len(DEMO_ROIS):
        sys.exit(f"expected {len(DEMO_ROIS)} series, got {len(series)}")
    print(f"\nDemo experiment: {experiment_dir}")
    print(f"Browse to: {experiment_dir / 'captures'}\n")
    print("Expected results (sigmoid fit and 'Trim poor tail' are "
          "preselected; switch the Fit dropdown to try the others, and "
          "the View dropdown for the d² and fastest-change charts):")
    for (name, _, _, truth), (roi_id, (_, elapsed, values)) in zip(
            DEMO_ROIS, series.items()):
        gap_count = sum(1 for value in values if math.isnan(value))
        if gap_count:
            sys.exit(f"{name}: {gap_count} NaN points — cache keys "
                     f"did not match, the plot would show gaps")
        print(f"\n  {name}  (truth: {truth})")
        for method in ("linear", "poly2", "poly3", "exponential",
                       "sigmoid"):
            fit = fit_series(elapsed, values, method,
                             session.figure.trim_poor_fit)
            if fit is None:
                print(f"    {method:12s}: fit failed")
                continue
            line = f"    {method:12s}: {fit.equation}" \
                   f"{trimmed_note(fit, max(elapsed))}  " \
                   f"R²={fit.r_squared:.4f}"
            extrema = second_derivative_extrema(
                fit, min(elapsed), max(elapsed))
            if extrema:
                t_max, y_max = extrema["max"]
                t_min, y_min = extrema["min"]
                line += (f"  d²max@({t_max:.3g}, {y_max:.3g})"
                         f"  d²min@({t_min:.3g}, {y_min:.3g})")
            else:
                line += "  (flat d² -> no markers)"
            t_fastest = fastest_change_time(
                fit, min(elapsed), max(elapsed))
            line += (f"  fastest@{t_fastest:.3g}s"
                     if t_fastest is not None
                     else "  (constant rate -> no bar)")
            print(line)


def main():
    # The report is full of ·, ², ≤; a cp1252 console would die on it.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Generate the curve-fitting demo experiment.")
    parser.add_argument(
        "output_dir", nargs="?",
        default=str(Path.home() / "Documents"),
        help="Folder to create fit_demo_experiment/ in "
             "(default: your Documents folder)")
    arguments = parser.parse_args()
    experiment_dir = (Path(arguments.output_dir).resolve()
                      / "fit_demo_experiment")
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
