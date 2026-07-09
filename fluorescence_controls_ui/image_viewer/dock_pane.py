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
from pyface.tasks.api import TraitsDockPane
from PySide6.QtCore import QTimer
from traits.api import Any, Instance, observe

from logger.logger_service import get_logger

from ..consts import PKG
from ..consts import DISCOVERY_POLL_INTERVAL_MS, SLIDESHOW_INTERVAL_MS
from .controller import FluorescenceImageViewerController
from .model import FluorescenceImageViewerModel
from .view import ImageViewerView

logger = get_logger(__name__)


class FluorescenceImageViewerDockPane(TraitsDockPane):
    """Viewer for captured fluorescence images (16-bit aware)."""

    id = PKG + ".image_viewer.dock_pane"
    name = "Fluorescence Images"

    view = ImageViewerView

    model = Instance(FluorescenceImageViewerModel)
    controller = Instance(FluorescenceImageViewerController)
    _poll_timer = Any()
    _play_timer = Any()

    def traits_init(self):
        self.model = FluorescenceImageViewerModel()
        self.controller = FluorescenceImageViewerController(model=self.model)

    def create_contents(self, parent):
        self.ui = self.edit_traits(
            kind="subpanel", parent=parent, handler=self.controller)
        control = self.ui.control
        # Qt schedulers are view-owned: the slideshow tick and the capture
        # discovery poll (which also picks up experiment-folder switches).
        self._play_timer = QTimer(control)
        self._play_timer.setInterval(SLIDESHOW_INTERVAL_MS)
        self._play_timer.timeout.connect(lambda: self.controller.step(1))
        self._poll_timer = QTimer(control)
        self._poll_timer.setInterval(DISCOVERY_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.controller.rescan)
        self._poll_timer.start()
        self.controller.rescan()
        return control

    @observe("model:playing")
    def _sync_slideshow_timer(self, event):
        if self._play_timer is None:
            return
        if event.new:
            self._play_timer.start()
        else:
            self._play_timer.stop()
