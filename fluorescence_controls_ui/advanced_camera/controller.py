"""Controller for the advanced camera controls pane: mirrors every model
edit into the shared ASI camera settings, which the running feed forwards
to the capture thread (applied between frames) — and copies the camera
capabilities the feed reports back into the model, so the pane's
dropdowns narrow to what the connected camera supports."""
from traits.api import observe
from traitsui.api import Controller

from ..cameras.camera_settings import (
    ADVANCED_CAMERA_TRAITS, CAMERA_CAPS_TRAITS, asi_camera_settings,
)
from ..cameras.consts import AUTO_MAX_EXPOSURE_UNIT_US

#: Singleton traits this controller copies INTO the model as they change
#: (the reverse direction of the setting pushes).
CAMERA_FEEDBACK_TRAITS = CAMERA_CAPS_TRAITS + ("camera_temperature",)


class AdvancedCameraController(Controller):
    """Mediates between the pane's model and ``asi_camera_settings``."""

    def traits_init(self):
        # Controller assigns self.model AFTER HasTraits init, so only the
        # singleton observers register here; the feedback copy waits for it.
        asi_camera_settings.observe(
            self._on_camera_feedback_changed,
            ",".join(CAMERA_FEEDBACK_TRAITS))

    @observe("model")
    def _copy_camera_feedback_to_model(self, event):
        if self.model is None:
            return
        for name in CAMERA_FEEDBACK_TRAITS:
            setattr(self.model, name, getattr(asi_camera_settings, name))

    def remove_camera_caps_observers(self):
        """Detach from the module-level settings singleton — required for
        runtime hot unload of the pane (the dock pane calls this)."""
        asi_camera_settings.observe(
            self._on_camera_feedback_changed,
            ",".join(CAMERA_FEEDBACK_TRAITS), remove=True)

    def _on_camera_feedback_changed(self, event):
        if self.model is not None:
            setattr(self.model, event.name, event.new)

    @observe(f"model:[{','.join(ADVANCED_CAMERA_TRAITS)}]")
    def _push_advanced_camera_settings(self, event):
        setattr(asi_camera_settings, event.name, event.new)

    @observe("model:auto_max_exposure_value")
    @observe("model:auto_max_exposure_unit")
    def _push_auto_max_exposure(self, event):
        """The pane edits a value + ms/s unit pair; the shared settings
        (and the capture thread) take plain microseconds."""
        asi_camera_settings.auto_max_exposure = (
            self.model.auto_max_exposure_value
            * AUTO_MAX_EXPOSURE_UNIT_US[self.model.auto_max_exposure_unit])

    def push_all_advanced_camera_settings(self):
        """Mirror the full (restored) model state into the shared settings
        once at pane creation — the observers only fire on later edits."""
        asi_camera_settings.trait_set(**{
            name: getattr(self.model, name)
            for name in ADVANCED_CAMERA_TRAITS})
        self._push_auto_max_exposure(None)
