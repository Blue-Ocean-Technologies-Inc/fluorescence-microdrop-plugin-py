"""Series derivation for the ROI plot: a pure function of the session
and the viewer's filtered paths, so the plot pane owns its own picture
(observer pattern — nothing pushes series at it). Qt-free."""
import math


def stat_value(stats, stat):
    """The plotted value for one (image, ROI) stats dict — NaN when the
    stats are missing entirely or lack the needed keys.
    ``bg_corrected`` is interior mean minus outline-ring mean."""
    if not stats:
        return math.nan
    if stat == "bg_corrected":
        mean = stats.get("mean")
        outline = stats.get("outline_mean")
        if mean is None or outline is None:
            return math.nan
        return mean - outline
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
    times = [session.stat_info(path, stat_cache)[1] for path in paths]
    start_time = times[0]
    series = {}
    for roi in session.rois:
        elapsed, values = [], []
        for path, capture_time in zip(paths, times):
            stats = session.stats.get(
                session.cache_key(path, roi, stat_cache))
            elapsed.append(capture_time - start_time)
            values.append(stat_value(stats, session.plot_stat))
        series[roi.roi_id] = (roi.name, elapsed, values)
    return series


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
