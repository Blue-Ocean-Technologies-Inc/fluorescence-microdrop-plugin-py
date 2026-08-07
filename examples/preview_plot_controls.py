"""Preview mockup of the ROI Intensities control panel, standalone.

The tabbed layout chosen in review, over the real analysis model so
every enabled_when / visible_when behaves as it would in the app — but
view only: nothing here touches plot_pane, and closing the window
discards everything.

Structure:

- The top row is always visible: what is plotted (View, Plot) and the
  save button.
- **Axes** is a table — rows X and Y, columns Auto / Min / Max / Log —
  so the two axes read as the pair they are and "Log" needs no axis in
  its name.
- **Fit** holds two collapsible groups: Method (the fit dropdown, Trim
  tail, Equations, the ƒ table) and Advanced metrics (the d² markers
  and their dressing).
- **Cleanup** is the outlier test, the smoothing, and the value
  rewrites (Normalize, Subtract first, Bg ref).
- **Export** carries DPI and Format on their own rows; the save button
  itself stays on the top row, where it is always reachable.

Run (from src/fluorescence-microdrop-plugin-py):
    pixi run --manifest-path ../../pyproject.toml \\
        python examples/preview_plot_controls.py

``--shots <dir>`` renders a PNG per tab offscreen instead of opening
a window.
"""
import argparse
import os
import sys

from pyface.qt.QtWidgets import QApplication
from traits.api import Bool, HasTraits
from pyface.qt.QtWidgets import QDoubleSpinBox
from traitsui.api import (
    BasicEditorFactory, EnumEditor, HGroup, Item, Label, RangeEditor,
    Tabbed, UItem, VGroup, View,
)
from traitsui.qt.editor import Editor as QtEditor

from microdrop_style.helpers import style_app
from microdrop_style.icons.icons import ICON_FUNCTION, ICON_SAVE
from microdrop_utils.traitsui_qt_helpers import (
    DoubleSpinBoxEditor, IconButtonEditor, IconToggleEditor,
    InPlaceToggleEditor,
)

from fluorescence_controls_ui.image_viewer.analysis.consts import (
    BUTTER_CUTOFF_BOUNDS, BUTTER_ORDER_BOUNDS,
    OUTLIER_THRESHOLD_BOUNDS_MAD, OUTLIER_WINDOW_BOUNDS_PTS,
    SAVGOL_ORDER_BOUNDS, SAVGOL_WINDOW_BOUNDS_PTS, VIEW_MODE_LABELS,
    VIEW_MODES,
)
from fluorescence_controls_ui.image_viewer.analysis.plot_pane import (
    PLOT_STAT_LABELS, _fit_method_label,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    PLOT_STATS, RoiAnalysisModel,
)

#: Fixed pixel widths, so nothing stretches to fill the row: a value
#: spinner, a small parameter spinner, and a dropdown.
VALUE_SPIN_W = -78
PARAM_SPIN_W = -58
DROPDOWN_W = -130

#: Axis-limit spin boxes: wide enough for any intensity the cameras
#: produce, stepping by a whole count.
AXIS_LIMIT_BOUNDS = (-1e9, 1e9)


class PanelSections(HasTraits):
    """Which of the Fit tab's groups are open — the sidebar's collapse
    flags. In the real pane these would persist with the figure
    settings."""

    show_method = Bool(True)
    show_metrics = Bool(True)


def section(flag, label, *content):
    """A collapsible section: the image viewer sidebar's chevron
    header over a body that folds away with it."""
    return VGroup(
        HGroup(UItem(f"panel.{flag}", editor=IconToggleEditor()),
               Label(label)),
        VGroup(*content, visible_when=f"panel.{flag}"),
    )


def _axis_spin(name, auto_flag):
    return UItem(name, width=VALUE_SPIN_W,
                 editor=DoubleSpinBoxEditor(low=AXIS_LIMIT_BOUNDS[0],
                                            high=AXIS_LIMIT_BOUNDS[1],
                                            decimals=1, step=1.0),
                 enabled_when=f"not figure.{auto_flag}")


def _spin(name, label, bounds, width=PARAM_SPIN_W, enabled_when="",
          visible_when="", tooltip=""):
    return Item(name, label=label, width=width,
                editor=RangeEditor(low=bounds[0], high=bounds[1],
                                   mode="spinner", auto_set=True),
                enabled_when=enabled_when, visible_when=visible_when,
                tooltip=tooltip)


def _toggle(name, label, enabled_when="", tooltip=""):
    return UItem(name, editor=InPlaceToggleEditor(on_label=label,
                                                  off_label=label),
                 enabled_when=enabled_when, tooltip=tooltip)


# ------------------------------------------------------------------ #
# The pieces.                                                         #
# ------------------------------------------------------------------ #
def top_row():
    """Always visible: what is plotted, and the save button."""
    return HGroup(
        Item("figure.view_mode", label="View", width=DROPDOWN_W,
             editor=EnumEditor(values=list(VIEW_MODES),
                               format_func=VIEW_MODE_LABELS.get)),
        Item("session.plot_stat", label="Plot", width=DROPDOWN_W,
             editor=EnumEditor(values=list(PLOT_STATS),
                               format_func=PLOT_STAT_LABELS.get)),
        UItem("model.save_plot_button", editor=IconButtonEditor(
            glyph=ICON_SAVE,
            tooltip="Save the plot at the Export tab's DPI and "
                    "format")),
    )


class _AxesGridEditor(QtEditor):
    """The axes as a real Qt grid: rows X and Y under centred Auto /
    Min / Max / Log headers, with uniform column spacing — the
    alignment TraitsUI's VGrid cannot do, since it lays nested groups
    out as rows of their own.

    Bound to the FigureSettings object (via any of its traits); the
    six axis traits are wired by hand and unhooked on dispose."""

    #: (axis label, auto trait, min trait, max trait, log trait)
    ROWS = (("X", "x_auto", "x_min", "x_max", "log_x"),
            ("Y", "y_auto", "y_min", "y_max", "log_y"))
    HEADERS = ("", "Auto", "Min", "Max", "Log")

    def init(self, parent):
        from pyface.qt.QtCore import Qt
        from pyface.qt.QtWidgets import (
            QCheckBox, QGridLayout, QLabel, QPushButton, QWidget,
        )

        figure = self.object
        self.control = QWidget()
        grid = QGridLayout(self.control)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for column, title in enumerate(self.HEADERS):
            label = QLabel(title)
            grid.addWidget(label, 0, column, Qt.AlignHCenter)
        self._widgets = []
        for row, (axis, auto, low, high, log) in enumerate(self.ROWS,
                                                          start=1):
            grid.addWidget(QLabel(axis), row, 0, Qt.AlignHCenter)
            check = QCheckBox()
            check.setChecked(getattr(figure, auto))
            check.toggled.connect(
                lambda on, name=auto: setattr(figure, name, on))
            grid.addWidget(check, row, 1, Qt.AlignHCenter)
            for column, name in ((2, low), (3, high)):
                spin = QDoubleSpinBox()
                spin.setRange(*AXIS_LIMIT_BOUNDS)
                spin.setDecimals(1)
                spin.setFixedWidth(-VALUE_SPIN_W)
                spin.setValue(getattr(figure, name))
                spin.setEnabled(not getattr(figure, auto))
                spin.valueChanged.connect(
                    lambda value, name=name: setattr(figure, name,
                                                     value))
                grid.addWidget(spin, row, column, Qt.AlignHCenter)
                self._widgets.append((auto, spin))
            button = QPushButton("Log")
            button.setCheckable(True)
            button.setChecked(getattr(figure, log))
            button.setMaximumWidth(56)
            button.toggled.connect(
                lambda on, name=log: setattr(figure, name, on))
            grid.addWidget(button, row, 4, Qt.AlignHCenter)
        grid.setColumnStretch(len(self.HEADERS), 1)
        figure.observe(self._on_auto_changed, "x_auto, y_auto")

    def _on_auto_changed(self, event):
        # Min/Max grey out while their axis autoscales.
        for auto, spin in self._widgets:
            spin.setEnabled(not getattr(self.object, auto))

    def update_editor(self):
        """The traits are wired directly in init."""

    def dispose(self):
        self.object.observe(self._on_auto_changed, "x_auto, y_auto",
                            remove=True)
        super().dispose()


class AxesGridEditor(BasicEditorFactory):
    klass = _AxesGridEditor


def axes_tab():
    """The axes table, bound through any one figure trait — the editor
    reaches its siblings through the object."""
    return VGroup(
        UItem("figure.x_auto", editor=AxesGridEditor()),
        label="Axes",
    )


def fit_tab():
    return VGroup(
        section("show_method", "Method", HGroup(
            UItem("figure.fit_method",
                 width=DROPDOWN_W,
                 editor=EnumEditor(name="model.fit_method_choices",
                                   format_func=_fit_method_label)),
            _toggle("figure.trim_poor_fit", "Trim tail",
                    enabled_when="figure.fit_method != 'none'"),
            _toggle("figure.show_fit_equations", "Equations",
                    enabled_when="figure.fit_method != 'none'"),
            UItem("model.fit_equations_button",
                  editor=IconButtonEditor(
                      glyph=ICON_FUNCTION,
                      tooltip="Fitted parameters per ROI")),
        )),
        section("show_metrics", "Advanced metrics", HGroup(
            _toggle("figure.show_second_derivative_max", "d² max",
                    enabled_when="figure.fit_method != 'none'"),
            _toggle("figure.show_second_derivative_min", "d² min",
                    enabled_when="figure.fit_method != 'none'"),
            _toggle("figure.second_derivative_vline", "V-line",
                    enabled_when="figure.show_second_derivative_max "
                                 "or figure.show_second_derivative_min"),
            _toggle("figure.second_derivative_hline", "H-line",
                    enabled_when="figure.show_second_derivative_max "
                                 "or figure.show_second_derivative_min"),
            _toggle("figure.second_derivative_coords", "Coords",
                    enabled_when="figure.show_second_derivative_max "
                                 "or figure.show_second_derivative_min"),
        )),
        label="Fit",
    )


def cleanup_tab():
    return VGroup(
        HGroup(
            _toggle("figure.remove_outliers", "Outliers"),
            _spin("figure.outlier_threshold", "MADs",
                  OUTLIER_THRESHOLD_BOUNDS_MAD,
                  enabled_when="figure.remove_outliers"),
            _spin("figure.outlier_window", "win",
                  OUTLIER_WINDOW_BOUNDS_PTS,
                  enabled_when="figure.remove_outliers"),
        ),
        HGroup(
            Item("figure.smooth_method", label="Smooth",
                 width=DROPDOWN_W),
            _spin("figure.savgol_window", "win",
                  SAVGOL_WINDOW_BOUNDS_PTS,
                  visible_when="figure.smooth_method == 'savgol'"),
            _spin("figure.savgol_order", "order", SAVGOL_ORDER_BOUNDS,
                  visible_when="figure.smooth_method == 'savgol'"),
            _spin("figure.butter_order", "order", BUTTER_ORDER_BOUNDS,
                  visible_when="figure.smooth_method == 'butterworth'"),
            _spin("figure.butter_cutoff", "cutoff",
                  BUTTER_CUTOFF_BOUNDS,
                  visible_when="figure.smooth_method == 'butterworth'"),
        ),
        HGroup(
            _toggle("figure.normalize", "Normalize"),
            _toggle("figure.subtract_first", "Subtract first"),
            _toggle("figure.subtract_background_ref", "Bg ref"),
        ),
        label="Cleanup",
    )


def export_tab():
    """DPI and Format on their own rows; the save button lives on the
    top row rather than here, so saving never needs a tab switch."""
    return VGroup(
        HGroup(Item("figure.export_dpi", label="DPI",
                    width=PARAM_SPIN_W)),
        HGroup(Item("figure.export_format", label="Format",
                    width=PARAM_SPIN_W)),
        label="Export",
    )


def build_view():
    return View(
        VGroup(
            top_row(),
            Tabbed(axes_tab(), fit_tab(), cleanup_tab(),
                   export_tab()),
        ),
        title="ROI Intensities controls — tabbed", resizable=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", metavar="DIR",
                        help="render PNGs offscreen instead of showing")
    arguments = parser.parse_args()
    if arguments.shots:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    # The icon-font glyphs on the save/equations buttons need the
    # Material Symbols font, which the app normally loads at startup.
    style_app(app)

    model = RoiAnalysisModel()
    # "object" must exist: a Spring is an Item named "spring", and
    # TraitsUI resolves an unqualified item against context["object"].
    context = {"object": model, "model": model,
               "session": model.session,
               "figure": model.session.figure,
               "panel": PanelSections()}
    ui = build_view().ui(context=context, kind="live")
    if arguments.shots:
        from pathlib import Path
        from pyface.qt.QtWidgets import QTabWidget

        out = Path(arguments.shots)
        out.mkdir(parents=True, exist_ok=True)
        ui.control.show()
        app.processEvents()
        tabs = ui.control.findChild(QTabWidget)
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            app.processEvents()
            name = tabs.tabText(index).lower().replace(" ", "_")
            ui.control.grab().save(str(out / f"tab_{name}.png"))
            print(f"tab {tabs.tabText(index)}: "
                  f"{ui.control.width()}x{ui.control.height()} "
                  f"-> tab_{name}.png")
        ui.dispose()
        return 0
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
