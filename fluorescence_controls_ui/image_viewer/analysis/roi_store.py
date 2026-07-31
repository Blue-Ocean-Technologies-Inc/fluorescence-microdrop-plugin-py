"""Persistence for the ROI analysis: the per-experiment roi_config.json
(bases + overrides, auto-saved on change and auto-loaded per experiment)
and the intensity CSV export. Qt-free, pure file IO."""
import csv
import json
from pathlib import Path

from logger.logger_service import get_logger

from .consts import ANALYSIS_DIR_NAME, OUTLINE_STATS_PREFIX, \
    ROI_CONFIG_FILENAME
from .roi_compute import STAT_NAMES
from .roi_model import Roi

logger = get_logger(__name__)


def analysis_directory(experiment_directory) -> Path:
    """The experiment's analysis output folder, created on demand."""
    directory = Path(experiment_directory) / ANALYSIS_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_roi_config(experiment_directory, rois):
    payload = [{
        "roi_id": roi.roi_id,
        "name": roi.name,
        "kind": roi.kind,
        "geometry": list(roi.geometry),
        "base_anchor": roi.base_anchor,
        "overrides": {repr(anchor): list(geometry)
                      for anchor, geometry in roi.overrides.items()},
    } for roi in rois]
    path = analysis_directory(experiment_directory) / ROI_CONFIG_FILENAME
    path.write_text(json.dumps(payload, indent=2))


def load_roi_config(experiment_directory) -> list:
    """The experiment's saved ROIs, [] when absent or unreadable."""
    path = (Path(experiment_directory) / ANALYSIS_DIR_NAME
            / ROI_CONFIG_FILENAME)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
        return [
            Roi(roi_id=entry["roi_id"], name=entry["name"],
                kind=entry["kind"],
                geometry=[float(value) for value in entry["geometry"]],
                base_anchor=float(entry["base_anchor"]),
                overrides={
                    float(anchor): [float(value) for value in geometry]
                    for anchor, geometry in entry["overrides"].items()})
            for entry in payload]
    except Exception as error:
        logger.warning(f"Could not load ROI config {path}: {error}")
        return []


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
