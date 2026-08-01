"""Dock pane plotting the ROI intensity series: the chosen stat vs
elapsed time, one line per ROI. A pure observer of the shared analysis
model — it derives its own series from the session (stats store +
filters + plot stat) and coalesces notification bursts into single
redraws. Lines gap where an image failed or isn't computed."""
import os

os.environ.setdefault("QT_API", "pyside6")
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg, NavigationToolbar2QT,
)
from matplotlib.figure import Figure

from pyface.tasks.api import DockPane
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...consts import PKG
from .consts import ROI_PLOT_COALESCE_MS
from .plot_series import derive_series
from .roi_model import roi_analysis_model

#: Everything the derived series depends on; one observer, one redraw
#: path. Session swap covers experiment changes; stats_revision covers
#: store growth/loads; rois/name for legend labels; plot_stat and
#: filtered_paths for the axes content.
_PLOT_STATE = ("session, session:stats_revision, session:rois.items, "
               "session:rois:items:name, session:plot_stat, "
               "filtered_paths.items")


class RoiPlotCanvas(FigureCanvasQTAgg):
    """Intensity-vs-time chart derived from the analysis model."""

    def __init__(self, model):
        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Elapsed time (s)")
        self._axes.set_ylabel("Mean intensity")
        self._axes.grid(True, alpha=0.3)
        self._lines = {}
        self._redraw_pending = False
        model.observe(self._on_plot_state_changed, _PLOT_STATE)
        self._schedule_redraw()

    def closeEvent(self, event):
        self._model.observe(self._on_plot_state_changed, _PLOT_STATE,
                            remove=True)
        super().closeEvent(event)

    def showEvent(self, event):
        self._schedule_redraw()   # catch up on anything missed hidden
        super().showEvent(event)

    def _on_plot_state_changed(self, event):
        self._schedule_redraw()

    def _schedule_redraw(self):
        if self._redraw_pending:
            return
        self._redraw_pending = True
        QTimer.singleShot(ROI_PLOT_COALESCE_MS, self._refresh)

    def _refresh(self):
        self._redraw_pending = False
        if not self.isVisible():
            return                # showEvent reschedules
        series = derive_series(self._model.session,
                               self._model.filtered_paths)
        for roi_id in list(self._lines):
            if roi_id not in series:
                self._lines.pop(roi_id).remove()
        for roi_id, (name, elapsed, values) in series.items():
            if roi_id not in self._lines:
                (self._lines[roi_id],) = self._axes.plot(
                    [], [], marker=".", label=name)
            line = self._lines[roi_id]
            line.set_data(elapsed, values)
            line.set_label(name)
        if self._lines:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


class FluorescenceRoiPlotDockPane(DockPane):
    """ROI intensity vs time for the filtered image series."""

    id = PKG + ".image_viewer.roi_plot_dock_pane"
    name = "Fluorescence ROI Intensities"

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        canvas = RoiPlotCanvas(roi_analysis_model)
        layout.addWidget(NavigationToolbar2QT(canvas, widget))
        layout.addWidget(canvas)
        progress = QLabel("", widget)
        roi_analysis_model.observe(
            lambda event: progress.setText(event.new), "progress_text")
        layout.addWidget(progress)
        return widget
