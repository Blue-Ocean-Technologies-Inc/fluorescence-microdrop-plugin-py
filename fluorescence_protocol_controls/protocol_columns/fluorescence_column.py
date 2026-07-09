"""Fluorescence column — per-step LED + camera state.

The cell shows a compact summary ('' when the step changes nothing);
editing opens the full fluorescence controls panel as a dialog (the
protocol tree's dialog-editing view support), so every pane knob — mode,
light, per-mode wavelength/intensity/frequency/exposure/gain — can be
set per step. The stored value is a plain dict (or None), so it rides
protocol JSON untouched.

At run time the handler applies the state at step start, one priority
bucket BEFORE the capture/record columns, so a Step Start capture sees
the settled light and exposure.
"""
import json
import time

from pyface.gui import GUI
from pyface.qt.QtCore import Qt

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from fluorescence_controller.consts import (
    ALL_LEDS_OFF, SET_LED, SET_LED_FREQUENCY,
)
from fluorescence_controls_ui.cameras.camera_settings import (
    asi_camera_settings,
)
from pluggable_protocol_tree.models.column import (
    BaseColumnHandler, BaseColumnModel, Column,
)
from pluggable_protocol_tree.views.columns.base import BaseColumnView
from pluggable_protocol_tree.views.delegate import DIALOG_CANCELLED

from ..consts import (
    FLUORESCENCE_COLUMN_ID, LED_STABILIZATION_S, LIGHT_USED_SCRATCH_KEY,
)
from ..step_settings import FluorescenceStepSettings, step_settings_view

logger = get_logger(__name__)


class FluorescenceStepModel(BaseColumnModel):
    """Dict of per-step settings (STEP_SETTING_TRAITS keys), or None =
    the step leaves the fluorescence state untouched. JSON-native, so
    the default serialize/deserialize identity applies."""


class FluorescenceDialogView(BaseColumnView):
    """Summary cell; editing opens the controls panel as a dialog."""

    def format_display(self, value, row):
        if not value:
            return ""
        light = "light on" if value.get("light_on") else "light off"
        return f"{value.get('mode', 'br')} · {light}"

    def get_flags(self, row):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def create_editor(self, parent, context):
        return None   # dialog-edited: see edit_dialog

    def edit_dialog(self, parent, row):
        settings = FluorescenceStepSettings.from_value(
            self.model.get_value(row))
        ui = settings.edit_traits(view=step_settings_view, parent=parent,
                                  kind="livemodal")
        if ui.result:
            return settings.to_value()
        return DIALOG_CANCELLED


class FluorescenceStepHandler(BaseColumnHandler):
    """Applies the row's fluorescence state at step start.

    Priority 5 — one bucket EARLIER than capture/record/video (10), so
    the LED + camera state is published and settled before a Step Start
    capture fires. Fire-and-forget to the board topics (the same
    requests the controls pane publishes); camera exposure/gain go into
    the shared asi_camera_settings on the GUI thread (the running ASI
    feed applies them live).
    """
    priority = 5

    def on_pre_step(self, row, ctx):
        # Preview mode: no hardware side effects (mirrors magnet/capture).
        if getattr(ctx.protocol, "preview_mode", False):
            return
        settings = FluorescenceStepSettings.from_value(
            getattr(row, FLUORESCENCE_COLUMN_ID, None))
        if not settings.apply:
            return

        self._apply_camera_settings(settings)

        if settings.light_on:
            # The light drives the brightfield set outside fl mode (the
            # pane's dual-mode semantics). Frequency first so the LED
            # lights at the right PWM; exclusive = atomic off->on, since
            # the previously-lit LED is unknown between steps.
            fl_mode = settings.mode == "fl"
            led = settings.fl_led_index if fl_mode else settings.br_led_index
            publish_message(topic=SET_LED_FREQUENCY, message=json.dumps({
                "led": led,
                "frequency": settings.fl_frequency if fl_mode
                else settings.br_frequency,
            }))
            publish_message(topic=SET_LED, message=json.dumps({
                "led": led,
                "duty": settings.fl_intensity if fl_mode
                else settings.br_intensity,
                "exclusive": True,
            }))
            ctx.protocol.scratch[LIGHT_USED_SCRATCH_KEY] = True
        else:
            publish_message(topic=ALL_LEDS_OFF, message="")

        # Let the light/exposure settle before the capture bucket fires
        # (the standalone waited its led_stabilization_time the same way).
        time.sleep(LED_STABILIZATION_S)

    @staticmethod
    def _apply_camera_settings(settings):
        """Mirror the active mode's exposure/gain into the shared ASI
        settings ON THE GUI THREAD (the executor runs on its own thread;
        the settings singleton and the feed's observers live with the
        GUI). The pane shows milliseconds; the camera takes microseconds.
        In dual mode the camera runs on the brightfield pair."""
        fl_mode = settings.mode == "fl"
        exposure_ms = settings.fl_exposure if fl_mode else settings.br_exposure
        gain = settings.fl_gain if fl_mode else settings.br_gain
        GUI.invoke_later(asi_camera_settings.trait_set,
                         exposure=exposure_ms * 1000, gain=gain)

    def on_post_protocol_end(self, ctx):
        """Lights out at the end of the run if any step lit one."""
        scratch = getattr(ctx, "scratch", None)
        if scratch and scratch.get(LIGHT_USED_SCRATCH_KEY):
            publish_message(topic=ALL_LEDS_OFF, message="")


def make_fluorescence_column():
    """Factory — a fresh fluorescence per-step settings column."""
    return Column(
        model=FluorescenceStepModel(
            col_id=FLUORESCENCE_COLUMN_ID, col_name="Fluorescence",
            default_value=None,
        ),
        view=FluorescenceDialogView(),
        handler=FluorescenceStepHandler(),
    )
