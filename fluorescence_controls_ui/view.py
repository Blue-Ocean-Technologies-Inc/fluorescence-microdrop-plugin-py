from traitsui.api import (
    View, VGroup, HGroup, Item, UItem, Readonly, TableEditor, Label,
)
from traitsui.key_bindings import KeyBindings, KeyBinding
from traitsui.menu import Menu, Action

from microdrop_style.icons.icons import ICON_DELETE
from microdrop_utils.traitsui_qt_helpers import (
    CustomCheckboxColumn, IconButtonEditor, InPlaceToggleEditor,
    IconToggleEditor, ObjectColumn,
)

# Every section is collapsible: an arrow glyph acts as the section header and
# the bordered group below it is shown only while its `show_*` trait is
# ticked (same structure as the heater controls pane).

# Connection / board identity / last board ack.
status_group = VGroup(
    Readonly("connection_status_text", label="Connection"),
    Readonly("board_id_text", label="Board"),
    Readonly("last_reading", label="Log"),
    visible_when="show_status",
    show_border=True,
)

# Master light toggle + device-viewer stream checkbox. The mode selector
# (br/fl/dual) is gone (issue #6): a single LED/camera param set now drives
# whichever chain row is being edited.
control_group = VGroup(
    HGroup(
        UItem("light_on", editor=InPlaceToggleEditor(on_label="Light On", off_label="Light Off"),
             enabled_when="connected"),
    ),
    HGroup(
        # Master gate for the pane's LED board commands (heater stream
        # toggle parity): while off, lighting edits are staged.
        UItem("stream_active",
              editor=InPlaceToggleEditor(on_label="Stream On",
                                         off_label="Stream Off"),
              enabled_when="connected"),
        # Live ASI preview in the device viewer — independent of the LED
        # board connection (it only needs the camera), hence no
        # enabled_when.
        Item("device_viewer_stream", label="Device View Camera Feed"),
    ),
    visible_when="show_control",
    show_border=True,
)

# Single LED/camera param set (issue #6): replaces the old brightfield_group
# / fluorescence_group per-mode split. Doubles as the editor for whichever
# capture-chain row is selected (see the controller's panel<->row binding).
# The Auto checkboxes hand exposure/gain to the capture thread's brightness
# loop; the manual sliders disable while their auto is on.
params_group = VGroup(
    Item("label", label="Label"),
    Item("wavelength", label="Wavelength"),
    Item("intensity", label="Intensity (%)"),
    Item("frequency", label="Frequency (Hz)"),
    HGroup(
        Item("exposure", label="Exposure (ms)",
             enabled_when="not auto_exposure"),
        Item("auto_exposure", label="Auto"),
    ),
    HGroup(
        Item("gain", label="Gain", enabled_when="not auto_gain"),
        Item("auto_gain", label="Auto"),
    ),
    visible_when="show_params",
    show_border=True,
)

# Capture-chain table (issue #6), copied from the device viewer's route
# table (route_selection_view.py): the Run column is a glyph, not a Qt
# checkbox — CustomCheckboxColumn renders Material Symbols text and
# toggles the bool on click.
class RunColumn(CustomCheckboxColumn):
    def formatter(self, value):
        return "play_arrow" if value else "play_disabled"


# Right-click menu on a chain row (route-table Menu parity): the Action
# name dispatches to the View's handler — the pane's controller.
ChainRowMenu = Menu(
    Action(name="&Delete", action="delete_chain_row"),
)

chain_table_editor = TableEditor(
    columns=[
        ObjectColumn(name="label", label="Label", resize_mode="stretch"),
        RunColumn(
            name="run",
            label="Run",
            editable=False,
            horizontal_alignment="center",
            width=16,
        ),
    ],
    menu=ChainRowMenu,
    show_lines=False,
    selected="chain_selection",
    sortable=False,
    reorderable=True,
    show_column_labels=True,
    show_row_labels=True,
)

# Glyph buttons above the table (route run_controls parity; IconButtonEditor
# because — unlike the DV sidebar — this pane gets no ancestor QSS that
# maps QPushButton text into the icon font). Add seeds a new row from the
# panel's params (controller.add_capture — no inline row factory, Add owns
# creation); Run Capture bursts the ticked rows; Delete removes the
# selected row, or the last one when nothing is selected.
chain_group = VGroup(
    HGroup(
        UItem("add_capture_button", editor=IconButtonEditor(
            glyph="add", tooltip="Add a capture from the panel's params")),
        UItem("run_capture_button", editor=IconButtonEditor(
            glyph="play_circle", tooltip="Run the ticked captures now"),
              enabled_when="connected and not protocol_running"),
        UItem("delete_capture_button", editor=IconButtonEditor(
            glyph=ICON_DELETE,
            tooltip="Delete the selected capture (the last one when "
                    "nothing is selected)")),
    ),
    UItem("chain_rows", editor=chain_table_editor),
    show_border=True,
)


def _collapse_header(trait, label):
    """A section header row: a Material arrow glyph that expands / collapses
    the section by toggling ``trait``, followed by the section's label."""
    return HGroup(
        UItem(trait, editor=IconToggleEditor()),
        Label(label),
    )


UnifiedView = View(
    VGroup(
        _collapse_header("show_status", "Status"),
        status_group,

        _collapse_header("show_control", "Control"),
        control_group,

        _collapse_header("show_params", "LED / Camera Params"),
        params_group,

        chain_group,
    ),
    # Resizable so the pane can be dragged larger/smaller; scrollable so the
    # contents stay reachable when the dock is shorter than the sections.
    resizable=True,
    scrollable=True,
    # Route-view parity: Delete over the pane removes the selected chain
    # row (handler method lives on the controller — the View's handler).
    key_bindings=KeyBindings(
        KeyBinding(binding1="Delete", method_name="handle_delete_key"),
    ),
)
