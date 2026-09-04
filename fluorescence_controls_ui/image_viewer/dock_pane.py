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

import threading
from pathlib import Path

from PySide6.QtCore import QTimer

from pyface.tasks.api import TraitsDockPane
from traits.api import Any, Instance, observe

# Sanctioned cross-plugin channel: device_viewer.consts is the published
# contract for locating and now NOTICING captures (same pattern as the
# capture-layout constants imported by the controller).
from device_viewer.consts import CAPTURES_DIR_NAME, media_capture_event_model

from ..consts import DISCOVERY_POLL_INTERVAL_MS, PKG, SLIDESHOW_INTERVAL_MS
from .analysis.ai_controller import AiRoiController
from .analysis.consts import ANALYSIS_RESULT_DRAIN_INTERVAL_MS
from .analysis.roi_batch import _shared_executor
from .analysis.roi_controller import RoiAnalysisController
from .controller import FluorescenceImageViewerController
from .model import FluorescenceImageViewerModel
from .view import ImageViewerView

from logger.logger_service import get_logger

logger = get_logger(__name__)

#: Named for what it is rather than for the plugin it currently ships
#: in: the viewer is on its way to a plugin of its own.
_dock_pane_name = "Image Viewer"


def _title_for(browsed_directory: str, info_text: str) -> str:
    """The pane title for the browsed folder — "Name - folder", the
    device-viewer dock pane's convention — plus the loaded image's
    summary (the model's ``info_text``). The default captures dir would
    just read "captures", so its parent (the experiment folder) names it
    instead; '' (nothing resolved yet) keeps the bare name."""
    title = _dock_pane_name
    if browsed_directory:
        folder = Path(browsed_directory)
        display = (
            folder.parent.name
            if folder.name == CAPTURES_DIR_NAME and folder.parent.name
            else folder.name
        )
        title += "\t-\t" + display
    if info_text:
        title += "\t-\t" + info_text
    return title


class FluorescenceImageViewerDockPane(TraitsDockPane):
    """Viewer for captured fluorescence images (16-bit aware)."""

    id = PKG + ".image_viewer.dock_pane"
    name = _dock_pane_name

    view = ImageViewerView

    model = Instance(FluorescenceImageViewerModel)
    controller = Instance(FluorescenceImageViewerController)
    analysis_controller = Instance(RoiAnalysisController)
    ai_controller = Instance(AiRoiController)
    _poll_timer = Any()
    _play_timer = Any()
    _drain_timer = Any()

    def traits_init(self):
        self.model = FluorescenceImageViewerModel()
        self.controller = FluorescenceImageViewerController(model=self.model)
        self.analysis_controller = RoiAnalysisController(
            viewer_model=self.model, analysis_model=self.model.roi_analysis
        )
        self.ai_controller = AiRoiController(
            viewer_model=self.model, analysis_model=self.model.roi_analysis
        )
        # Warm the process pool off-thread so the first Calculate does
        # not pay the Windows spawn cost (~seconds for cv2 workers).
        threading.Thread(target=_shared_executor, daemon=True).start()
        # Event-driven refresh: the device viewer fires this the moment a
        # capture file finishes writing, so new images appear immediately
        # instead of on the next poll tick (the poll below stays only to
        # follow experiment-folder switches).
        media_capture_event_model.observe(self._on_media_captured, "captured")

    def trait_context(self):
        """The pane's model and the analysis model.

        TraitsUI checks every ``enabled_when`` when a trait changes on
        an object IN THE CONTEXT, and not for nested traits reached
        through one. The rolling-ball controls are enabled by a trait
        on the analysis model, which is nested under the viewer model —
        so without this the toolbar toggle left them stale until some
        unrelated edit to the viewer model (hovering the image, which
        writes the pixel readout) happened to trigger the check.
        """
        context = super().trait_context()
        context["analysis"] = self.model.roi_analysis
        return context

    def destroy(self):
        media_capture_event_model.observe(
            self._on_media_captured, "captured", remove=True
        )
        super().destroy()

    def _on_media_captured(self, event):
        self.controller.rescan()

    def create_contents(self, parent):
        self.ui = self.edit_traits(
            kind="subpanel", parent=parent, handler=self.controller
        )
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
        self._drain_timer = QTimer(control)
        self._drain_timer.setInterval(ANALYSIS_RESULT_DRAIN_INTERVAL_MS)
        self._drain_timer.timeout.connect(self._drain_tick)
        self._drain_timer.start()
        self.controller.rescan()
        return control

    def _drain_tick(self):
        self.controller.drain_loaded()
        # ai_controller first: its TRACK_FRAME handling marks
        # tracked-override config dirty, and analysis_controller's
        # drain_results/flush_stats should flush that in the same tick
        # it was marked, not a tick behind.
        self.ai_controller.drain_results()
        self.analysis_controller.drain_results()
        self.analysis_controller.flush_stats()

    @observe("model:browsed_directory, model:info_text")
    def _update_title(self, event):
        self.name = _title_for(self.model.browsed_directory, self.model.info_text)

    @observe("model:playing")
    def _sync_slideshow_timer(self, event):
        if self._play_timer is None:
            return
        if event.new:
            self._play_timer.start()
        else:
            self._play_timer.stop()
