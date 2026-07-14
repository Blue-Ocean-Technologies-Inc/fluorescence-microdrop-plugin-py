"""Hardware-free tests for the fluorescence per-step compound column:
the settings <-> stored-value round trip, the snapshot-on-check
interaction, the summary cell, and the handler's protocol publish +
ack wait."""
import json

import pytest

from fluorescence_controller.consts import (
    ALL_LEDS_OFF, FLUORESCENCE_APPLIED, LED_WAVELENGTHS,
    PROTOCOL_SET_FLUORESCENCE,
)
from fluorescence_controls_ui.cameras.camera_settings import (
    ADVANCED_CAMERA_TRAITS,
)
from fluorescence_protocol_controls.consts import (
    FLUORESCENCE_COMPOUND_BASE_ID, FLUORESCENCE_ON_COLUMN_ID,
    FLUORESCENCE_SETTINGS_COLUMN_ID, LED_STABILIZATION_S,
    STEP_SETTING_TRAITS,
)
from fluorescence_protocol_controls.protocol_columns import (
    fluorescence_column as column_module,
)
from fluorescence_protocol_controls.protocol_columns.fluorescence_column import (
    FluorescenceSnapshotView, FluorescenceStepHandler,
    make_fluorescence_column,
)
from fluorescence_protocol_controls.step_settings import (
    FluorescenceStepSettings,
)
from microdrop_utils import dramatiq_pub_sub_helpers


# --- settings <-> stored value ----------------------------------------------

def test_round_trip_preserves_every_setting():
    settings = FluorescenceStepSettings(apply=True, mode="fl", light_on=True)
    settings.fl_wavelength = LED_WAVELENGTHS[1]
    settings.fl_intensity = 33
    settings.advanced = {"binning": 2}
    value = settings.to_value()
    assert set(value) == set(STEP_SETTING_TRAITS) | {"advanced"}

    back = FluorescenceStepSettings.from_value(value)
    assert back.apply is True
    assert (back.mode, back.light_on) == ("fl", True)
    assert back.fl_wavelength == LED_WAVELENGTHS[1]
    assert back.fl_intensity == 33
    assert back.advanced == {"binning": 2}


def test_no_apply_stores_none_and_none_seeds_defaults():
    assert FluorescenceStepSettings(apply=False).to_value() is None
    settings = FluorescenceStepSettings.from_value(None)
    assert settings.apply is False


def test_invalid_stored_entry_is_skipped():
    value = FluorescenceStepSettings(apply=True).to_value()
    value["br_wavelength"] = "not-a-wavelength"    # stale protocol file
    value["advanced"] = {"not_a_setting": 1, "offset": 5}
    settings = FluorescenceStepSettings.from_value(value)
    assert settings.br_wavelength == LED_WAVELENGTHS[0]
    assert settings.advanced == {"offset": 5}


# --- snapshot-on-check interaction ------------------------------------------

class _RecordingModel:
    """Just enough compound-model surface for on_interact."""
    def __init__(self):
        self.values = {}

    def set_value(self, row, field_id, value):
        self.values[field_id] = value
        return True


def test_check_snapshots_live_controls_and_uncheck_keeps_them():
    from fluorescence_controls_ui.live_state import fluorescence_live_state
    fluorescence_live_state.light_on = True
    try:
        handler = FluorescenceStepHandler()
        model = _RecordingModel()
        assert handler.on_interact(_Row(), model,
                                   FLUORESCENCE_ON_COLUMN_ID, True)
        assert model.values[FLUORESCENCE_ON_COLUMN_ID] is True
        snapshot = model.values[FLUORESCENCE_SETTINGS_COLUMN_ID]
        assert snapshot["light_on"] is True
        assert set(snapshot["advanced"]) == set(ADVANCED_CAMERA_TRAITS)

        # Unchecking flips only the Bool; the stored snapshot survives.
        assert handler.on_interact(_Row(), model,
                                   FLUORESCENCE_ON_COLUMN_ID, False)
        assert model.values[FLUORESCENCE_ON_COLUMN_ID] is False
        assert model.values[FLUORESCENCE_SETTINGS_COLUMN_ID] == snapshot
    finally:
        fluorescence_live_state.light_on = False


# --- summary cell ------------------------------------------------------------

def test_summary_cell_text():
    view = FluorescenceSnapshotView()
    assert view.format_display(None, None) == ""
    assert view.format_display(
        {"mode": "fl", "light_on": True}, None) == "fl · light on"
    assert list(view.depends_on_row_traits) == [
        FLUORESCENCE_SETTINGS_COLUMN_ID]


# --- handler ----------------------------------------------------------------

class _Ctx:
    """Just enough StepContext surface for on_pre_step."""
    class _Protocol:
        preview_mode = False

    def __init__(self, preview=False):
        self.protocol = self._Protocol()
        self.protocol.preview_mode = preview
        self.waited = []

    def wait_for(self, topic, timeout=None):
        self.waited.append((topic, timeout))


class _Row:
    pass


def _make_row(checked, settings):
    row = _Row()
    setattr(row, FLUORESCENCE_ON_COLUMN_ID, checked)
    setattr(row, FLUORESCENCE_SETTINGS_COLUMN_ID,
            settings.to_value() if settings is not None else None)
    return row


@pytest.fixture
def published(monkeypatch):
    calls = []

    def record(message, topic, **kw):
        calls.append((topic, message))

    # ALL_LEDS_OFF goes through the module's publish_message; the LED
    # snapshot goes through the validated publisher, whose publish lands
    # on the pub/sub helper module's publish_message.
    monkeypatch.setattr(column_module, "publish_message", record)
    monkeypatch.setattr(dramatiq_pub_sub_helpers, "publish_message", record)
    monkeypatch.setattr(column_module.GUI, "invoke_later",
                        lambda func, *args, **kw: func(*args, **kw))
    return calls


def test_light_on_publishes_protocol_set_and_waits_for_ack(published):
    settings = FluorescenceStepSettings(apply=True, mode="fl", light_on=True)
    settings.fl_wavelength = LED_WAVELENGTHS[2]
    settings.fl_intensity, settings.fl_frequency = 25, 40000
    row = _make_row(True, settings)

    ctx = _Ctx()
    FluorescenceStepHandler().on_pre_step(row, ctx)

    assert [topic for topic, _ in published] == [PROTOCOL_SET_FLUORESCENCE]
    payload = json.loads(published[0][1])
    assert payload == {"light_on": True, "led": 2, "duty": 25,
                       "frequency": 40000, "settle_s": LED_STABILIZATION_S}
    assert ctx.waited == [(FLUORESCENCE_APPLIED, 5.0)]


def test_light_off_still_applies_and_waits_for_ack(published):
    row = _make_row(True, FluorescenceStepSettings(apply=True, light_on=False))
    ctx = _Ctx()
    FluorescenceStepHandler().on_pre_step(row, ctx)
    assert [topic for topic, _ in published] == [PROTOCOL_SET_FLUORESCENCE]
    assert json.loads(published[0][1])["light_on"] is False
    assert ctx.waited == [(FLUORESCENCE_APPLIED, 5.0)]


def test_unchecked_missing_snapshot_and_preview_publish_nothing(published):
    handler = FluorescenceStepHandler()

    # Unchecked: the stored snapshot (kept from an earlier check) is ignored.
    ctx = _Ctx()
    handler.on_pre_step(
        _make_row(False, FluorescenceStepSettings(apply=True, light_on=True)),
        ctx)

    # Checked but no snapshot stored (stale/hand-edited protocol file).
    handler.on_pre_step(_make_row(True, None), ctx)

    # Preview mode: no hardware side effects.
    preview_ctx = _Ctx(preview=True)
    handler.on_pre_step(
        _make_row(True, FluorescenceStepSettings(apply=True, light_on=True)),
        preview_ctx)

    assert published == []
    assert ctx.waited == [] and preview_ctx.waited == []


def test_camera_settings_mirror_uses_active_mode_pair(published):
    from fluorescence_controls_ui.cameras.camera_settings import (
        asi_camera_settings,
    )
    settings = FluorescenceStepSettings(apply=True, mode="dual",
                                        light_on=False)
    settings.br_exposure, settings.br_gain = 12, 55    # dual runs on br pair
    settings.auto_exposure = True
    FluorescenceStepHandler().on_pre_step(_make_row(True, settings), _Ctx())
    assert asi_camera_settings.exposure == 12_000      # ms -> us
    assert asi_camera_settings.gain == 55
    assert asi_camera_settings.auto_exposure is True


def test_pre_step_reflects_snapshot_into_pane(published):
    from fluorescence_controls_ui.live_state import fluorescence_live_state
    reflected = []

    def capture(event):
        reflected.append(event.new)

    fluorescence_live_state.observe(capture, "protocol_step_settings_applied")
    try:
        settings = FluorescenceStepSettings(apply=True, light_on=True)
        FluorescenceStepHandler().on_pre_step(_make_row(True, settings),
                                              _Ctx())
        assert reflected and reflected[-1] == settings.to_value()
    finally:
        fluorescence_live_state.observe(
            capture, "protocol_step_settings_applied", remove=True)


def test_run_end_always_turns_lights_off_and_mirrors_pane(published):
    """Unconditional: the operator may enter the run with the light on
    manually, which leaves no run-time trace."""
    from fluorescence_controls_ui.live_state import fluorescence_live_state
    reflected = []

    def capture(event):
        reflected.append(event.new)

    fluorescence_live_state.observe(capture, "protocol_step_settings_applied")
    try:
        FluorescenceStepHandler().on_post_protocol_end(object())
        assert [topic for topic, _ in published] == [ALL_LEDS_OFF]
        assert reflected == [{"light_on": False}]
    finally:
        fluorescence_live_state.observe(
            capture, "protocol_step_settings_applied", remove=True)


def test_factory_wires_compound_column():
    column = make_fluorescence_column()
    assert column.model.base_id == FLUORESCENCE_COMPOUND_BASE_ID
    assert [spec.field_id for spec in column.model.field_specs()] == [
        FLUORESCENCE_ON_COLUMN_ID, FLUORESCENCE_SETTINGS_COLUMN_ID]
    assert column.handler.priority == 5    # before the capture bucket (10)
    assert column.handler.wait_for_topics == [FLUORESCENCE_APPLIED]
    assert isinstance(
        column.view.cell_view_for_field(FLUORESCENCE_SETTINGS_COLUMN_ID),
        FluorescenceSnapshotView)
