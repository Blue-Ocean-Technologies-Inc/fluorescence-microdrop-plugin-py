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
from traitsui.api import (
    EnumEditor, HGroup, Item, Label, RangeEditor, Tabbed, UItem,
    VGrid, VGroup, View,
)

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


def axes_tab():
    """The axes as a table: rows X and Y, columns Auto / Min / Max /
    Log. The row names the axis, so the Log toggle needs no axis in
    its label."""
    return VGroup(
        VGrid(
            Label(""), Label("Auto"), Label("Min"), Label("Max"),
            Label("Log"),
            Label("X"),
            UItem("figure.x_auto"),
            _axis_spin("figure.x_min", "x_auto"),
            _axis_spin("figure.x_max", "x_auto"),
            _toggle("figure.log_x", "Log"),
            Label("Y"),
            UItem("figure.y_auto"),
            _axis_spin("figure.y_min", "y_auto"),
            _axis_spin("figure.y_max", "y_auto"),
            _toggle("figure.log_y", "Log"),
            columns=5, show_labels=False,
        ),
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
    context = {"model": model, "session": model.session,
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
