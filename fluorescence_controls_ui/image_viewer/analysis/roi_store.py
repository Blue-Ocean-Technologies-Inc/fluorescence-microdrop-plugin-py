"""Persistence for the ROI analysis: the per-experiment session config
(roi_config.json v2 — ROIs with styles, plot stat, figure settings),
the computed-stats store (roi_stats.json), and the intensity CSV
export. Qt-free, pure file IO."""
import csv
import json
from pathlib import Path

from logger.logger_service import get_logger

from .consts import ANALYSIS_DIR_NAME, OUTLINE_STATS_PREFIX, \
    ROI_CONFIG_FILENAME, ROI_STATS_FILENAME
from .roi_compute import STAT_NAMES
from .roi_geometry import normalize
from .roi_model import (
    AnalysisSession, FigureSettings, Roi, RoiStyle, ScaleCalibration,
)

logger = get_logger(__name__)

#: Persisted FigureSettings fields (also the tolerated-missing set on
#: load, so older configs upgrade with defaults).
_FIGURE_FIELDS = ("x_auto", "x_min", "x_max", "y_auto", "y_min",
                  "y_max", "export_format", "export_dpi",
                  "fit_method", "trim_poor_fit", "show_legend",
                  "show_fit_equations",
                  "show_second_derivative_max",
                  "show_second_derivative_min",
                  "second_derivative_vline", "second_derivative_hline",
                  "second_derivative_coords", "view_mode")
_STYLE_FIELDS = ("color", "line_style", "marker", "marker_size",
                 "visible", "alpha")

#: Persisted ScaleCalibration fields (tolerated-missing on load, so a
#: config written before the scale bar opens uncalibrated).
_SCALE_FIELDS = ("metres_per_pixel", "value", "unit", "show_bar")


def analysis_directory(experiment_directory) -> Path:
    """The experiment's analysis output folder, created on demand."""
    directory = Path(experiment_directory) / ANALYSIS_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_session(experiment_directory, session):
    payload = {
        "version": 2,
        "plot_stat": session.plot_stat,
        "figure": {name: getattr(session.figure, name)
                   for name in _FIGURE_FIELDS},
        "scale": {name: getattr(session.scale, name)
                  for name in _SCALE_FIELDS},
        "rois": [{
            "roi_id": roi.roi_id,
            "name": roi.name,
            "kind": roi.kind,
            "geometry": list(roi.geometry),
            "base_anchor": roi.base_anchor,
            "overrides": {repr(anchor): list(geometry)
                          for anchor, geometry in roi.overrides.items()},
            "style": {name: getattr(roi.style, name)
                      for name in _STYLE_FIELDS},
        } for roi in session.rois],
    }
    path = analysis_directory(experiment_directory) / ROI_CONFIG_FILENAME
    path.write_text(json.dumps(payload, indent=2))


def _roi_from(entry):
    style = RoiStyle()
    style.trait_set(**{name: entry.get("style", {})[name]
                       for name in _STYLE_FIELDS
                       if name in entry.get("style", {})})
    kind, geometry = normalize(entry["kind"], entry["geometry"])
    return Roi(roi_id=entry["roi_id"], name=entry["name"],
               kind=kind, geometry=geometry,
               base_anchor=float(entry["base_anchor"]),
               overrides={
                   float(anchor): normalize(kind, override)[1]
                   for anchor, override in entry["overrides"].items()},
               style=style)


def load_session(experiment_directory) -> AnalysisSession:
    """The experiment's saved analysis session; empty (with defaults)
    when absent or unreadable. Accepts the v1 format (a bare ROI list,
    no styles/figure) with defaults filling the rest. One bad ROI entry
    or an invalid plot_stat/figure value is skipped/defaulted in place
    rather than discarding every other ROI already parsed."""
    session = AnalysisSession(directory=str(experiment_directory))
    path = (Path(experiment_directory) / ANALYSIS_DIR_NAME
            / ROI_CONFIG_FILENAME)
    if not path.is_file():
        return session
    try:
        payload = json.loads(path.read_text())
        entries = payload if isinstance(payload, list) \
            else payload["rois"]
    except Exception as error:
        logger.warning(f"Could not load ROI config {path}: {error}")
        return AnalysisSession(directory=str(experiment_directory))

    rois = []
    for entry in entries:
        try:
            rois.append(_roi_from(entry))
        except Exception as error:
            logger.warning(f"Skipping unreadable ROI entry in {path}: "
                           f"{error}")
    session.rois = rois

    if isinstance(payload, dict):
        try:
            session.plot_stat = payload.get("plot_stat", "mean")
        except Exception as error:
            logger.warning(f"Ignoring invalid plot_stat in {path}: "
                           f"{error}")
        try:
            figure = FigureSettings()
            figure.trait_set(**{name: payload.get("figure", {})[name]
                                for name in _FIGURE_FIELDS
                                if name in payload.get("figure", {})})
            session.figure = figure
        except Exception as error:
            logger.warning(f"Ignoring invalid figure settings in "
                           f"{path}: {error}")
        try:
            scale = ScaleCalibration()
            scale.trait_set(**{name: payload.get("scale", {})[name]
                               for name in _SCALE_FIELDS
                               if name in payload.get("scale", {})})
            session.scale = scale
        except Exception as error:
            logger.warning(f"Ignoring invalid scale settings in "
                           f"{path}: {error}")
    return session


def save_roi_stats(experiment_directory, stats):
    """Lossless dump of the computed-stats store (json allows the NaN
    literal, which Python's parser reads back)."""
    payload = {"version": 1, "entries": [{
        "path": key[0], "mtime": key[1], "roi_id": key[2],
        "kind": key[3], "geometry": list(key[4]), "stats": value,
    } for key, value in stats.items()]}
    path = analysis_directory(experiment_directory) / ROI_STATS_FILENAME
    path.write_text(json.dumps(payload))


def _stats_key(entry):
    """The cache key a stats entry answers to, migrated the same way
    the ROI it belongs to is — so intensities computed before shapes
    could rotate keep matching after."""
    kind, geometry = normalize(entry["kind"], entry["geometry"])
    return (entry["path"], float(entry["mtime"]), entry["roi_id"],
            kind, tuple(geometry))


def load_roi_stats(experiment_directory) -> dict:
    """The persisted stats store, {} when absent/unreadable/unknown
    version. Entries that no longer match anything (moved ROI, changed
    file) are simply never looked up — invalidation stays automatic."""
    path = (Path(experiment_directory) / ANALYSIS_DIR_NAME
            / ROI_STATS_FILENAME)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
        if payload["version"] != 1:
            logger.warning(f"Unknown ROI stats version in {path}")
            return {}
        return {_stats_key(entry): entry["stats"]
                for entry in payload["entries"]}
    except Exception as error:
        logger.warning(f"Could not load ROI stats {path}: {error}")
        return {}


#: Per-ROI CSV columns, in order: interior stats then outline stats.
CSV_STAT_COLUMNS = tuple(STAT_NAMES) + tuple(
    OUTLINE_STATS_PREFIX + name for name in STAT_NAMES)


def write_intensity_csv(csv_path, rows, rois):
    """One row per image, blank cells where an (image, ROI) pair has no
    computed stats. ``rows``: [{"filename", "time_utc", "elapsed_sec",
    "group", "wavelength", "stats": {roi_id: stats_dict}}, ...]."""
    header = ["index", "time_utc", "elapsed_sec", "filename", "group",
              "wavelength"]
    for roi in rois:
        header += [f"{roi.name}_{stat}" for stat in CSV_STAT_COLUMNS]
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index, row in enumerate(rows):
            record = [index, row["time_utc"], row["elapsed_sec"],
                      row["filename"], row["group"], row["wavelength"]]
            for roi in rois:
                stats = row["stats"].get(roi.roi_id, {})
                record += [stats.get(stat, "")
                           for stat in CSV_STAT_COLUMNS]
            writer.writerow(record)
