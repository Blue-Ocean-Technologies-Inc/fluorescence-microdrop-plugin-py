# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Hardware-free tests for preference persistence: the control pane's
per-mode values survive a restart (the model two-way syncs with
FluorescencePreferences), and the light state never persists."""

# Enthought library imports.
from apptools.preferences.api import Preferences

# Microdrop package imports.
from fluorescence_controls_ui.consts import PERSISTED_CONTROL_TRAITS
from fluorescence_controls_ui.model import FluorescenceStatusModel
from fluorescence_controls_ui.preferences import FluorescencePreferences


def _prefs():
    return FluorescencePreferences(preferences=Preferences())  # in-memory


def test_every_persisted_trait_exists_on_model_and_preferences():
    helper = _prefs()
    control_model = FluorescenceStatusModel(preferences=helper)
    for trait in PERSISTED_CONTROL_TRAITS:
        assert control_model.trait(trait) is not None, trait
        assert helper.trait(trait) is not None, trait
    # The light always starts off — its state must never persist.
    assert "light_on" not in PERSISTED_CONTROL_TRAITS


def test_control_edits_restore_into_a_fresh_model():
    helper = _prefs()
    first = FluorescenceStatusModel(preferences=helper)
    first.gain = 123  # pushed to preferences live

    model = FluorescenceStatusModel(preferences=helper)  # "next session"
    assert model.gain == 123


def test_preference_edits_pull_into_a_live_control_model():
    helper = _prefs()
    model = FluorescenceStatusModel(preferences=helper)
    helper.frequency = 12345
    assert model.frequency == 12345
