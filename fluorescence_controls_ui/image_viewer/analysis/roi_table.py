"""Per-ROI table under the intensity plot: editable name (drives the
plot legend and CSV columns), style editors (color, line, marker,
size), and live stats for the image currently shown in the viewer —
including the instant result right after drawing an ROI. A pure
observer of the shared analysis model, mutating it only from Qt editor
signals (GUI thread). Rebuilds (row count, editors, cell identities) on
structure/style change; value-refreshes (stat cells rewritten in place)
on stats/current-image change — both scheduled onto the next event-loop
turn so nothing mutates the table from inside the emitting Qt signal or
traits notification."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDoubleSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem,
)

from .plot_series import stat_value

#: Value columns after the editors, shown for the current image.
_STAT_COLUMNS = ("mean", "bg_corrected", "median", "min", "max",
                 "count")
_HEADERS = ("Name", "Color", "Line", "Marker", "Size") + _STAT_COLUMNS
_LINE_CHOICES = ("solid", "dashed", "dotted", "dashdot")
_MARKER_CHOICES = ("none", ".", "o", "s", "^", "x")

#: Row count/editors/cell identities change — triggers a full rebuild.
_TABLE_STRUCTURE = ("session, session:rois.items, "
                    "session:rois:items:name, "
                    "session:rois:items:style:color")
#: Only the stat-cell text can be stale — triggers a values-only
#: refresh. The two geometry clauses close a staleness edge: editing an
#: ROI back to an already-cached geometry never bumps stats_revision.
_TABLE_VALUES = ("session:stats_revision, current_image_path, "
                 "session:rois:items:geometry, "
                 "session:rois:items:overrides.items")


class RoiStatsTable(QTableWidget):
    """One row per ROI; editors write straight into the session."""

    def __init__(self, model, parent=None):
        super().__init__(0, len(_HEADERS), parent)
        self._model = model
        self._rebuilding = False
        self._pending = None   # None | "rebuild" | "values"
        self.setHorizontalHeaderLabels(_HEADERS)
        self.verticalHeader().setVisible(False)
        self.itemChanged.connect(self._on_item_changed)
        model.observe(self._on_structure_changed, _TABLE_STRUCTURE)
        model.observe(self._on_values_changed, _TABLE_VALUES)
        self._rebuild()

    def detach(self):
        self._model.observe(self._on_structure_changed, _TABLE_STRUCTURE,
                            remove=True)
        self._model.observe(self._on_values_changed, _TABLE_VALUES,
                            remove=True)

    def _on_structure_changed(self, event):
        self._schedule("rebuild")

    def _on_values_changed(self, event):
        self._schedule("values")

    def _schedule(self, kind):
        """Coalesce onto the next event-loop turn; a pending rebuild
        subsumes a pending values-only refresh."""
        if self._pending == "rebuild":
            return
        if kind == "rebuild" or self._pending is None:
            already_scheduled = self._pending is not None
            self._pending = kind
            if not already_scheduled:
                QTimer.singleShot(0, self._run_pending)

    def _run_pending(self):
        pending, self._pending = self._pending, None
        if pending == "rebuild":
            self._rebuild()
        elif pending == "values":
            self._refresh_values()

    def _rebuild(self):
        self._rebuilding = True
        session = self._model.session
        rois = list(session.rois)
        self.setRowCount(len(rois))
        current = self._model.current_image_path
        stat_cache = {}
        for row, roi in enumerate(rois):
            name_item = QTableWidgetItem(roi.name)
            name_item.setData(Qt.ItemDataRole.UserRole, roi.roi_id)
            self.setItem(row, 0, name_item)
            self.setCellWidget(row, 1, self._color_button(roi))
            self.setCellWidget(
                row, 2, self._combo(_LINE_CHOICES, roi.style.line_style,
                                    lambda value, roi=roi:
                                    roi.style.trait_set(line_style=value)))
            self.setCellWidget(
                row, 3, self._combo(_MARKER_CHOICES, roi.style.marker,
                                    lambda value, roi=roi:
                                    roi.style.trait_set(marker=value)))
            self.setCellWidget(row, 4, self._size_spin(roi))
            stats = (session.stats.get(
                session.cache_key(current, roi, stat_cache))
                if current else None)
            for column, stat in enumerate(_STAT_COLUMNS,
                                          start=len(_HEADERS)
                                          - len(_STAT_COLUMNS)):
                value = stat_value(stats, stat)
                text = "" if value != value else f"{value:.1f}"
                value_item = QTableWidgetItem(text)
                value_item.setFlags(value_item.flags()
                                    & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(row, column, value_item)
        self._rebuilding = False

    def _refresh_values(self):
        """Rewrite the read-only stat cells in place — no editors or
        row identities touched, so this never deletes a widget the user
        is mid-interaction with."""
        self._rebuilding = True
        session = self._model.session
        rois = list(session.rois)
        current = self._model.current_image_path
        stat_cache = {}
        for row, roi in enumerate(rois):
            if row >= self.rowCount():
                break
            stats = (session.stats.get(
                session.cache_key(current, roi, stat_cache))
                if current else None)
            for column, stat in enumerate(_STAT_COLUMNS,
                                          start=len(_HEADERS)
                                          - len(_STAT_COLUMNS)):
                value = stat_value(stats, stat)
                text = "" if value != value else f"{value:.1f}"
                item = self.item(row, column)
                if item is not None:
                    item.setText(text)
        self._rebuilding = False

    def _on_item_changed(self, item):
        if self._rebuilding or item.column() != 0:
            return
        roi = self._model.session.roi_by_id(
            item.data(Qt.ItemDataRole.UserRole))
        if roi is not None and item.text().strip():
            roi.name = item.text().strip()

    def _color_button(self, roi):
        button = QPushButton(self)
        button.setStyleSheet(
            f"background-color: {roi.style.color};")
        button.clicked.connect(lambda _=False, roi=roi, button=button:
                               self._pick_color(roi, button))
        return button

    def _pick_color(self, roi, button):
        color = QColorDialog.getColor(QColor(roi.style.color), self)
        if color.isValid():
            roi.style.color = color.name()
            button.setStyleSheet(f"background-color: {color.name()};")

    def _combo(self, choices, current, setter):
        combo = QComboBox(self)
        combo.addItems(choices)
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(setter)
        return combo

    def _size_spin(self, roi):
        spin = QDoubleSpinBox(self)
        spin.setRange(1.0, 30.0)
        spin.setValue(roi.style.marker_size)
        spin.valueChanged.connect(
            lambda value, roi=roi:
            roi.style.trait_set(marker_size=value))
        return spin
