import json

from traits.api import observe

from template_status_and_controls.base_controller import BaseStatusController
from microdrop_utils.dramatiq_pub_sub_helpers import publish_message
from microdrop_utils.traitsui_qt_helpers import stretch_group_layouts_horizontally
from logger.logger_service import get_logger

from .cameras.camera_settings import asi_camera_settings
from .consts import SET_LED, SET_LED_FREQUENCY, ALL_LEDS_OFF

logger = get_logger(__name__)


class FluorescenceControlsController(BaseStatusController):
    """Fluorescence LED controls controller — port of the standalone app's
    LED slots (on_light_button_click, update_br_/fl_ handlers).

    Live-command gating matches the original exactly: edits publish only
    while the light is on AND the edited set's mode is active ("br" edits in
    br mode, "fl" edits in fl mode; in dual mode edits are staged and the
    light toggle drives the brightfield set). Wavelength switches publish ONE
    exclusive set_led request — the backend runs the legacy off->on sequence
    atomically (two pub/sub messages would have no ordering guarantee).

    The standalone 0.5 s duplicate-command debounce is unnecessary here:
    trait observers only fire on actual value changes.
    """

    # ------------------------------------------------------------------ #
    # UI build hook                                                        #
    # ------------------------------------------------------------------ #
    def init(self, info):
        """Stretch the collapsible sections to the full pane width once the UI
        is built (TraitsUI otherwise left-hugs each group to its content)."""
        stretch_group_layouts_horizontally(info.ui.control)
        return super().init(info)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _publish(topic, payload):
        publish_message(message=json.dumps(payload), topic=topic)

    def _active_led_payload(self, exclusive=False):
        """The LED the light toggle drives: brightfield in br/dual mode
        (the original's abs/double branch), fluorescence in fl mode."""
        if self.model.mode == "fl":
            payload = {"led": self.model.fl_led_index, "duty": self.model.fl_intensity}
        else:
            payload = {"led": self.model.br_led_index, "duty": self.model.br_intensity}
        if exclusive:
            payload["exclusive"] = True
        return payload

    # ------------------------------------------------------------------ #
    # Controller Interface                                                 #
    # ------------------------------------------------------------------ #
    def br_frequency_setattr(self, info, object, traitname, value):
        return super().setattr(info, object, traitname, int(value))

    def fl_frequency_setattr(self, info, object, traitname, value):
        return super().setattr(info, object, traitname, int(value))

    # ------------------------------------------------------------------ #
    # Master light toggle                                                  #
    # ------------------------------------------------------------------ #
    @observe("model:light_on")
    def _light_toggled(self, event):
        if event.new:
            self._publish(SET_LED, self._active_led_payload())
        else:
            self._publish(ALL_LEDS_OFF, {})

    # ------------------------------------------------------------------ #
    # Brightfield set (live only in br mode with the light on)             #
    # ------------------------------------------------------------------ #
    def _br_live(self):
        return self.model.light_on and self.model.mode == "br"

    @observe("model:br_intensity")
    def _br_intensity_changed(self, event):
        if self._br_live():
            self._publish(SET_LED, {"led": self.model.br_led_index, "duty": event.new})

    @observe("model:br_frequency")
    def _br_frequency_changed(self, event):
        if self._br_live():
            self._publish(SET_LED_FREQUENCY,
                          {"led": self.model.br_led_index, "frequency": event.new})

    @observe("model:br_wavelength")
    def _br_wavelength_changed(self, event):
        if self._br_live():
            self._publish(SET_LED, self._active_led_payload(exclusive=True))

    # ------------------------------------------------------------------ #
    # Fluorescence set (live only in fl mode with the light on)            #
    # ------------------------------------------------------------------ #
    def _fl_live(self):
        return self.model.light_on and self.model.mode == "fl"

    @observe("model:fl_intensity")
    def _fl_intensity_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED, {"led": self.model.fl_led_index, "duty": event.new})

    @observe("model:fl_frequency")
    def _fl_frequency_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED_FREQUENCY,
                          {"led": self.model.fl_led_index, "frequency": event.new})

    @observe("model:fl_wavelength")
    def _fl_wavelength_changed(self, event):
        if self._fl_live():
            self._publish(SET_LED, self._active_led_payload(exclusive=True))

    # ------------------------------------------------------------------ #
    # Camera settings (per-mode, like the standalone UI's br_/fl_          #
    # exposure/gain): the CURRENT mode's pair is mirrored into the shared  #
    # ASI settings, which the running camera feed applies live. The pane   #
    # is the ONLY editor — the device viewer shows no settings row.        #
    # ------------------------------------------------------------------ #
    def _camera_mode_is_fl(self):
        return self.model.mode == "fl"

    @observe("model:mode")
    @observe("model:br_exposure")
    @observe("model:br_gain")
    @observe("model:fl_exposure")
    @observe("model:fl_gain")
    def _push_active_camera_settings(self, event):
        # The pane shows milliseconds; the camera takes microseconds.
        if self._camera_mode_is_fl():
            asi_camera_settings.exposure = int(self.model.fl_exposure * 1000)
            asi_camera_settings.gain = int(self.model.fl_gain)
        else:
            asi_camera_settings.exposure = int(self.model.br_exposure * 1000)
            asi_camera_settings.gain = int(self.model.br_gain)

    @observe("model:device_viewer_stream")
    def _push_device_viewer_stream(self, event):
        asi_camera_settings.device_viewer_stream = self.model.device_viewer_stream

    @observe("model:auto_exposure")
    @observe("model:auto_gain")
    def _push_auto_flags(self, event):
        asi_camera_settings.auto_exposure = self.model.auto_exposure
        asi_camera_settings.auto_gain = self.model.auto_gain
