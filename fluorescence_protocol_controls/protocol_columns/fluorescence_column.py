"""Fluorescence compound column — per-step LED + camera state.

Two coupled cells share one model + one handler (the PPT-11 compound
framework):
  * fluorescence_on       (Bool) — apply this step's fluorescence state,
    or leave it untouched
  * fluorescence_settings (dict) — the snapshot of the live controls

Device-viewer semantics: arrange the LIVE fluorescence controls (mode,
light, LED sets, camera exposure/gain/auto, advanced camera settings),
then CHECK the step's fluorescence cell — the check grabs the controls
into the settings cell. Unchecking leaves the fluorescence state
untouched at run time (the last snapshot stays stored for display;
re-checking re-grabs the current controls). While the checked step stays
SELECTED, the pane live-tracks it: any pane edit re-snapshots into the
step, and selecting a checked step loads its snapshot back into the pane
(the controls-UI sync built on the tree's row_selected / set_cell topics).

At run time the handler mirrors the snapshot's camera state into the
shared ASI settings, reflects the snapshot into the controls pane (a
passive mirror during a run), publishes the LED state to the backend,
and blocks until the backend acks that the light is applied AND settled
— so the capture/record bucket (priority 10) only fires once the camera
truly sees the final light.
"""
from pyface.gui import GUI

from traits.api import Any, Bool, List, Str

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from logger.logger_service import get_logger

from fluorescence_controller.consts import ALL_LEDS_OFF, FLUORESCENCE_APPLIED
from fluorescence_controller.datamodels import (
    protocol_set_fluorescence_publisher,
)
from fluorescence_controls_ui.cameras.camera_settings import (
    asi_camera_settings,
)
from fluorescence_controls_ui.live_state import fluorescence_live_state
from pluggable_protocol_tree.interfaces.i_compound_column import FieldSpec
from pluggable_protocol_tree.models.compound_column import (
    BaseCompoundColumnHandler, BaseCompoundColumnModel, CompoundColumn,
    DictCompoundColumnView,
)
from pluggable_protocol_tree.views.columns.base import BaseColumnView
from pluggable_protocol_tree.views.columns.checkbox import CheckboxColumnView

from ..consts import (
    FLUORESCENCE_COMPOUND_BASE_ID, FLUORESCENCE_ON_COLUMN_ID,
    FLUORESCENCE_SETTINGS_COLUMN_ID, LED_STABILIZATION_S,
)
from ..step_settings import FluorescenceStepSettings

logger = get_logger(__name__)


class FluorescenceCompoundModel(BaseCompoundColumnModel):
    """Two coupled fields; base_id 'fluorescence' appears as the compound
    id on each field's JSON column entry. The settings dict is JSON-native,
    so the default serialize/deserialize identity applies."""
    base_id = FLUORESCENCE_COMPOUND_BASE_ID

    def field_specs(self):
        return [
            FieldSpec(FLUORESCENCE_ON_COLUMN_ID, "Fluorescence", False),
            FieldSpec(FLUORESCENCE_SETTINGS_COLUMN_ID,
                      "Fluorescence Settings", None),
        ]

    def trait_for_field(self, field_id):
        if field_id == FLUORESCENCE_ON_COLUMN_ID:
            return Bool(False)
        if field_id == FLUORESCENCE_SETTINGS_COLUMN_ID:
            return Any(None)
        raise KeyError(field_id)


class FluorescenceSnapshotView(BaseColumnView):
    """Read-only summary of the stored snapshot ('fl · light on')."""

    #: The checkbox interaction writes a fresh snapshot straight to the
    #: row trait (bypassing setData), so declare the dependency for the
    #: tree model's per-row repaint wiring.
    depends_on_row_traits = List(Str,
                                 value=[FLUORESCENCE_SETTINGS_COLUMN_ID])

    def format_display(self, value, row):
        if not value:
            return ""
        light = "light on" if value.get("light_on") else "light off"
        return f"{value.get('mode', 'br')} · {light}"

    def create_editor(self, parent, context):
        return None   # display-only; the pane + checkbox own the edits


class FluorescenceStepHandler(BaseCompoundColumnHandler):
    """Snapshots the live controls into the step on check; replays them
    with a backend ack at run time.

    Priority 5 — one bucket EARLIER than capture/record/video (10), so
    the LED + camera state is applied and settled before a Step Start
    capture fires. The backend owns the settle and acks only afterwards
    (magnet backend pattern); the camera settings are mirrored to the
    shared ASI settings on the GUI thread BEFORE the LED round trip, so
    the running feed converges on them during the ack wait.
    """
    priority = 5
    wait_for_topics = [FLUORESCENCE_APPLIED]
    default_ack_time_s = 5.0

    def on_interact(self, row, model, field_id, value):
        """Checking the fluorescence cell grabs the CURRENT fluorescence
        controls into the settings cell; unchecking flips the Bool only,
        so the step leaves the fluorescence state untouched (the last
        snapshot stays stored for display)."""
        if field_id == FLUORESCENCE_ON_COLUMN_ID:
            if value:
                model.set_value(
                    row, FLUORESCENCE_SETTINGS_COLUMN_ID,
                    FluorescenceStepSettings.snapshot_current().to_value())
            return model.set_value(row, field_id, bool(value))
        return super().on_interact(row, model, field_id, value)

    def on_pre_step(self, row, ctx):
        # Preview mode: no hardware side effects (mirrors magnet/capture).
        if getattr(ctx.protocol, "preview_mode", False):
            return
        if not getattr(row, FLUORESCENCE_ON_COLUMN_ID, False):
            return
        stored_value = getattr(row, FLUORESCENCE_SETTINGS_COLUMN_ID, None)
        settings = FluorescenceStepSettings.from_value(stored_value)
        if not settings.apply:
            logger.warning("Fluorescence step is checked but stores no "
                           "settings snapshot; leaving state untouched")
            return

        self._apply_camera_settings(settings)

        # Reflect the step's settings into the controls pane — during a
        # run the pane is a passive mirror (its hardware publishes are
        # gated), so the operator always sees what the protocol applied.
        GUI.invoke_later(setattr, fluorescence_live_state,
                         "protocol_step_settings_applied", dict(stored_value))

        # The light drives the brightfield set outside fl mode (the
        # pane's dual-mode semantics).
        fl_mode = settings.mode == "fl"
        protocol_set_fluorescence_publisher.publish(
            light_on=settings.light_on,
            led=settings.fl_led_index if fl_mode else settings.br_led_index,
            duty=settings.fl_intensity if fl_mode else settings.br_intensity,
            frequency=settings.fl_frequency if fl_mode
            else settings.br_frequency,
            settle_s=LED_STABILIZATION_S,
        )

        # Block until the backend confirms the LEDs are applied AND
        # settled — the capture bucket then sees a stable image. The
        # status timers freeze during the wait (ack accounting). No ack
        # within ack_time_s fails the step: the backend withholds the ack
        # on hardware errors (magnet error contract).
        if self.ack_time_s > 0:
            ctx.wait_for(FLUORESCENCE_APPLIED, timeout=self.ack_time_s)

    @staticmethod
    def _apply_camera_settings(settings):
        """Mirror the snapshot's camera state into the shared ASI settings
        ON THE GUI THREAD (the executor runs on its own thread; the
        settings singleton and the feed's observers live with the GUI).
        The pane shows milliseconds; the camera takes microseconds. In
        dual mode the camera runs on the brightfield pair."""
        fl_mode = settings.mode == "fl"
        exposure_ms = settings.fl_exposure if fl_mode else settings.br_exposure
        gain = settings.fl_gain if fl_mode else settings.br_gain
        GUI.invoke_later(
            asi_camera_settings.trait_set,
            exposure=int(exposure_ms * 1000), gain=int(gain),
            auto_exposure=settings.auto_exposure,
            auto_gain=settings.auto_gain,
            **settings.advanced)

    def on_post_protocol_end(self, ctx):
        """Lights out at the end of every run — unconditional, because the
        operator may have entered the run with the light on manually, or
        every step's snapshot may hold light_on False (neither case leaves
        a run-time trace, and a lit LED must never outlive the run).
        Preview runs have no hardware side effects to clean up."""
        if getattr(ctx, "preview_mode", False):
            return
        publish_message(topic=ALL_LEDS_OFF, message="")
        # Partial snapshot: the pane's light toggle mirrors the off.
        GUI.invoke_later(setattr, fluorescence_live_state,
                         "protocol_step_settings_applied",
                         {"light_on": False})


def make_fluorescence_column():
    """Factory — a fresh fluorescence per-step compound column."""
    return CompoundColumn(
        model=FluorescenceCompoundModel(),
        view=DictCompoundColumnView(cell_views={
            FLUORESCENCE_ON_COLUMN_ID: CheckboxColumnView(),
            FLUORESCENCE_SETTINGS_COLUMN_ID: FluorescenceSnapshotView(),
        }),
        handler=FluorescenceStepHandler(),
    )
