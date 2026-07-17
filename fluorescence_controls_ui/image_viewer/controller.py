"""Controller for the image viewer pane: turns toolbar events into model
mutations, loads whatever ``current_path`` points at, keeps the dropdown /
seek slider / path selection in sync, and rescans the browsed folder
(called from the pane's poll timer).
"""
from pathlib import Path

import numpy as np
from traits.api import Instance, observe
from traitsui.api import Controller
from pyface.api import DirectoryDialog, OK

from logger.logger_service import get_logger
from microdrop_application.preferences import MicrodropPreferences

from .discovery import current_captures_directory, discover_captures
from .display import load_image_array
from .model import FluorescenceImageViewerModel

logger = get_logger(__name__)


class FluorescenceImageViewerController(Controller):
    """All image loading and navigation funnels through
    ``model.current_path`` — the ONE loader below turns it into pixels.
    The dropdown and seek slider both converge on it (traits only notify
    on real changes, so the cross-sync naturally terminates)."""

    model = Instance(FluorescenceImageViewerModel)

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
        """A newly chosen folder: discover its images and start at the
        first one. A cleared directory is the home button's reset — it
        drives the rescan itself (and lands on the newest instead)."""
        if not event.new:
            return
        self.rescan()
        if self.model.paths:
            self.model.current_path = str(self.model.paths[0])

    @observe("model:home_button")
    def _return_to_experiment_captures(self, event):
        """Back to the ongoing experiment: follow its raw-captures folder
        again and show the newest image (so new captures auto-follow)."""
        self.model.directory = ""
        self.rescan()
        if self.model.paths:
            self.model.current_path = str(self.model.paths[-1])

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
        """Sync with the browsed folder; a newly landed image is shown
        automatically unless the user is parked on an older one."""
        paths = discover_captures(self._scan_directory())
        if paths == self.model.paths:
            return
        following_newest = (
            not self.model.current_path or not self.model.paths
            or self.model.current_path == str(self.model.paths[-1]))
        self.model.paths = paths
        if paths and following_newest \
                and self.model.current_path != str(paths[-1]):
            self.model.current_path = str(paths[-1])
        else:
            self._sync_selection()   # indices may have shifted
