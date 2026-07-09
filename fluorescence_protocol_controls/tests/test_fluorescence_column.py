"""Hardware-free tests for the fluorescence per-step protocol column:
the settings <-> column-value round trip, the summary cell, and the
handler's publishes (LED topics + GUI-thread camera mirror)."""
import json

import pytest

from fluorescence_controller.consts import (
    ALL_LEDS_OFF, LED_WAVELENGTHS, SET_LED, SET_LED_FREQUENCY,
)
from fluorescence_protocol_controls.consts import (
    FLUORESCENCE_COLUMN_ID, LIGHT_USED_SCRATCH_KEY,
)
from fluorescence_protocol_controls.protocol_columns import (
    fluorescence_column as column_module,
)
from fluorescence_protocol_controls.protocol_columns.fluorescence_column import (
    FluorescenceDialogView, FluorescenceStepHandler, make_fluorescence_column,
)
from fluorescence_protocol_controls.step_settings import (
    STEP_SETTING_TRAITS, FluorescenceStepSettings,
)


# --- settings <-> column value ---------------------------------------------

def test_round_trip_preserves_every_setting():
    settings = FluorescenceStepSettings(apply=True, mode="fl", light_on=True)
    settings.fl_wavelength = LED_WAVELENGTHS[1]
    settings.fl_intensity = 33
    value = settings.to_value()
    assert set(value) == set(STEP_SETTING_TRAITS)

    back = FluorescenceStepSettings.from_value(value)
    assert back.apply is True
    assert (back.mode, back.light_on) == ("fl", True)
    assert back.fl_wavelength == LED_WAVELENGTHS[1]
    assert back.fl_intensity == 33


def test_no_apply_stores_none_and_none_seeds_defaults():
    assert FluorescenceStepSettings(apply=False).to_value() is None
    settings = FluorescenceStepSettings.from_value(None)
    assert settings.apply is False


def test_invalid_stored_entry_is_skipped():
    value = FluorescenceStepSettings(apply=True).to_value()
    value["br_wavelength"] = "not-a-wavelength"    # stale protocol file
    settings = FluorescenceStepSettings.from_value(value)
    assert settings.br_wavelength == LED_WAVELENGTHS[0]


# --- summary cell ------------------------------------------------------------

def test_summary_cell_text():
    view = FluorescenceDialogView()
    assert view.format_display(None, None) == ""
    assert view.format_display(
        {"mode": "fl", "light_on": True}, None) == "fl · light on"


# --- handler ----------------------------------------------------------------

class _Ctx:
    """Just enough StepContext surface for on_pre_step."""
    class _Protocol:
        preview_mode = False
        scratch = None
    def __init__(self, preview=False):
        self.protocol = self._Protocol()
        self.protocol.preview_mode = preview
        self.protocol.scratch = {}


class _Row:
    pass


@pytest.fixture
def published(monkeypatch):
    calls = []
    monkeypatch.setattr(column_module, "publish_message",
                        lambda topic, message: calls.append((topic, message)))
    monkeypatch.setattr(column_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(column_module.GUI, "invoke_later",
                        lambda func, **kw: func(**kw))
    return calls


def test_light_on_publishes_frequency_then_exclusive_led(published):
    row = _Row()
    settings = FluorescenceStepSettings(apply=True, mode="fl", light_on=True)
    settings.fl_wavelength = LED_WAVELENGTHS[2]
    settings.fl_intensity, settings.fl_frequency = 25, 40000
    setattr(row, FLUORESCENCE_COLUMN_ID, settings.to_value())

    ctx = _Ctx()
    FluorescenceStepHandler().on_pre_step(row, ctx)

    topics = [topic for topic, _ in published]
    assert topics == [SET_LED_FREQUENCY, SET_LED]
    frequency_payload = json.loads(published[0][1])
    led_payload = json.loads(published[1][1])
    assert frequency_payload == {"led": 2, "frequency": 40000}
    assert led_payload == {"led": 2, "duty": 25, "exclusive": True}
    assert ctx.protocol.scratch[LIGHT_USED_SCRATCH_KEY] is True


def test_light_off_publishes_all_leds_off(published):
    row = _Row()
    setattr(row, FLUORESCENCE_COLUMN_ID,
            FluorescenceStepSettings(apply=True, light_on=False).to_value())
    FluorescenceStepHandler().on_pre_step(row, _Ctx())
    assert [topic for topic, _ in published] == [ALL_LEDS_OFF]


def test_none_value_and_preview_mode_publish_nothing(published):
    handler = FluorescenceStepHandler()
    row = _Row()
    setattr(row, FLUORESCENCE_COLUMN_ID, None)
    handler.on_pre_step(row, _Ctx())

    setattr(row, FLUORESCENCE_COLUMN_ID,
            FluorescenceStepSettings(apply=True, light_on=True).to_value())
    handler.on_pre_step(row, _Ctx(preview=True))
    assert published == []


def test_camera_settings_mirror_uses_active_mode_pair(published):
    from fluorescence_controls_ui.cameras.camera_settings import (
        asi_camera_settings,
    )
    row = _Row()
    settings = FluorescenceStepSettings(apply=True, mode="dual", light_on=False)
    settings.br_exposure, settings.br_gain = 12, 55    # dual runs on br pair
    setattr(row, FLUORESCENCE_COLUMN_ID, settings.to_value())
    FluorescenceStepHandler().on_pre_step(row, _Ctx())
    assert asi_camera_settings.exposure == 12_000      # ms -> us
    assert asi_camera_settings.gain == 55


def test_run_end_turns_lights_off_only_when_used(published):
    handler = FluorescenceStepHandler()

    class _ProtocolCtx:
        scratch = {}
    handler.on_post_protocol_end(_ProtocolCtx())
    assert published == []

    _ProtocolCtx.scratch = {LIGHT_USED_SCRATCH_KEY: True}
    handler.on_post_protocol_end(_ProtocolCtx())
    assert [topic for topic, _ in published] == [ALL_LEDS_OFF]


def test_factory_wires_column():
    column = make_fluorescence_column()
    assert column.model.col_id == FLUORESCENCE_COLUMN_ID
    assert column.handler.priority == 5    # before the capture bucket (10)
    assert callable(column.view.edit_dialog)
