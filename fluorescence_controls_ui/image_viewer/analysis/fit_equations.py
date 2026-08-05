"""Fit-equations popup: the equation being fitted, editable, above a
table of every ROI's fitted parameters — one column per parameter of
whatever model is in force. Typing an equation refits on the spot; one
that is neither a built-in nor already saved can be added to the
presets from here."""
import numpy as np
from traits.api import (
    Bool, Button, Float, HasTraits, Instance, Int, List, Str, observe,
)
from traitsui.api import (
    EnumEditor, HGroup, Item, Label, TabularEditor, UItem, View,
)
from traitsui.tabular_adapter import TabularAdapter

from .curve_fit import CUSTOM_METHOD, fit_series, trimmed_note
from .fit_expression import FitExpressionError, parse_expression
from .fit_presets import (
    add_preset, expression_for, fit_arguments, method_label,
    method_for_expression,
)
from .plot_series import derive_series

#: Column widths as fractions of the viewport; the parameters share
#: what the fixed columns leave, however many of them there are.
_NAME_WIDTH = 0.18
_R_SQUARED_WIDTH = 0.12
_RANGE_WIDTH = 0.16


class FitEquationRow(HasTraits):
    """One ROI's fit outcome: its fitted parameter values in the fit's
    own parameter order, plus how good that fit was."""

    roi_name = Str()
    #: Formatted parameter values, positionally matching the parameter
    #: columns; empty when the fit failed.
    values = List(Str)
    r_squared_text = Str()
    fit_range_text = Str()
    #: Why there are no values, shown under the first parameter.
    note = Str()


class _FitAdapter(TabularAdapter):
    """The parameter columns are rebuilt per fit, so their text comes
    from the row's own list by position rather than from a named trait
    per column."""

    can_edit = False

    #: How many of the middle columns are parameters.
    parameter_count = Int(0)

    #: Widths of the fixed columns, as fractions of the viewport. The
    #: parameter columns take the default share each, there being no
    #: knowing how many of them a typed equation will have.
    roi_name_width = Float(_NAME_WIDTH)
    r_squared_width = Float(_R_SQUARED_WIDTH)
    fit_range_width = Float(_RANGE_WIDTH)

    def get_text(self, object, trait, row, column):
        item = getattr(object, trait)[row]
        if column == 0:
            return item.roi_name
        if column == self.parameter_count + 1:
            return item.r_squared_text
        if column > self.parameter_count + 1:
            return item.fit_range_text
        index = column - 1
        if item.values:
            return item.values[index] if index < len(item.values) else ""
        # A failed fit says so once, under the first parameter, rather
        # than leaving a row of blanks that reads like zeros.
        return item.note if index == 0 else ""


def fit_rows(session, filtered_paths, presets):
    """(parameter names, rows) for the session's current fit over the
    filtered images. The names come from the first ROI that fitted:
    every ROI is fitted with the same model, so they all report the
    same parameters in the same order."""
    method, expression = fit_arguments(session.figure, presets)
    parameters, rows = [], []
    for roi_id, (name, elapsed, values) in derive_series(
            session, filtered_paths).items():
        fit = fit_series(elapsed, values, method,
                         session.figure.trim_poor_fit, expression)
        row = FitEquationRow(roi_name=name)
        if fit is None:
            row.note = ("no fit selected" if method == "none"
                        else "fit failed")
        else:
            if not parameters:
                parameters = list(fit.params)
            row.values = [f"{value:.4g}"
                          for value in fit.params.values()]
            row.r_squared_text = f"{fit.r_squared:.4f}"
            finite_t = np.asarray(elapsed, dtype=float)[
                np.isfinite(np.asarray(values, dtype=float))]
            row.fit_range_text = trimmed_note(
                fit, finite_t.max()).strip(" ()")
        rows.append(row)
    return parameters, rows


class PresetName(HasTraits):
    """Modal asking what to call the equation being saved."""

    name = Str()

    traits_view = View(Item("name", label="Preset name"),
                       title="Save fit equation",
                       buttons=["OK", "Cancel"],
                       kind="livemodal", width=280)


class FitEquationsTable(HasTraits):
    """View-model for the popup: the fit in force, editable, and one
    row per ROI. Live — changing the equation refits every ROI."""

    #: Set by the pane; both are read, never written, except for the
    #: figure's fit settings which this popup exists to change.
    session = Instance(HasTraits)
    model = Instance(HasTraits)
    filtered_paths = List(Str)

    rows = List(FitEquationRow)
    adapter = Instance(TabularAdapter)

    #: The equation as typed, and why it cannot be used ('' when fine).
    expression = Str()
    error = Str()

    add_preset_button = Button("Add to presets")
    can_add_preset = Bool(False)

    #: Set while one of the two-way observers below is writing the
    #: other's trait, so the dropdown and the field cannot chase each
    #: other around.
    _syncing = Bool(False)

    def _adapter_default(self):
        return _FitAdapter()

    def default_traits_view(self):
        # Built per instance: the TabularEditor holds its adapter by
        # value, and this popup's columns change with the fit.
        return View(
            HGroup(
                Item("object.session.figure.fit_method", label="Fit",
                     editor=EnumEditor(
                         name="object.model.fit_method_choices",
                         format_func=self._method_label)),
                UItem("add_preset_button",
                      enabled_when="can_add_preset",
                      tooltip="Save this equation as a preset you can "
                              "pick from the Fit list"),
            ),
            HGroup(
                Label("F(x) = "),
                UItem("expression", springy=True,
                      tooltip="Any equation in x — every other symbol "
                              "is a fitted parameter, e.g. "
                              "a + b*exp(-c*x)"),
            ),
            UItem("error", style="readonly",
                  visible_when="error != ''"),
            UItem("rows",
                  editor=TabularEditor(adapter=self.adapter,
                                       editable=False,
                                       stretch_last_section=False)),
            title="Fit equations", width=640, height=340,
            resizable=True)

    def _method_label(self, key):
        return method_label(key, self.model.fit_presets)

    # ------------------------------------------------------------------ #
    # Two-way sync: the dropdown fills the field, and editing the field  #
    # switches the method to whatever now matches it.                     #
    # ------------------------------------------------------------------ #
    @observe("session:figure:fit_method")
    def _on_method_changed(self, event):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.expression = expression_for(
                self.session.figure.fit_method, self.model.fit_presets,
                self.session.figure.custom_expression)
            self.error = ""
        finally:
            self._syncing = False
        self.refresh()

    @observe("expression")
    def _on_expression_changed(self, event):
        self._update_can_add()
        if self._syncing or not self.expression.strip():
            return
        try:
            parse_expression(self.expression)
        except FitExpressionError as error:
            # Say what is wrong and leave the previous fit standing:
            # every keystroke passes through here, and most of them are
            # halfway through an equation.
            self.error = str(error)
            return
        self.error = ""
        self._syncing = True
        try:
            figure = self.session.figure
            figure.custom_expression = self.expression
            figure.fit_method = (
                method_for_expression(self.expression,
                                      self.model.fit_presets)
                or CUSTOM_METHOD)
        finally:
            self._syncing = False
        self.refresh()

    def _update_can_add(self):
        text = self.expression.strip()
        self.can_add_preset = bool(text) and not method_for_expression(
            text, self.model.fit_presets) and _parses(text)

    @observe("add_preset_button")
    def _add_preset(self, event):
        entry = PresetName()
        if not entry.edit_traits().result or not entry.name.strip():
            return
        name = entry.name.strip()
        self.model.fit_presets = add_preset(
            list(self.model.fit_presets), name, self.expression.strip())
        self._syncing = True
        try:
            self.session.figure.fit_method = f"preset:{name}"
        finally:
            self._syncing = False
        self._update_can_add()

    # ------------------------------------------------------------------ #
    def refresh(self):
        """Refit every ROI and rebuild the table around the parameters
        the fit reports."""
        parameters, rows = fit_rows(self.session, self.filtered_paths,
                                    self.model.fit_presets)
        show_range = any(row.fit_range_text for row in rows)
        self.adapter.parameter_count = len(parameters)
        columns = [("ROI", "roi_name")]
        columns += [(name, f"p{index}")
                    for index, name in enumerate(parameters)]
        columns.append(("R²", "r_squared"))
        if show_range:
            columns.append(("Fitted to", "fit_range"))
        # The editor watches this list, so it is assigned last: the
        # parameter count must be in place before the headers are
        # rebuilt around it.
        self.adapter.columns = columns
        self.rows = rows


def _parses(text):
    try:
        parse_expression(text)
    except FitExpressionError:
        return False
    return True
