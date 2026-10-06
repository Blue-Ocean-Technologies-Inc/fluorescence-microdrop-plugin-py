# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Construction-only shape test for `UnifiedView` (issue #6, Plan-B Task 5):
the mode selector + per-mode brightfield/fluorescence groups are gone,
replaced by a single params section plus a capture-chain table. Pure
traitsui object-graph walk — no Qt widget instantiation (that's Task 10).
"""

# Enthought library imports.
from traitsui.api import Group, Item, View

# Microdrop package imports.
from fluorescence_controls_ui.consts import LED_PROPORTION_TRAITS
from fluorescence_controls_ui.view import UnifiedView

# Microdrop utils imports.
from microdrop_utils.traitsui_qt_helpers import IconButtonEditor


def _item_names(node):
    """Recursively collect every `Item.name` under a View/Group node.

    `View.content` is a single top-level `Group`; a `Group`'s own
    `.content` is the list of `Item`/`Group` children TraitsUI actually
    iterates when laying the pane out.
    """
    if isinstance(node, Item):
        return [node.name]
    if isinstance(node, View):
        return _item_names(node.content)
    if isinstance(node, Group):
        names = []
        for child in node.content:
            names.extend(_item_names(child))
        return names
    return []


def _all_item_names():
    return _item_names(UnifiedView)


def test_no_deleted_mode_or_per_mode_item_names():
    names = _all_item_names()
    assert "mode" not in names
    assert not any(name.startswith("br_") for name in names)
    assert not any(name.startswith("fl_") for name in names)


def test_params_group_present():
    names = _all_item_names()
    for name in (
        "image_tag",
        "wavelength",
        "intensity",
        "frequency",
        "exposure",
        "auto_exposure",
        "gain",
        "auto_gain",
    ):
        assert name in names, f"{name!r} missing from view item names"


def test_chain_group_present():
    names = _all_item_names()
    assert "chain_rows" in names


def test_control_group_still_present():
    """Light/stream toggles survive the rework untouched."""
    names = _all_item_names()
    assert "light_on" in names
    assert "stream_active" in names
    assert "device_viewer_stream" in names


def test_status_group_still_present():
    names = _all_item_names()
    for name in ("connection_status_text", "board_id_text", "last_reading"):
        assert name in names


def test_chain_buttons_present():
    """Add / Run Capture buttons wired into the chain group."""
    names = _all_item_names()
    assert "add_capture_button" in names
    assert "run_capture_button" in names


def test_delete_button_present_in_chain_group():
    from fluorescence_controls_ui.view import UnifiedView

    assert "delete_capture_button" in _item_names(UnifiedView.content)


def test_run_column_is_a_glyph_not_a_checkbox():
    """Route-table parity: the Run column renders Material glyphs."""
    from fluorescence_controls_ui.view import RunColumn, chain_table_editor

    col = chain_table_editor.columns[1]
    assert isinstance(col, RunColumn)
    assert col.formatter(True) == "play_arrow"
    assert col.formatter(False) == "play_disabled"


def test_chain_table_has_right_click_delete_menu():
    from fluorescence_controls_ui.view import chain_table_editor

    actions = [
        item.action.action
        for group in chain_table_editor.menu.groups
        for item in group.items
    ]
    assert "delete_chain_row" in actions


def _find(node, name):
    """The first `Item` named ``name`` under a Group node, or None."""

    if isinstance(node, Item) and node.name == name:
        return node

    if isinstance(node, Group):
        for child in node.content:
            found = _find(child, name)

            if found is not None:
                return found

    return None


def test_capture_phase_toggles_present():
    names = _all_item_names()
    assert "capture_start" in names
    assert "capture_end" in names


def test_capture_phase_toggles_are_always_clickable():
    """No enabled_when guard: a disabled toggle renders grey even while on
    (the editor's :disabled style), and the sole lit phase must still be
    clickable to swap phases. The model holds the at-least-one-on rule."""
    from fluorescence_controls_ui.view import params_group

    assert _find(params_group, "capture_start").enabled_when == ""
    assert _find(params_group, "capture_end").enabled_when == ""


def test_camera_lead_time_item_sits_with_the_camera_params():
    from fluorescence_controls_ui.view import params_group

    item = _find(params_group, "camera_lead_time_ms")
    assert item is not None
    assert item.label == "Camera Lead Time (ms)"


def test_mix_preset_items_sit_under_the_mix_sliders():
    from fluorescence_controls_ui.view import multi_channel_group

    names = _item_names(multi_channel_group)

    for name in (
        "led_mix_preset_name",
        "save_led_mix_preset_button",
        "led_mix_preset",
        "delete_led_mix_preset_button",
    ):
        assert name in names, f"{name!r} missing from the Multi-Channel group"

    assert names.index("led_mix_preset_name") > names.index(LED_PROPORTION_TRAITS[-1])


def test_mix_preset_picker_lists_the_model_choices():
    from fluorescence_controls_ui.view import multi_channel_group

    item = _find(multi_channel_group, "led_mix_preset")

    assert item.editor.name == "led_mix_preset_choices"


def test_mix_preset_buttons_are_glyphs_gated_on_their_inputs():
    from fluorescence_controls_ui.view import multi_channel_group

    save = _find(multi_channel_group, "save_led_mix_preset_button")
    delete = _find(multi_channel_group, "delete_led_mix_preset_button")

    assert isinstance(save.editor, IconButtonEditor)
    assert save.editor.glyph == "add"
    assert save.enabled_when == "led_mix_preset_name.strip()"
    assert isinstance(delete.editor, IconButtonEditor)
    assert delete.editor.glyph == "remove"
    assert delete.enabled_when == "led_mix_preset"


def test_camera_lead_time_uses_the_frequency_range_shifting_slider():
    """Same default editor as Frequency: the `xslider` mode (traitsui's
    LargeRangeSliderEditor, whose arrows shift the slider's window)."""
    from fluorescence_controls_ui.model import FluorescenceStatusModel

    class_traits = FluorescenceStatusModel.class_traits()

    assert class_traits["frequency"].handler.mode == "xslider"
    assert class_traits["camera_lead_time_ms"].handler.mode == "xslider"
