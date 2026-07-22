"""Construction-only shape test for `UnifiedView` (issue #6, Plan-B Task 5):
the mode selector + per-mode brightfield/fluorescence groups are gone,
replaced by a single params section plus a capture-chain table. Pure
traitsui object-graph walk — no Qt widget instantiation (that's Task 10).
"""
from traitsui.api import Group, Item, View

from fluorescence_controls_ui.view import UnifiedView


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
    for name in ("image_tag", "wavelength", "intensity", "frequency",
                 "exposure", "auto_exposure", "gain", "auto_gain"):
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
    actions = [item.action.action
               for group in chain_table_editor.menu.groups
               for item in group.items]
    assert "delete_chain_row" in actions


def test_capture_phase_toggles_present_with_last_one_on_guards():
    names = _all_item_names()
    assert "capture_start" in names
    assert "capture_end" in names


def test_capture_phase_toggles_cannot_switch_off_the_last_phase():
    """Each toggle disables exactly when it is the sole phase on, so it
    can always be turned on but never switched off last."""
    from fluorescence_controls_ui.view import params_group

    def _find(node, name):
        from traitsui.api import Group, Item
        if isinstance(node, Item) and node.name == name:
            return node
        if isinstance(node, Group):
            for child in node.content:
                found = _find(child, name)
                if found is not None:
                    return found
        return None

    start = _find(params_group, "capture_start")
    end = _find(params_group, "capture_end")
    assert start.enabled_when == "capture_end or not capture_start"
    assert end.enabled_when == "capture_start or not capture_end"
