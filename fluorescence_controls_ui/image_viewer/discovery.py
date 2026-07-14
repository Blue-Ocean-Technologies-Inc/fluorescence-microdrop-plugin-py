"""Capture discovery for the image viewer: where the device viewer saves
the raw (16-bit) sensor frames for the current experiment, and the ordered
list of those files. Pure path logic so it stays hardware/Qt-free testable.
"""
from pathlib import Path

from device_viewer.consts import CAPTURES_DIR_NAME, RAW_CAPTURES_SUBDIR
from microdrop_application.helpers import get_current_experiment_directory
from logger.logger_service import get_logger

from ..consts import IMAGE_PATTERNS

logger = get_logger(__name__)


def current_raw_captures_directory():
    """The raw-captures folder of the CURRENT experiment (re-resolved on
    every call so experiment switches are picked up), or None when the
    experiment directory is unavailable (e.g. no Redis)."""
    try:
        return (get_current_experiment_directory()
                / CAPTURES_DIR_NAME / RAW_CAPTURES_SUBDIR)
    except Exception as e:
        logger.debug(f"Experiment directory unavailable: {e}")
        return None


def discover_captures(directory) -> list:
    """Every image (IMAGE_PATTERNS) in ``directory``, oldest first (save
    time, with the filename — which embeds a capture's UTC timestamp — as
    tiebreak). [] when the directory is unset or missing."""
    if directory is None or not Path(directory).is_dir():
        return []
    paths = {path for pattern in IMAGE_PATTERNS
             for path in Path(directory).glob(pattern)}
    return sorted(paths, key=lambda path: (path.stat().st_mtime, path.name))
