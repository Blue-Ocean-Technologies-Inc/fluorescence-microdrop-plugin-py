"""Controller for the image viewer pane: turns toolbar events into model
mutations, loads whatever ``current_path`` points at, keeps the dropdown /
seek slider / path selection in sync, and rescans the browsed folder
(called from the pane's poll timer).
"""
from pathlib import Path

import numpy as np
from traits.api import Any, Instance, observe
from traitsui.api import Controller
from pyface.api import DirectoryDialog, OK

from logger.logger_service import get_logger
from microdrop_application.preferences import MicrodropPreferences

from .discovery import (
    current_captures_directory, detect_wavelength, discover_bursts,
)
from .display import load_image_array
from .model import FluorescenceImageViewerModel, WAVELENGTH_FILTER_ALL

logger = get_logger(__name__)


class FluorescenceImageViewerController(Controller):
    """All image loading and navigation funnels through
    ``model.current_path`` — the ONE loader below turns it into pixels.
    The dropdown and seek slider both converge on it (traits only notify
    on real changes, so the cross-sync naturally terminates)."""

    model = Instance(FluorescenceImageViewerModel)

    #: One-shot "what to show" hint consumed by the burst-selection
    #: observer ("first"/"last"/"keep"); set by rescan / home / folder
    #: handlers before they change ``selected_burst``.
    _pending_show = Any(None)

    # ------------------------------------------------------------------ #
    # UI build hook                                                        #
    # ------------------------------------------------------------------ #
    def init(self, info):
        """A long filename must not dictate the pane's minimum width: let
        the text readouts clip instead of propagating their text width
        (a QLabel's minimum size hint is its full text otherwise)."""
        from pyface.qt.QtWidgets import QSizePolicy
        for readout_name in ("info_text", "pixel_text"):
            control = getattr(info, readout_name).control
            policy = control.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            control.setSizePolicy(policy)
        return super().init(info)

    # ------------------------------------------------------------------ #
    # Toolbar events                                                       #
    # ------------------------------------------------------------------ #
    @observe("model:directory_button")
    def _pick_directory(self, event):
        # Open the built-in Pyface directory dialog
        dialog = DirectoryDialog(
            default_path=MicrodropPreferences().EXPERIMENTS_DIR,
            message="Select Images Directory"
        )

        # If the user clicks 'OK', update the hidden directory trait
        if dialog.open() == OK:
            self.model.directory = dialog.path
            logger.info(f"Image Viewer: Directory --> {self.model.directory}")

    @observe("model:directory")
    def _browse_directory(self, event):
        """A newly chosen folder: discover its bursts and start at the
        first burst's first image. A cleared directory is the home
        button's reset — it drives the rescan itself (and lands on the
        newest instead)."""
        if not event.new:
            return
        self.rescan()
        self._jump_to_burst(0, "first")

    @observe("model:home_button")
    def _return_to_experiment_captures(self, event):
        """Back to the ongoing experiment: follow its captures folder
        again and show the newest burst's newest image (so new captures
        auto-follow)."""
        self.model.directory = ""
        self.rescan()
        self._jump_to_burst(-1, "last")

    def _jump_to_burst(self, index, show):
        """Land on ``bursts[index]`` showing its first/last image."""
        names = self.model.burst_names
        if not names:
            return
        target = names[index]
        if self.model.selected_burst != target:
            self._pending_show = show
            self.model.selected_burst = target
        else:
            self._refresh_visible(show)

    @observe("model:fit_button")
    def _fit(self, event):
        self.model.fit_request = True

    @observe("model:previous_button")
    def _previous(self, event):
        self.step(-1)

    @observe("model:next_button")
    def _next(self, event):
        self.step(1)

    def step(self, step):
        """Show the discovered image ``step`` away (wrapping); also the
        slideshow tick."""
        path = self.model.relative_path(step)
        if path is not None:
            self.model.current_path = str(path)

    # ------------------------------------------------------------------ #
    # Burst dropdown / burst slider / wavelength filter                    #
    # ------------------------------------------------------------------ #
    @observe("model:selected_burst")
    def _burst_selected(self, event):
        """Burst picked (dropdown, slider, or a programmatic jump):
        sync the slider and rebuild the visible image list. A plain user
        pick starts at the burst's first image; rescan/home hand a
        different intent through ``_pending_show``."""
        show = self._pending_show or "first"
        self._pending_show = None
        names = self.model.burst_names
        if event.new in names:
            self.model.burst_index = names.index(event.new)
        self._refresh_visible(show)

    @observe("model:burst_index")
    def _burst_seek(self, event):
        names = self.model.burst_names
        if 0 <= event.new < len(names):
            self.model.selected_burst = names[event.new]

    @observe("model:selected_wavelength")
    def _wavelength_filtered(self, event):
        """Filter change: keep the displayed image when it survives the
        filter, else fall to the first surviving one."""
        self._refresh_visible("keep")

    def _visible_paths(self):
        """The selected burst's images through the wavelength filter."""
        paths = self.model.burst_paths(self.model.selected_burst)
        if self.model.selected_wavelength != WAVELENGTH_FILTER_ALL:
            paths = [path for path in paths
                     if detect_wavelength(path)
                     == self.model.selected_wavelength]
        return paths

    def _refresh_visible(self, show):
        """Rebuild ``model.paths`` and pick what to display: "first" /
        "last" of the visible list, or "keep" (stay on the current image
        when it is still visible, else fall to the first)."""
        paths = self._visible_paths()
        if paths != self.model.paths:
            self.model.paths = paths
        if not paths:
            self.model.selected_image = ""
            return
        if show == "keep" and self.model.path_index() is not None:
            self._sync_selection()
            return
        target = paths[-1] if show == "last" else paths[0]
        if self.model.current_path != str(target):
            self.model.current_path = str(target)
        else:
            self._sync_selection()

    # ------------------------------------------------------------------ #
    # Dropdown / seek-slider selection                                     #
    # ------------------------------------------------------------------ #
    @observe("model:selected_image")
    def _select_by_name(self, event):
        for path in self.model.paths:
            if path.name == event.new:
                self.model.current_path = str(path)
                return

    @observe("model:image_index")
    def _seek(self, event):
        if 0 <= event.new < len(self.model.paths):
            self.model.current_path = str(self.model.paths[event.new])

    def _sync_selection(self):
        """Point the dropdown and seek slider at the displayed image."""
        index = self.model.path_index()
        if index is not None:
            self.model.image_index = index
            self.model.selected_image = self.model.paths[index].name
        else:
            self.model.selected_image = ""

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #
    @observe("model:current_path")
    def _load_current_path(self, event):
        path = event.new
        if not path:
            return
        array = load_image_array(path)
        if array is None:
            logger.error(f"Could not load image: {path}")
            self.model.info_text = "Could not load image"
            return
        self.model.array = array
        bits = 16 if array.dtype == np.uint16 else 8
        kind = "gray" if array.ndim == 2 else "RGB"
        self.model.info_text = (f"{Path(path).name} — {array.shape[1]}x"
                                f"{array.shape[0]} {bits}-bit {kind}")
        self._sync_selection()
        logger.info(f"Loaded image: {path} ({bits}-bit {kind})")

    # ------------------------------------------------------------------ #
    # Folder discovery (driven by the pane's poll timer, GUI thread)       #
    # ------------------------------------------------------------------ #
    def _scan_directory(self):
        if self.model.directory:
            return Path(self.model.directory)
        return current_captures_directory()

    def rescan(self):
        """Sync with the browsed folder's bursts; a newly landed burst /
        image is followed automatically unless the user is parked on an
        older one. Also refreshes the wavelength-filter choices from
        what the filenames embed."""
        directory = self._scan_directory()
        self.model.browsed_directory = str(directory) if directory else ""
        bursts = discover_bursts(directory)
        if bursts == self.model.bursts:
            return
        # "Following newest" = showing the newest visible image of the
        # newest burst (or nothing yet) — those users ride along as new
        # captures land; anyone parked elsewhere stays parked.
        following_newest = (
            not self.model.current_path or not self.model.paths
            or (self.model.burst_names
                and self.model.selected_burst == self.model.burst_names[-1]
                and self.model.current_path == str(self.model.paths[-1])))
        self.model.bursts = bursts

        detected = sorted({wavelength
                           for _name, paths in bursts
                           for wavelength in map(detect_wavelength, paths)
                           if wavelength})
        self.model.wavelength_names = [WAVELENGTH_FILTER_ALL] + detected
        if self.model.selected_wavelength not in self.model.wavelength_names:
            self.model.selected_wavelength = WAVELENGTH_FILTER_ALL

        names = self.model.burst_names
        if not names:
            self.model.paths = []
            self.model.selected_image = ""
            return
        if following_newest:
            self._jump_to_burst(-1, "last")
        elif self.model.selected_burst not in names:
            # The parked burst vanished (folder pruned): fall to newest.
            self._jump_to_burst(-1, "first")
        else:
            self._refresh_visible("keep")
