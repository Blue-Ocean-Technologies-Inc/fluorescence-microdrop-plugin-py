"""Dock pane plotting the ROI intensity series: the chosen stat vs
elapsed time, one line per ROI — or, per the View dropdown, the fits'
second-derivative curves or the per-ROI time-of-fastest-change bars.
A pure observer of the shared analysis model — it derives its own
series from the session (stats store + filters + plot stat) and
coalesces notification bursts into single redraws. Lines gap where an
image failed or isn't computed."""
import os

os.environ.setdefault("QT_API", "pyside6")
import matplotlib
matplotlib.use("QtAgg")

import numpy as np
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg, NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator, ScalarFormatter
from pyface.api import FileDialog, OK
from pyface.tasks.api import DockPane
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QLabel, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)
from traits.api import Any, Instance
from traitsui.api import EnumEditor, HGroup, Item, UItem, VGroup, View

from microdrop_style.icons.icons import ICON_FUNCTION, ICON_SAVE
from microdrop_utils.traitsui_qt_helpers import IconButtonEditor

from ...consts import PKG
from .consts import (
    ROI_PLOT_CANVAS_MIN_HEIGHT, ROI_PLOT_CANVAS_MIN_WIDTH,
    ROI_PLOT_COALESCE_MS, VIEW_MODE_LABELS, VIEW_MODES,
)
from .curve_fit import (
    FIT_LABELS, FIT_METHODS, fastest_change_time, fit_series,
    second_derivative_extrema,
)
from .fit_equations import FitEquationsTable, fit_equation_rows
from .plot_series import derive_series
from .roi_model import PLOT_STATS, roi_analysis_model
from .roi_store import analysis_directory
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

#: Controls over the per-session plot/export traits. Rebuilt against the
#: new session on every swap (TraitsUI resolves context objects at build
#: time), which replaces all hand-written widget<->trait syncing. Two
#: rows keep the pane's un-scrolled minimum width small; `figure` is its
#: own context key because enabled_when only re-evaluates on trait
#: changes of direct context objects.
_plot_controls_view = View(
    VGroup(
        HGroup(
            Item("figure.view_mode", label="View",
                 editor=EnumEditor(values=list(VIEW_MODES),
                                   format_func=VIEW_MODE_LABELS.get)),
            Item("session.plot_stat", label="Plot",
                 editor=EnumEditor(values=list(PLOT_STATS),
                                   format_func=PLOT_STAT_LABELS.get)),
            Item("figure.x_auto", label="X auto"),
            Item("figure.x_min", label="min",
                 enabled_when="not figure.x_auto"),
            Item("figure.x_max", label="max",
                 enabled_when="not figure.x_auto"),
        ),
        HGroup(
            Item("figure.y_auto", label="Y auto"),
            Item("figure.y_min", label="min",
                 enabled_when="not figure.y_auto"),
            Item("figure.y_max", label="max",
                 enabled_when="not figure.y_auto"),
            Item("figure.export_dpi", label="DPI"),
            Item("figure.export_format", label="Format"),
            UItem("model.save_plot_button", editor=IconButtonEditor(
                glyph=ICON_SAVE,
                tooltip="Save the plot to the experiment's analysis "
                        "folder at the chosen format and DPI")),
        ),
        HGroup(
            Item("figure.fit_method", label="Fit",
                 editor=EnumEditor(values=list(FIT_METHODS),
                                   format_func=FIT_LABELS.get)),
            Item("figure.show_legend", label="Legend"),
            Item("figure.show_fit_equations", label="Equations on figure",
                 enabled_when="figure.fit_method != 'none'"),
            UItem("model.fit_equations_button", editor=IconButtonEditor(
                glyph=ICON_FUNCTION,
                tooltip="Show the fitted equation for every ROI in a "
                        "table")),
        ),
        HGroup(
            Item("figure.show_second_derivative_max", label="d² max",
                 enabled_when="figure.fit_method != 'none'"),
            Item("figure.show_second_derivative_min", label="d² min",
                 enabled_when="figure.fit_method != 'none'"),
            Item("figure.second_derivative_vline", label="V-line",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
            Item("figure.second_derivative_hline", label="H-line",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
            Item("figure.second_derivative_coords", label="Coords",
                 enabled_when="figure.show_second_derivative_max or "
                              "figure.show_second_derivative_min"),
        ),
    ),
)

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
               "session:figure:y_min, session:figure:y_max, "
               "session:figure:fit_method, session:figure:show_legend, "
               "session:figure:show_fit_equations, "
               "session:figure:show_second_derivative_max, "
               "session:figure:show_second_derivative_min, "
               "session:figure:second_derivative_vline, "
               "session:figure:second_derivative_hline, "
               "session:figure:second_derivative_coords, "
               "session:figure:view_mode")


class RoiPlotCanvas(FigureCanvasQTAgg):
    """Chart derived from the analysis model, rendering whichever view
    the session's figure settings select."""

    def __init__(self, model):
        # No layout engine: one would re-run on every draw and silently
        # discard the margins set through the toolbar's configure-subplots
        # sliders (and re-fit on savefig, breaking preview == export).
        # tight_layout() once instead, for sensible initial margins.
        self._figure = Figure(figsize=(4, 3))
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Elapsed time (s)")
        self._axes.set_ylabel("Mean intensity")
        self._axes.grid(True, alpha=0.3)
        self._figure.tight_layout()
        self._lines = {}
        self._fit_artists = []
        self._redraw_pending = False
        self._detached = False
        model.observe(self._on_plot_state_changed, _PLOT_STATE)
        self._schedule_redraw()

    def detach(self):
        # An in-flight coalesced singleShot may fire after the widget's
        # C++ side is gone; the flag makes it a no-op.
        self._detached = True
        self._model.observe(self._on_plot_state_changed, _PLOT_STATE,
                            remove=True)

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
        if self._detached:
            return
        if not self.isVisible():
            return                # showEvent reschedules
        series = derive_series(self._model.session,
                               self._model.filtered_paths)
        figure_settings = self._model.session.figure
        for artist in self._fit_artists:
            artist.remove()
        self._fit_artists = []
        # A previous fastest-change render left categorical ticks behind.
        self._axes.xaxis.set_major_locator(AutoLocator())
        self._axes.xaxis.set_major_formatter(ScalarFormatter())
        self._axes.set_xlabel("Elapsed time (s)")
        if figure_settings.view_mode == "intensity":
            self._refresh_intensity(series, figure_settings)
        else:
            for roi_id in list(self._lines):
                self._lines.pop(roi_id).remove()
            if figure_settings.view_mode == "second_derivative":
                self._draw_second_derivative(series, figure_settings)
            else:
                self._draw_fastest_change(series, figure_settings)
        self._axes.relim()
        self._axes.autoscale_view()
        if (not figure_settings.x_auto
                and figure_settings.view_mode != "fastest_change"):
            self._axes.set_xlim(figure_settings.x_min,
                                figure_settings.x_max)
        if not figure_settings.y_auto:
            self._axes.set_ylim(figure_settings.y_min,
                                figure_settings.y_max)
        self.draw_idle()

    def _refresh_intensity(self, series, figure_settings):
        self._axes.set_ylabel(
            PLOT_STAT_LABELS[self._model.session.plot_stat])
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
        if figure_settings.fit_method != "none":
            self._draw_fits(series, figure_settings)
        self._apply_legend(bool(self._lines)
                           and figure_settings.show_legend)

    def _draw_second_derivative(self, series, figure_settings):
        """One curve per ROI: the fitted model's d²y/dt² over the ROI's
        time span; the d² max/min checkboxes mark its extrema here."""
        self._axes.set_ylabel("d² of fit")
        if figure_settings.fit_method == "none":
            self._apply_legend(False)
            self._draw_hint("Select a fit method to view d²")
            return
        drew = False
        for roi_id, (name, elapsed, values) in series.items():
            roi = self._model.session.roi_by_id(roi_id)
            if roi is None:
                continue
            fit = fit_series(elapsed, values, figure_settings.fit_method)
            if fit is None:
                continue
            finite_t = np.asarray(elapsed, dtype=float)[
                np.isfinite(np.asarray(values, dtype=float))]
            dense = np.linspace(finite_t.min(), finite_t.max(), 200)
            d2 = np.asarray(fit.second_derivative(dense), dtype=float)
            if d2.shape != dense.shape:
                d2 = np.full_like(dense, float(d2))
            (curve,) = self._axes.plot(dense, d2, color=roi.style.color,
                                       label=name)
            self._fit_artists.append(curve)
            drew = True
            wanted = [key for key, enabled in
                      (("max", figure_settings.show_second_derivative_max),
                       ("min", figure_settings.show_second_derivative_min))
                      if enabled]
            if wanted:
                extrema = second_derivative_extrema(
                    fit, finite_t.min(), finite_t.max())
                for key in wanted:
                    if key not in extrema:
                        continue
                    t_star = extrema[key][0]
                    self._draw_extremum_marker(
                        t_star, float(fit.second_derivative(t_star)),
                        roi, figure_settings)
        self._apply_legend(drew and figure_settings.show_legend)

    def _draw_fastest_change(self, series, figure_settings):
        """Bar per ROI: seconds until the fitted curve changes fastest
        (max |dy/dt| — a sigmoid's inflection point). ROIs whose fit
        fails or whose speed is flat (linear) get no bar."""
        self._axes.set_ylabel("Time of fastest change (s)")
        self._axes.set_xlabel("ROI")
        self._apply_legend(False)
        if figure_settings.fit_method == "none":
            self._draw_hint("Select a fit method to view fastest change")
            return
        labels, times, colors = [], [], []
        for roi_id, (name, elapsed, values) in series.items():
            roi = self._model.session.roi_by_id(roi_id)
            if roi is None:
                continue
            fit = fit_series(elapsed, values, figure_settings.fit_method)
            if fit is None:
                continue
            finite_t = np.asarray(elapsed, dtype=float)[
                np.isfinite(np.asarray(values, dtype=float))]
            t_star = fastest_change_time(fit, finite_t.min(),
                                         finite_t.max())
            if t_star is None:
                continue
            labels.append(name)
            times.append(t_star)
            colors.append(roi.style.color)
        if not labels:
            self._draw_hint("No fastest-change times "
                            "(fits failed or rate is constant)")
            return
        positions = list(range(len(labels)))
        self._fit_artists.extend(
            self._axes.bar(positions, times, color=colors))
        self._axes.set_xticks(positions, labels)
        for x, t_star in zip(positions, times):
            self._fit_artists.append(self._axes.annotate(
                f"{t_star:.3g}", (x, t_star),
                textcoords="offset points", xytext=(0, 4),
                ha="center", fontsize="x-small"))

    def _apply_legend(self, wanted):
        if wanted:
            self._axes.legend(loc="best", fontsize="small")
        elif self._axes.get_legend() is not None:
            self._axes.get_legend().remove()

    def _draw_hint(self, message):
        self._fit_artists.append(self._axes.text(
            0.5, 0.5, message, transform=self._axes.transAxes,
            ha="center", va="center", color="gray"))

    def _draw_fits(self, series, figure_settings):
        """Dashed fit overlay + optional corner equation lines per ROI;
        series that cannot be fitted are silently skipped (the popup
        table is where failures are reported)."""
        equation_lines = []
        for roi_id, (name, elapsed, values) in series.items():
            roi = self._model.session.roi_by_id(roi_id)
            if roi is None:
                continue
            fit = fit_series(elapsed, values, figure_settings.fit_method)
            if fit is None:
                continue
            # fit_series requires >= 2 finite points, so never empty.
            finite_t = np.asarray(elapsed, dtype=float)[
                np.isfinite(np.asarray(values, dtype=float))]
            dense = np.linspace(finite_t.min(), finite_t.max(), 200)
            (overlay,) = self._axes.plot(
                dense, fit.predict(dense), linestyle="--", alpha=0.8,
                color=roi.style.color, label="_nolegend_")
            self._fit_artists.append(overlay)
            equation_lines.append(
                (roi.style.color,
                 f"{name}: {fit.equation} (R²={fit.r_squared:.3f})"))
            self._draw_extrema(fit, finite_t.min(), finite_t.max(),
                               roi, figure_settings)
        if figure_settings.show_fit_equations:
            for index, (color, text) in enumerate(equation_lines):
                self._fit_artists.append(self._axes.text(
                    0.02, 0.97 - 0.06 * index, text,
                    transform=self._axes.transAxes, va="top",
                    fontsize="x-small", color=color))

    def _draw_extrema(self, fit, t_start, t_end, roi, figure_settings):
        """Point (plus optional v/h line and coordinates) on the fitted
        curve where its second derivative peaks/troughs."""
        wanted = [key for key, enabled in
                  (("max", figure_settings.show_second_derivative_max),
                   ("min", figure_settings.show_second_derivative_min))
                  if enabled]
        if not wanted:
            return
        extrema = second_derivative_extrema(fit, t_start, t_end)
        for key in wanted:
            if key not in extrema:
                continue
            t_star, y_star = extrema[key]
            self._draw_extremum_marker(t_star, y_star, roi,
                                       figure_settings)

    def _draw_extremum_marker(self, t_star, y_star, roi,
                              figure_settings):
        """One d²-extremum marker at (t_star, y_star) — on the fitted
        curve in the intensity view, on the d² curve in the d² view."""
        (point,) = self._axes.plot(
            [t_star], [y_star], marker="o", linestyle="",
            color=roi.style.color, markeredgecolor="black",
            label="_nolegend_")
        self._fit_artists.append(point)
        if figure_settings.second_derivative_vline:
            self._fit_artists.append(self._axes.axvline(
                t_star, color=roi.style.color, linestyle=":",
                alpha=0.6))
        if figure_settings.second_derivative_hline:
            self._fit_artists.append(self._axes.axhline(
                y_star, color=roi.style.color, linestyle=":",
                alpha=0.6))
        if figure_settings.second_derivative_coords:
            self._fit_artists.append(self._axes.annotate(
                f"({t_star:.3g}, {y_star:.3g})", (t_star, y_star),
                textcoords="offset points", xytext=(6, 6),
                fontsize="x-small", color=roi.style.color))


def _save_figure(canvas):
    """Render the current figure at the session's export settings; the
    dialog defaults into the experiment's analysis folder."""
    session = roi_analysis_model.session
    default_dir = (str(analysis_directory(session.directory))
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

    canvas = Instance(RoiPlotCanvas)
    table = Instance(RoiStatsTable)
    _controls_ui = Any()
    _equations_ui = Any()
    _progress_label = Any()

    def create_contents(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        self.canvas = RoiPlotCanvas(roi_analysis_model)
        self.canvas.setMinimumSize(ROI_PLOT_CANVAS_MIN_WIDTH,
                                   ROI_PLOT_CANVAS_MIN_HEIGHT)
        layout.addWidget(NavigationToolbar2QT(self.canvas, widget))
        self._controls_ui = self._build_controls(widget)
        layout.addWidget(self._controls_ui.control)
        splitter = QSplitter(Qt.Orientation.Vertical, widget)
        splitter.addWidget(self.canvas)
        self.table = RoiStatsTable(roi_analysis_model, splitter)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self._progress_label = QLabel("", widget)
        layout.addWidget(self._progress_label)
        roi_analysis_model.observe(self._on_session_swapped, "session")
        roi_analysis_model.observe(self._on_save_plot, "save_plot_button")
        roi_analysis_model.observe(self._on_fit_equations,
                                   "fit_equations_button")
        roi_analysis_model.observe(self._on_progress_text_changed,
                                   "progress_text")
        # The pane may be resized below the content's minimum; past that
        # point scrollbars take over instead of the dock pane locking.
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _build_controls(self, parent):
        session = roi_analysis_model.session
        return _plot_controls_view.ui(
            context={"session": session, "figure": session.figure,
                     "model": roi_analysis_model},
            kind="subpanel", parent=parent)

    def _on_session_swapped(self, event):
        old_ui = self._controls_ui
        holder = old_ui.control.parentWidget()
        self._controls_ui = self._build_controls(holder)
        holder.layout().replaceWidget(old_ui.control,
                                      self._controls_ui.control)
        old_ui.dispose()

    def _on_save_plot(self, event):
        _save_figure(self.canvas)

    def _on_fit_equations(self, event):
        rows = fit_equation_rows(roi_analysis_model.session,
                                 roi_analysis_model.filtered_paths)
        if (self._equations_ui is not None
                and self._equations_ui.control is not None):
            self._equations_ui.info.object.rows = rows
            self._equations_ui.control.raise_()
            self._equations_ui.control.activateWindow()
            return
        self._equations_ui = FitEquationsTable(rows=rows).edit_traits(
            kind="live")

    def _on_progress_text_changed(self, event):
        self._progress_label.setText(event.new)

    def destroy(self):
        # Everything below was registered in create_contents, which a
        # constructed-but-never-shown pane never ran (pyface's own
        # destroy() guards its teardown the same way).
        if self.control is not None:
            self.canvas.detach()
            self.table.detach()
            self._controls_ui.dispose()
            if (self._equations_ui is not None
                    and self._equations_ui.control is not None):
                self._equations_ui.dispose()
            roi_analysis_model.observe(self._on_session_swapped, "session",
                                       remove=True)
            roi_analysis_model.observe(self._on_save_plot,
                                       "save_plot_button", remove=True)
            roi_analysis_model.observe(self._on_fit_equations,
                                       "fit_equations_button", remove=True)
            roi_analysis_model.observe(self._on_progress_text_changed,
                                       "progress_text", remove=True)
        super().destroy()
