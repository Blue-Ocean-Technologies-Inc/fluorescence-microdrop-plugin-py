"""Dock pane plotting the ROI intensity series: mean intensity vs
elapsed time, one line per ROI, streaming in as the batch computes
(poll-timer canvas over the shared analysis model — the temperature
canvas pattern). Lines gap where an image failed or isn't computed."""
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
from .consts import ROI_PLOT_REFRESH_INTERVAL_MS
from .roi_model import roi_analysis_model


class RoiPlotCanvas(FigureCanvasQTAgg):
    """Intensity-vs-time chart fed from the analysis model's
    ``plot_series``; redraws only when ``plot_revision`` moves."""

    def __init__(self, model):
        self._figure = Figure(figsize=(4, 3), tight_layout=True)
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Elapsed time (s)")
        self._axes.set_ylabel("Mean intensity")
        self._axes.grid(True, alpha=0.3)
        self._lines = {}
        self._plotted_revision = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)

    def showEvent(self, event):
        self._timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _refresh(self):
        if self._model.plot_revision == self._plotted_revision:
            return
        self._plotted_revision = self._model.plot_revision
        series = dict(self._model.plot_series)
        for roi_id in list(self._lines):
            if roi_id not in series:
                self._lines.pop(roi_id).remove()
        for roi_id, (name, elapsed, means) in series.items():
            if roi_id not in self._lines:
                (self._lines[roi_id],) = self._axes.plot(
                    [], [], marker=".", label=name)
            line = self._lines[roi_id]
            line.set_data(elapsed, means)
            line.set_label(name)
        if self._lines:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


class FluorescenceRoiPlotDockPane(DockPane):
    """ROI mean intensity vs time for the filtered image series."""

    id = PKG + ".image_viewer.roi_plot_dock_pane"
    name = "Fluorescence ROI Intensities"

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        canvas = RoiPlotCanvas(roi_analysis_model)
        layout.addWidget(NavigationToolbar2QT(canvas, widget))
        layout.addWidget(canvas)
        progress = QLabel("", widget)
        layout.addWidget(progress)
        timer = QTimer(widget)
        timer.timeout.connect(
            lambda: progress.setText(roi_analysis_model.progress_text))
        timer.start(ROI_PLOT_REFRESH_INTERVAL_MS)
        return widget
