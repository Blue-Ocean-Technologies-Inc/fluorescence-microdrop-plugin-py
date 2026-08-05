"""Series derivation for the ROI plot: a pure function of the session
and the viewer's filtered paths, so the plot pane owns its own picture
(observer pattern — nothing pushes series at it). Qt-free."""
import math

from ..scale_bar import pixel_area


def _signal(stats, background):
    """The mean, or the mean less the outline ring when ``background``.
    NaN when either piece is missing."""
    mean = stats.get("mean")
    if mean is None:
        return math.nan
    if not background:
        return mean
    outline = stats.get("outline_mean")
    return math.nan if outline is None else mean - outline


def _count(stats):
    """The interior pixel count, or NaN — which then propagates through
    whatever it is multiplied into."""
    count = stats.get("count")
    return math.nan if count is None else count


def stat_value(stats, stat, pixel_area=1.0):
    """The plotted value for one (image, ROI) stats dict — NaN when the
    stats are missing entirely or lack the pieces a stat needs.
    ``bg_corrected`` is interior mean minus outline-ring mean.
    ``pixel_area`` is one pixel's area in the display unit (1.0 = px²),
    which the size-aware stats scale by."""
    if not stats:
        return math.nan
    if stat == "bg_corrected":
        return _signal(stats, True)
    if stat == "integrated":
        return _signal(stats, False) * _count(stats)
    if stat == "bg_integrated":
        return _signal(stats, True) * _count(stats)
    if stat == "per_area":
        return _signal(stats, False) / pixel_area
    if stat == "bg_per_area":
        return _signal(stats, True) / pixel_area
    if stat == "area":
        return _count(stats) * pixel_area
    value = stats.get(stat)
    return math.nan if value is None else value


def derive_series(session, filtered_paths):
    """{roi_id: (name, [elapsed_sec], [value])} for ``session.plot_stat``
    over the filtered images, elapsed from the first filtered capture.
    NaN where an (image, ROI) pair has no computed stats (line gaps)."""
    paths = list(filtered_paths)
    if not paths or not session.rois:
        return {}
    stat_cache = {}
    # Named to leave the imported pixel_area() function reachable.
    area_per_pixel = pixel_area(session.scale.metres_per_pixel,
                                session.scale.unit)
    times = [session.stat_info(path, stat_cache)[1] for path in paths]
    start_time = times[0]
    series = {}
    for roi in session.rois:
        elapsed, values = [], []
        for path, capture_time in zip(paths, times):
            stats = session.stats.get(
                session.cache_key(path, roi, stat_cache))
            elapsed.append(capture_time - start_time)
            values.append(stat_value(stats, session.plot_stat,
                                     area_per_pixel))
        series[roi.roi_id] = (roi.name, elapsed, values)
    return series


def subtracted_series(series):
    """``series`` with each curve less its own first finite value, so
    every ROI starts at zero and shows change from baseline. NaN stays
    NaN; a curve with no finite value passes through untouched."""
    shifted = {}
    for roi_id, (name, elapsed, values) in series.items():
        first = next((value for value in values if value == value), None)
        shifted[roi_id] = (name, elapsed, values if first is None else [
            value if value != value else value - first
            for value in values])
    return shifted


def normalized_series(series):
    """``series`` with each ROI stretched to 0-100% of its own finite
    range, so curves of wildly different brightness can be compared for
    shape and timing. NaN stays NaN, so a gap stays a gap; a curve with
    no range (min == max) sits flat at 0%, there being nothing to
    stretch and no span to divide by."""
    scaled = {}
    for roi_id, (name, elapsed, values) in series.items():
        finite = [value for value in values if value == value]
        low = min(finite) if finite else 0.0
        span = (max(finite) - low) if finite else 0.0
        scaled[roi_id] = (name, elapsed, [
            value if value != value
            else (0.0 if span == 0 else (value - low) / span * 100.0)
            for value in values])
    return scaled


def visible_series(session, series):
    """``series`` less the ROIs whose eye is off (and any entry whose
    ROI is gone). Applied once per redraw, so every view the figure
    offers hides the same ROIs; the stats table and the CSV, which are
    data rather than figure, keep them all."""
    shown = {}
    for roi_id, entry in series.items():
        roi = session.roi_by_id(roi_id)
        if roi is not None and roi.style.visible:
            shown[roi_id] = entry
    return shown
