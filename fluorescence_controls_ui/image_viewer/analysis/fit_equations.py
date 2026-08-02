"""Fit-equations popup: a read-only table of each ROI's fitted
equation for the session's current fit method over the filtered
images. Rows are recomputed when the popup is opened or its button
re-clicked — not live."""
from traits.api import HasTraits, List, Str
from traitsui.api import Item, TabularEditor, View
from traitsui.tabular_adapter import TabularAdapter

from .curve_fit import FIT_LABELS, fit_series
from .plot_series import derive_series


class FitEquationRow(HasTraits):
    """One ROI's fit outcome."""

    roi_name = Str()
    method_label = Str()
    equation = Str()
    r_squared_text = Str()


class _FitEquationAdapter(TabularAdapter):
    columns = [("ROI", "roi_name"), ("Method", "method_label"),
               ("Equation", "equation"), ("R²", "r_squared_text")]
    can_edit = False


class FitEquationsTable(HasTraits):
    """View-model for the popup; rows are replaced wholesale."""

    rows = List(FitEquationRow)

    traits_view = View(
        Item("rows", show_label=False,
             editor=TabularEditor(adapter=_FitEquationAdapter(),
                                  editable=False)),
        title="Fit equations", width=560, height=280, resizable=True)


def fit_equation_rows(session, filtered_paths):
    """Rows for the session's current fit method over the filtered
    images ("fit failed" covers both non-convergence and too few
    points — fit_series does not distinguish)."""
    method = session.figure.fit_method
    rows = []
    for roi_id, (name, elapsed, values) in derive_series(
            session, filtered_paths).items():
        fit = fit_series(elapsed, values, method)
        rows.append(FitEquationRow(
            roi_name=name,
            method_label=FIT_LABELS[method],
            equation=(fit.equation if fit is not None
                      else "no fit selected" if method == "none"
                      else "fit failed"),
            r_squared_text=(f"{fit.r_squared:.4f}"
                            if fit is not None else "")))
    return rows
