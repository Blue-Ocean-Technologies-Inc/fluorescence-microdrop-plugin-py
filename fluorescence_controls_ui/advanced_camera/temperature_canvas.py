"""Matplotlib canvas for the Temp tab: sensor temperature over time.

Same construction as the heater plots pane: a QTimer samples the Qt-free
model on its own cadence, the Line2D artist is created once and updated
with set_data, and the timer pauses while the widget is hidden.
"""
import os

os.environ.setdefault("QT_API", "pyside6")
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtCore import QTimer

#: Redraw cadence — matches the capture thread's temperature poll.
TEMPERATURE_PLOT_UPDATE_INTERVAL_MS = 2000


class TemperatureCanvas(FigureCanvasQTAgg):
    """Rolling sensor-temperature chart fed from the pane model's
    ``temperature_history``."""

    def __init__(self, model):
        self._figure = Figure(figsize=(3, 2), tight_layout=True)
        super().__init__(self._figure)
        self._model = model
        self._axes = self._figure.add_subplot(111)
        self._axes.set_xlabel("Time (s)")
        self._axes.set_ylabel("Temperature (\N{DEGREE SIGN}C)")
        self._axes.grid(True, alpha=0.3)
        (self._line,) = self._axes.plot([], [])
        self._plotted_count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(TEMPERATURE_PLOT_UPDATE_INTERVAL_MS)

    def showEvent(self, event):
        self._timer.start(TEMPERATURE_PLOT_UPDATE_INTERVAL_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _refresh(self):
        history = list(self._model.temperature_history)
        if len(history) == self._plotted_count:
            return
        self._plotted_count = len(history)
        self._line.set_data([point[0] for point in history],
                            [point[1] for point in history])
        self._axes.relim()
        self._axes.autoscale_view()
        self.draw_idle()


def temperature_canvas_factory(parent, editor):
    """TraitsUI CustomEditor factory: the editor's object is the model."""
    return TemperatureCanvas(editor.object)
