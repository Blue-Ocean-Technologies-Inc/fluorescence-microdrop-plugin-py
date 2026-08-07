"""Preview mockups of the ROI Intensities control panel, standalone.

Candidate layouts over the real analysis model, so every enabled_when
/ visible_when behaves as it would in the app — but view only: nothing
here touches plot_pane, and closing the window discards everything.

Shared structure, per review:

- The top row is always visible: what is plotted (View, Plot) and the
  export controls (DPI, Format, save).
- Axes puts X and Y on their own rows, with the display transforms
  under them — Log X / Log Y first, then Normalize / Subtract first /
  Bg ref.
- Fit is two groups: Method (the fit dropdown, Trim tail, Equations,
  the ƒ table) and Advanced metrics (the d² markers and dressing).
- Cleanup is the outlier test and the smoothing.

Variants:

- ``a`` one column of collapsible sections (the image viewer sidebar's
        chevron headers).
- ``b`` tabs: Axes / Fit / Cleanup, the Fit tab holding the two
        chevron groups.
- ``c`` two columns of the same sections — widest, for comparison.

Run (from src/fluorescence-microdrop-plugin-py):
    pixi run --manifest-path ../../pyproject.toml \\
        python examples/preview_plot_controls.py a|b|c|all

``--shots <dir>`` renders each variant to a PNG offscreen instead of
opening windows.
"""
import argparse
import os
import sys

from pyface.qt.QtWidgets import QApplication
from traits.api import Bool, HasTraits
from traitsui.api import (
    EnumEditor, HGroup, Item, Label, RangeEditor, Tabbed, UItem,
    VGroup, View,
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
    """Which sections are open — the sidebar's collapse flags, for
    this panel. In the real pane these would persist with the figure
    settings."""

    show_axes = Bool(True)
    show_method = Bool(True)
    show_metrics = Bool(True)
    show_cleanup = Bool(True)


def section(flag, label, *content):
    """A collapsible section: the image viewer sidebar's chevron
    header over a body that folds away with it."""
    return VGroup(
        HGroup(UItem(f"panel.{flag}", editor=IconToggleEditor()),
               Label(label)),
        VGroup(*content, visible_when=f"panel.{flag}"),
    )


def _axis_spin(name, label, auto_flag):
    return Item(name, label=label, width=VALUE_SPIN_W,
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
# The sections, shared by every variant.                              #
# ------------------------------------------------------------------ #
def top_row():
    """Always visible: what is plotted, and how it exports."""
    return HGroup(
        Item("figure.view_mode", label="View", width=DROPDOWN_W,
             editor=EnumEditor(values=list(VIEW_MODES),
                               format_func=VIEW_MODE_LABELS.get)),
        Item("session.plot_stat", label="Plot", width=DROPDOWN_W,
             editor=EnumEditor(values=list(PLOT_STATS),
                               format_func=PLOT_STAT_LABELS.get)),
        Item("figure.export_dpi", label="DPI", width=PARAM_SPIN_W),
        Item("figure.export_format", label="Format",
             width=PARAM_SPIN_W),
        UItem("model.save_plot_button", editor=IconButtonEditor(
            glyph=ICON_SAVE, tooltip="Save the plot")),
    )


def axes_group():
    """X and Y on their own rows, the display transforms under them:
    the log scales first, then the value rewrites."""
    return VGroup(
        HGroup(
            Item("figure.x_auto", label="X auto"),
            _axis_spin("figure.x_min", "min", "x_auto"),
            _axis_spin("figure.x_max", "max", "x_auto"),
        ),
        HGroup(
            Item("figure.y_auto", label="Y auto"),
            _axis_spin("figure.y_min", "min", "y_auto"),
            _axis_spin("figure.y_max", "max", "y_auto"),
        ),
        HGroup(
            _toggle("figure.log_x", "Log X"),
            _toggle("figure.log_y", "Log Y"),
        ),
        HGroup(
            _toggle("figure.normalize", "Normalize"),
            _toggle("figure.subtract_first", "Subtract first"),
            _toggle("figure.subtract_background_ref", "Bg ref"),
        ),
    )


def method_group():
    return HGroup(
        Item("figure.fit_method", label="Method", width=DROPDOWN_W,
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
    )


def metrics_group():
    return HGroup(
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
    )


def cleanup_group():
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
    )


# ------------------------------------------------------------------ #
# The variants.                                                       #
# ------------------------------------------------------------------ #
def variant_a():
    """One column of collapsible sections."""
    return View(
        VGroup(
            top_row(),
            section("show_axes", "Axes", axes_group()),
            section("show_method", "Method", method_group()),
            section("show_metrics", "Advanced metrics",
                    metrics_group()),
            section("show_cleanup", "Cleanup", cleanup_group()),
        ),
        title="A — collapsible sections", resizable=True)


def variant_b():
    """The top row over tabs; the Fit tab holds the two groups."""
    return View(
        VGroup(
            top_row(),
            Tabbed(
                VGroup(axes_group(), label="Axes"),
                VGroup(
                    section("show_method", "Method", method_group()),
                    section("show_metrics", "Advanced metrics",
                            metrics_group()),
                    label="Fit",
                ),
                VGroup(cleanup_group(), label="Cleanup"),
            ),
        ),
        title="B — tabbed", resizable=True)


def variant_c():
    """Two side-by-side columns of the same sections."""
    return View(
        VGroup(
            top_row(),
            HGroup(
                VGroup(section("show_axes", "Axes", axes_group())),
                VGroup(
                    section("show_method", "Method", method_group()),
                    section("show_metrics", "Advanced metrics",
                            metrics_group()),
                    section("show_cleanup", "Cleanup",
                            cleanup_group()),
                ),
            ),
        ),
        title="C — two columns", resizable=True)


VARIANTS = {"a": variant_a, "b": variant_b, "c": variant_c}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", nargs="?", default="all",
                        choices=[*VARIANTS, "all"])
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
    wanted = (list(VARIANTS) if arguments.variant == "all"
              else [arguments.variant])
    uis = [VARIANTS[key]().ui(context=context, kind="live")
           for key in wanted]
    if arguments.shots:
        from pathlib import Path
        out = Path(arguments.shots)
        out.mkdir(parents=True, exist_ok=True)
        for key, ui in zip(wanted, uis):
            ui.control.show()
            app.processEvents()
            ui.control.grab().save(str(out / f"controls_{key}.png"))
            size = ui.control.size()
            print(f"variant {key}: {size.width()}x{size.height()} "
                  f"-> controls_{key}.png")
            ui.dispose()
        return 0
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
