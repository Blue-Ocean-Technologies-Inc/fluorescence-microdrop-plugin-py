"""Fluorescence image viewer dock pane (thin MVC shell).

Displays 16-bit captures (the raw sensor frames the device viewer saves
under ``captures/16bit_raw``) with auto-contrast/manual windowing,
wheel-zoom/drag-pan, and a live pixel-value readout. The pane discovers
the current experiment's raw captures itself, follows new ones as they
land, and can step/cycle through them like a slideshow.

State lives in :class:`FluorescenceImageViewerModel` (Qt-free), behavior
in :class:`FluorescenceImageViewerController`, widgets in ``view.py``.
This pane only assembles them, owns the Qt timers (the view-injected
schedulers), and binds the persisted display-window preferences.
"""
from pathlib import Path

from pyface.tasks.api import TraitsDockPane
from PySide6.QtCore import QTimer
from traits.api import Any, Instance, observe

# Sanctioned cross-plugin channel: device_viewer.consts is the published
# contract for locating and now NOTICING captures (same pattern as the
# capture-layout constants imported by the controller).
from device_viewer.consts import CAPTURES_DIR_NAME, media_capture_event_model

from logger.logger_service import get_logger

from ..consts import PKG
from ..consts import DISCOVERY_POLL_INTERVAL_MS, SLIDESHOW_INTERVAL_MS
from .controller import FluorescenceImageViewerController
from .model import FluorescenceImageViewerModel
from .view import ImageViewerView

logger = get_logger(__name__)

_dock_pane_name = "Fluorescence Images"


def _title_for(browsed_directory: str) -> str:
    """The pane title for the browsed folder — "Name - folder", the
    device-viewer dock pane's convention. The default captures dir would
    just read "captures", so its parent (the experiment folder) names it
    instead; '' (nothing resolved yet) keeps the bare name."""
    if not browsed_directory:
        return _dock_pane_name
    folder = Path(browsed_directory)
    display = (folder.parent.name
               if folder.name == CAPTURES_DIR_NAME and folder.parent.name
               else folder.name)
    return _dock_pane_name + "\t\t-\t\t" + display


class FluorescenceImageViewerDockPane(TraitsDockPane):
    """Viewer for captured fluorescence images (16-bit aware)."""

    id = PKG + ".image_viewer.dock_pane"
    name = _dock_pane_name

    view = ImageViewerView

    model = Instance(FluorescenceImageViewerModel)
    controller = Instance(FluorescenceImageViewerController)
    _poll_timer = Any()
    _play_timer = Any()

    def traits_init(self):
        self.model = FluorescenceImageViewerModel()
        self.controller = FluorescenceImageViewerController(model=self.model)
        # Event-driven refresh: the device viewer fires this the moment a
        # capture file finishes writing, so new images appear immediately
        # instead of on the next poll tick (the poll below stays only to
        # follow experiment-folder switches).
        media_capture_event_model.observe(self._on_media_captured, "captured")

    def destroy(self):
        media_capture_event_model.observe(self._on_media_captured, "captured",
                                          remove=True)
        super().destroy()

    def _on_media_captured(self, event):
        self.controller.rescan()

    def create_contents(self, parent):
        self.ui = self.edit_traits(
            kind="subpanel", parent=parent, handler=self.controller)
        control = self.ui.control
        # Qt schedulers are view-owned: the slideshow tick and the
        # experiment-folder-switch poll (new captures arrive event-driven
        # via media_capture_event_model above).
        self._play_timer = QTimer(control)
        self._play_timer.setInterval(SLIDESHOW_INTERVAL_MS)
        self._play_timer.timeout.connect(lambda: self.controller.step(1))
        self._poll_timer = QTimer(control)
        self._poll_timer.setInterval(DISCOVERY_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.controller.rescan)
        self._poll_timer.start()
        self.controller.rescan()
        return control

    @observe("model:browsed_directory")
    def _update_title(self, event):
        self.name = _title_for(event.new)

    @observe("model:playing")
    def _sync_slideshow_timer(self, event):
        if self._play_timer is None:
            return
        if event.new:
            self._play_timer.start()
        else:
            self._play_timer.stop()
