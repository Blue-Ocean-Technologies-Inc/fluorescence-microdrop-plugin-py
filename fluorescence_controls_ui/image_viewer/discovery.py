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


def current_captures_directory():
    """The captures folder of the CURRENT experiment (re-resolved on
    every call so experiment switches are picked up), or None when the
    experiment directory is unavailable (e.g. no Redis)."""
    try:
        return get_current_experiment_directory() / CAPTURES_DIR_NAME
    except Exception as e:
        logger.debug(f"Experiment directory unavailable: {e}")
        return None


def discover_captures(directory) -> list:
    """Every RAW image (IMAGE_PATTERNS) under ``directory``, recursively,
    oldest first (save time, with the filename — which embeds a capture's
    UTC timestamp — as tiebreak). [] when the directory is unset or
    missing.

    Recursive because a capture-chain burst writes one folder per burst
    (``<step>_<utc>/16bit_raw/<label>_raw.png``); the parent-name filter
    keeps the viewer raws-only (its 16-bit windowing is the point) and
    still matches the old flat ``captures/16bit_raw/`` layout."""
    if directory is None or not Path(directory).is_dir():
        return []
    paths = {path for pattern in IMAGE_PATTERNS
             for path in Path(directory).rglob(pattern)
             if path.parent.name == RAW_CAPTURES_SUBDIR}
    return sorted(paths, key=lambda path: (path.stat().st_mtime, path.name))
