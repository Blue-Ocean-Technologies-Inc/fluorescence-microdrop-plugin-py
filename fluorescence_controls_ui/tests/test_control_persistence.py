"""Hardware-free tests for preference persistence: the control pane's
per-mode values and the image viewer's display window survive a restart
(the models two-way sync with FluorescencePreferences), and the light
state never persists."""
from apptools.preferences.api import Preferences

from fluorescence_controls_ui.consts import (
    PERSISTED_CONTROL_TRAITS, PERSISTED_VIEWER_TRAITS,
)
from fluorescence_controls_ui.image_viewer.model import (
    FluorescenceImageViewerModel,
)
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences


def _prefs():
    return FluorescencePreferences(preferences=Preferences())   # in-memory


def test_every_persisted_trait_exists_on_model_and_preferences():
    helper = _prefs()
    control_model = FluorescenceStatusModel(preferences=helper)
    for trait in PERSISTED_CONTROL_TRAITS:
        assert control_model.trait(trait) is not None, trait
        assert helper.trait(trait) is not None, trait
    viewer_model = FluorescenceImageViewerModel(preferences=helper)
    for model_trait, preference_trait in PERSISTED_VIEWER_TRAITS.items():
        assert viewer_model.trait(model_trait) is not None, model_trait
        assert helper.trait(preference_trait) is not None, preference_trait
    # The light always starts off — its state must never persist.
    assert "light_on" not in PERSISTED_CONTROL_TRAITS


def test_control_edits_restore_into_a_fresh_model():
    helper = _prefs()
    first = FluorescenceStatusModel(preferences=helper)
    first.gain = 123                               # pushed to preferences live

    model = FluorescenceStatusModel(preferences=helper)   # "next session"
    assert model.gain == 123


def test_preference_edits_pull_into_a_live_control_model():
    helper = _prefs()
    model = FluorescenceStatusModel(preferences=helper)
    helper.frequency = 12345
    assert model.frequency == 12345


def test_viewer_window_round_trip():
    helper = _prefs()
    first = FluorescenceImageViewerModel(preferences=helper)
    first.auto_contrast = False
    first.window_max = 3200                    # max first: bounds the min
    first.window_min = 400

    model = FluorescenceImageViewerModel(preferences=helper)
    assert model.auto_contrast is False
    assert (model.window_min, model.window_max) == (400, 3200)
