"""Controller for the image viewer pane: turns toolbar events into model
mutations, loads whatever ``current_path`` points at, keeps the dropdown /
seek slider / path selection in sync, and rescans the browsed folder
(called from the pane's poll timer).

Loading is asynchronous, latest-wins: ``current_path`` changes replace
the loader thread's single pending request, so dragging the seek slider
never decodes the frames dragged past and never blocks the GUI thread.
Finished decodes land through ``drain_loaded()`` (the dock pane's drain
timer) and a small LRU cache makes recently viewed frames instant.
"""
import queue
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
from traits.api import Any, Instance, Str, observe
from traitsui.api import Controller
from pyface.api import DirectoryDialog, OK

from logger.logger_service import get_logger
from microdrop_application.preferences import MicrodropPreferences

from ..consts import IMAGE_CACHE_FRAMES
from .discovery import (
    current_captures_directory, detect_wavelength, discover_bursts,
    discover_experiments,
)
from .display import load_image_array
from .model import (
    BURST_FILTER_ALL, FluorescenceImageViewerModel, WAVELENGTH_FILTER_ALL,
)

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

    #: Decoded frames, path -> array, newest last; bounded by
    #: IMAGE_CACHE_FRAMES so recently viewed frames re-display instantly.
    _decoded_cache = Instance(OrderedDict, ())

    #: (path, array | None) results from the loader thread, applied on
    #: the GUI thread by drain_loaded().
    _load_results = Instance(queue.SimpleQueue, ())

    #: The newest not-yet-started decode request. The loader always takes
    #: this and only this, so frames the slider dragged past are skipped.
    _pending_load = Str()
    _pending_load_lock = Instance(object)
    _load_wakeup = Instance(object)
    _load_worker = Instance(object)

    def __pending_load_lock_default(self):
        return threading.Lock()

    def __load_wakeup_default(self):
        return threading.Event()

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

    # ------------------------------------------------------------------ #
    # Experiment dropdown / experiment slider                              #
    # ------------------------------------------------------------------ #
    @observe("model:selected_experiment")
    def _experiment_selected(self, event):
        """Experiment picked (dropdown or slider): sync the slider and
        repoint the viewer at that experiment's captures — the
        ``directory`` observer then rescans and jumps to the first burst."""
        names = self.model.experiment_names
        if event.new in names:
            self.model.experiment_index = names.index(event.new)
        captures = self.model.experiment_captures(event.new)
        if captures is not None:
            self.model.directory = str(captures)

    @observe("model:experiment_index")
    def _experiment_seek(self, event):
        names = self.model.experiment_names
        if 0 <= event.new < len(names):
            self.model.selected_experiment = names[event.new]

    @observe("model:fit_button")
    def _fit(self, event):
        self.model.fit_request = True

    @observe("model:zoom_in_button")
    def _zoom_in(self, event):
        self.model.zoom_request = 1

    @observe("model:zoom_out_button")
    def _zoom_out(self, event):
        self.model.zoom_request = -1

    @observe("model:previous_button")
    def _previous(self, event):
        self.step(-1)

    @observe("model:next_button")
    def _next(self, event):
        self.step(1)

    def step(self, step):
        """Show the adjacent image, traversing the WHOLE experiment: within
        the current image group normally, and across group boundaries when
        the group's images are exhausted — next past the last image enters
        the next group's first image, previous before the first enters the
        previous group's last. Wraps around the experiment's groups. Also
        the slideshow tick."""
        paths = self.model.paths
        if not paths:
            return
        index = self.model.path_index()
        if index is None:
            # Displaying an image from outside the list: enter it at the
            # near end.
            self.model.current_path = str(paths[0] if step > 0 else paths[-1])
            return
        new_index = index + step
        if 0 <= new_index < len(paths):
            self.model.current_path = str(paths[new_index])
        elif new_index >= len(paths):
            self._step_to_adjacent_group(1, "first")
        else:
            self._step_to_adjacent_group(-1, "last")

    def _step_to_adjacent_group(self, direction, show):
        """Move to the next/previous image group (wrapping) and show its
        first/last image. With the "All" choice (or a single group) the
        visible list already spans everything: wrap within it."""
        if (self.model.selected_burst == BURST_FILTER_ALL
                or len(self.model.bursts) <= 1):
            paths = self.model.paths
            self.model.current_path = str(paths[0] if direction > 0
                                          else paths[-1])
            return
        group_index = (self.model.burst_index - 1 + direction) \
            % len(self.model.bursts)
        self._jump_to_burst(group_index + 1, show)

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
        return self.model.visible_of(
            self.model.burst_paths(self.model.selected_burst))

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
        cached = self._decoded_cache.get(path)
        if cached is not None:
            self._decoded_cache.move_to_end(path)
            self._apply_loaded(path, cached)
            return
        # Latest wins: replace any not-yet-started request so frames the
        # slider dragged past are never decoded at all.
        with self._pending_load_lock:
            self._pending_load = path
            self._load_wakeup.set()
        self._ensure_load_worker()
        self.model.info_text = f"Loading {Path(path).name}…"

    def _ensure_load_worker(self):
        if self._load_worker is not None and self._load_worker.is_alive():
            return
        self._load_worker = threading.Thread(target=self._run_loader,
                                             daemon=True)
        self._load_worker.start()

    def _run_loader(self):
        """Daemon loader: decode the newest pending path, report on the
        results queue, wait for the next request."""
        while True:
            self._load_wakeup.wait()
            with self._pending_load_lock:
                path = self._pending_load
                self._pending_load = ""
                self._load_wakeup.clear()
            if not path:
                continue
            try:
                array = load_image_array(path)
            except Exception as error:
                logger.warning(f"Image decode failed for {path}: {error}")
                array = None
            self._load_results.put((path, array))

    def drain_loaded(self):
        """Called by the dock pane's drain timer (GUI thread): apply
        finished decodes. Only the currently displayed path is shown, but
        every successful decode enters the cache."""
        while True:
            try:
                path, array = self._load_results.get_nowait()
            except queue.Empty:
                return
            if array is None:
                if path == self.model.current_path:
                    logger.error(f"Could not load image: {path}")
                    self.model.info_text = "Could not load image"
                continue
            self._decoded_cache[path] = array
            self._decoded_cache.move_to_end(path)
            while len(self._decoded_cache) > IMAGE_CACHE_FRAMES:
                self._decoded_cache.popitem(last=False)
            if path == self.model.current_path:
                self._apply_loaded(path, array)

    def _apply_loaded(self, path, array):
        self.model.array = array
        bits = 16 if array.dtype == np.uint16 else 8
        kind = "gray" if array.ndim == 2 else "RGB"
        self.model.info_text = (f"{Path(path).name} - {array.shape[1]}x"
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
        # Refresh the experiment list (cheap dir listing) so the Experiments
        # dropdown tracks newly created experiments; the user's selection is
        # left untouched.
        experiments = discover_experiments()
        if experiments != self.model.experiments:
            self.model.experiments = experiments

        directory = self._scan_directory()
        self.model.browsed_directory = str(directory) if directory else ""
        bursts = discover_bursts(directory)
        if bursts == self.model.bursts:
            return
        # "Following newest" = showing the newest visible image of the
        # newest burst (or nothing yet) — those users ride along as new
        # captures land; anyone parked elsewhere stays parked.
        on_all = self.model.selected_burst == BURST_FILTER_ALL
        following_newest = (
            not self.model.current_path or not self.model.paths
            or (on_all
                and self.model.current_path == str(self.model.paths[-1]))
            or (not on_all and self.model.burst_names
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
            if on_all:
                self._refresh_visible("last")
            else:
                self._jump_to_burst(-1, "last")
        elif self.model.selected_burst not in names:
            # The parked burst vanished (folder pruned): fall to newest.
            self._jump_to_burst(-1, "first")
        else:
            self._refresh_visible("keep")
