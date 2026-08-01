"""Dock pane plotting the ROI intensity series: the chosen stat vs
elapsed time, one line per ROI. A pure observer of the shared analysis
model — it derives its own series from the session (stats store +
filters + plot stat) and coalesces notification bursts into single
redraws. Lines gap where an image failed or isn't computed."""
import os

os.environ.setdefault("QT_API", "pyside6")
import matplotlib
matplotlib.use("QtAgg")
from pathlib import Path

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg, NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from pyface.api import FileDialog, OK
from pyface.tasks.api import DockPane
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ...consts import PKG
from .consts import ROI_PLOT_COALESCE_MS
from .plot_series import derive_series
from .roi_model import PLOT_STATS, roi_analysis_model
from .roi_table import RoiStatsTable

#: Human labels for the plotted stat (dropdown + y-axis).
PLOT_STAT_LABELS = {
    "mean": "Mean intensity",
    "bg_corrected": "Background-corrected mean",
    "median": "Median intensity",
    "min": "Min intensity",
    "max": "Max intensity",
    "outline_mean": "Outline ring mean",
}

#: matplotlib linestyle codes for RoiStyle.line_style.
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":",
               "dashdot": "-."}

#: Everything the derived series depends on; one observer, one redraw
#: path. Session swap covers experiment changes; stats_revision covers
#: store growth/loads; rois/name for legend labels; plot_stat and
#: filtered_paths for the axes content.
_PLOT_STATE = ("session, session:stats_revision, session:rois.items, "
               "session:rois:items:name, session:plot_stat, "
               "session:rois:items:style:color, "
               "session:rois:items:style:line_style, "
               "session:rois:items:style:marker, "
               "session:rois:items:style:marker_size, "
               "filtered_paths.items, "
               "session:figure:x_auto, session:figure:x_min, "
               "session:figure:x_max, session:figure:y_auto, "
               "session:figure:y_min, session:figure:y_max")


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
        self._axes.set_ylabel(
            PLOT_STAT_LABELS[self._model.session.plot_stat])
        series = derive_series(self._model.session,
                               self._model.filtered_paths)
        for roi_id in list(self._lines):
            if roi_id not in series:
                self._lines.pop(roi_id).remove()
        for roi_id, (name, elapsed, values) in series.items():
            if roi_id not in self._lines:
                (self._lines[roi_id],) = self._axes.plot([], [])
            line = self._lines[roi_id]
            line.set_data(elapsed, values)
            line.set_label(name)
            roi = self._model.session.roi_by_id(roi_id)
            if roi is not None:
                line.set_color(roi.style.color)
                line.set_linestyle(LINE_STYLES[roi.style.line_style])
                line.set_marker("" if roi.style.marker == "none"
                                else roi.style.marker)
                line.set_markersize(roi.style.marker_size)
        if self._lines:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()
        figure_settings = self._model.session.figure
        self._axes.relim()
        self._axes.autoscale_view()
        if not figure_settings.x_auto:
            self._axes.set_xlim(figure_settings.x_min,
                                figure_settings.x_max)
        if not figure_settings.y_auto:
            self._axes.set_ylim(figure_settings.y_min,
                                figure_settings.y_max)
        self.draw_idle()


def _save_figure(canvas):
    """Render the current figure at the session's export settings; the
    dialog defaults into the experiment's analysis folder."""
    session = roi_analysis_model.session
    default_dir = (str(Path(session.directory) / "analysis")
                   if session.directory else "")
    extension = session.figure.export_format
    dialog = FileDialog(
        action="save as", default_directory=default_dir,
        default_filename=f"roi_intensities.{extension}",
        wildcard=f"*.{extension}")
    if dialog.open() != OK:
        return
    canvas.figure.savefig(dialog.path,
                          dpi=session.figure.export_dpi,
                          format=extension)


class FluorescenceRoiPlotDockPane(DockPane):
    """ROI intensity vs time for the filtered image series."""

    id = PKG + ".image_viewer.roi_plot_dock_pane"
    name = "Fluorescence ROI Intensities"

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        canvas = RoiPlotCanvas(roi_analysis_model)
        layout.addWidget(NavigationToolbar2QT(canvas, widget))
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Plot:", widget))
        stat_combo = QComboBox(widget)
        for stat in PLOT_STATS:
            stat_combo.addItem(PLOT_STAT_LABELS[stat], stat)
        stat_combo.setCurrentIndex(
            PLOT_STATS.index(roi_analysis_model.session.plot_stat))
        stat_combo.currentIndexChanged.connect(
            lambda index: roi_analysis_model.session.trait_set(
                plot_stat=PLOT_STATS[index]))
        controls.addWidget(stat_combo)

        _axis_syncers = []

        def _axis_editors(label, auto_trait, low_trait, high_trait):
            figure_settings = roi_analysis_model.session.figure
            auto = QCheckBox(f"{label} auto", widget)
            auto.setChecked(getattr(figure_settings, auto_trait))
            low = QDoubleSpinBox(widget)
            high = QDoubleSpinBox(widget)
            for spin, trait in ((low, low_trait), (high, high_trait)):
                spin.setRange(-1e9, 1e9)
                spin.setDecimals(1)
                spin.setValue(getattr(figure_settings, trait))
                spin.setEnabled(not auto.isChecked())
                spin.valueChanged.connect(
                    lambda value, trait=trait:
                    roi_analysis_model.session.figure.trait_set(
                        **{trait: value}))
            def _on_auto(checked, auto_trait=auto_trait, low=low,
                         high=high):
                roi_analysis_model.session.figure.trait_set(
                    **{auto_trait: bool(checked)})
                low.setEnabled(not checked)
                high.setEnabled(not checked)
            auto.toggled.connect(_on_auto)
            for control in (auto, low, high):
                controls.addWidget(control)
            _axis_syncers.append((auto, low, high, auto_trait, low_trait,
                                  high_trait))

        _axis_editors("X", "x_auto", "x_min", "x_max")
        _axis_editors("Y", "y_auto", "y_min", "y_max")

        dpi_combo = QComboBox(widget)
        for dpi in (150, 300, 600):
            dpi_combo.addItem(f"{dpi} dpi", dpi)
        dpi_combo.setCurrentIndex(
            (150, 300, 600).index(
                roi_analysis_model.session.figure.export_dpi))
        dpi_combo.currentIndexChanged.connect(
            lambda index: roi_analysis_model.session.figure.trait_set(
                export_dpi=(150, 300, 600)[index]))
        controls.addWidget(dpi_combo)
        format_combo = QComboBox(widget)
        format_combo.addItems(["png", "svg", "pdf", "tiff"])
        format_combo.setCurrentText(
            roi_analysis_model.session.figure.export_format)
        format_combo.currentTextChanged.connect(
            lambda value: roi_analysis_model.session.figure.trait_set(
                export_format=value))
        controls.addWidget(format_combo)
        save_button = QPushButton("Save plot…", widget)
        save_button.clicked.connect(
            lambda: _save_figure(canvas))
        controls.addWidget(save_button)

        controls.addStretch()
        layout.addLayout(controls)
        roi_analysis_model.observe(
            lambda event: stat_combo.setCurrentIndex(
                PLOT_STATS.index(event.object.plot_stat)),
            "session:plot_stat")

        def _sync_controls(event):
            figure_settings = event.new.figure
            stat_combo.setCurrentIndex(
                PLOT_STATS.index(event.new.plot_stat))
            dpi_combo.setCurrentIndex(
                (150, 300, 600).index(figure_settings.export_dpi))
            format_combo.setCurrentText(figure_settings.export_format)
            for auto, low, high, auto_trait, low_trait, high_trait \
                    in _axis_syncers:
                auto.setChecked(getattr(figure_settings, auto_trait))
                low.setValue(getattr(figure_settings, low_trait))
                high.setValue(getattr(figure_settings, high_trait))
        roi_analysis_model.observe(_sync_controls, "session")

        layout.addWidget(canvas)
        table = RoiStatsTable(roi_analysis_model, widget)
        layout.addWidget(table)
        progress = QLabel("", widget)
        roi_analysis_model.observe(
            lambda event: progress.setText(event.new), "progress_text")
        layout.addWidget(progress)
        return widget
