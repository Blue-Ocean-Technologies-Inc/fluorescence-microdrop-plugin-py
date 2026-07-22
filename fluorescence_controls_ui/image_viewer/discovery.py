"""Capture discovery for the image viewer: where the device viewer saves
the raw (16-bit) sensor frames for the current experiment, and the ordered
list of those files. Pure path logic so it stays hardware/Qt-free testable.
"""
from pathlib import Path

from device_viewer.consts import CAPTURES_DIR_NAME, RAW_CAPTURES_SUBDIR
from fluorescence_controller.consts import LED_WAVELENGTHS
from fluorescence_protocol_controls.capture_chain import sanitize_label
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


def discover_experiments() -> list:
    """Every experiment folder alongside the current experiment:
    ``[(name, captures_path), ...]``, oldest first (by the folder's mtime).

    Rooted at the CURRENT experiment's parent (``get_current_experiment_
    directory().parent``) rather than a bare ``MicrodropPreferences()`` read
    — that instance returns the trait default, not the app's configured
    root, so it points at an empty folder. The parent of the folder the
    viewer already follows is exactly the Experiments root in use. Folders
    with no captures yet are still listed (selecting one just shows nothing)
    so the seek can walk them all. [] when the root is unavailable (no
    Redis)."""
    try:
        root = get_current_experiment_directory().parent
    except Exception as e:
        logger.debug(f"Experiments root unavailable: {e}")
        return []
    if not root.is_dir():
        return []
    experiments = [(child.name, child / CAPTURES_DIR_NAME)
                   for child in root.iterdir() if child.is_dir()]
    return sorted(experiments,
                  key=lambda item: (item[1].parent.stat().st_mtime, item[0]))


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


#: The legacy flat layout (captures/16bit_raw/*.png, pre-burst) shows up
#: as one pseudo-burst under this name.
UNGROUPED_BURST = "ungrouped"


def discover_bursts(directory) -> list:
    """The captures under ``directory`` grouped per burst folder:
    ``[(burst_name, [paths...]), ...]``, oldest burst first (by its first
    image's save time), images within a burst oldest first. A burst is a
    ``<name>_<utc>`` subfolder holding a ``16bit_raw`` dir; images from
    the legacy flat ``captures/16bit_raw`` layout appear as the single
    ``UNGROUPED_BURST`` entry. [] when the directory is unset/missing."""
    groups: dict = {}
    root = Path(directory) if directory is not None else None
    for path in discover_captures(directory):
        burst_dir = path.parent.parent   # <burst>/16bit_raw/<file>
        name = UNGROUPED_BURST if burst_dir == root else burst_dir.name
        groups.setdefault(name, []).append(path)
    return sorted(groups.items(),
                  key=lambda item: (item[1][0].stat().st_mtime, item[0]))


#: sanitized-token -> display name for the six LED wavelengths; derived
#: labels embed the sanitized form (e.g. "Green_540_nm"), which is how a
#: file's wavelength is detected.
WAVELENGTH_TOKENS = {sanitize_label(name): name for name in LED_WAVELENGTHS}


def detect_wavelength(path) -> str:
    """The display wavelength a capture filename embeds, or '' when none
    of the known LED wavelengths appears in it (e.g. legacy screen
    captures)."""
    name = Path(path).name
    for token, display in WAVELENGTH_TOKENS.items():
        if token in name:
            return display
    return ""
