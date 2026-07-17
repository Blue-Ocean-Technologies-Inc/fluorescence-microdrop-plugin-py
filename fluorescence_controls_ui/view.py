from traitsui.api import (
    View, VGroup, HGroup, Item, UItem, Readonly, TableEditor, Label,
)
from traitsui.extras.checkbox_column import CheckboxColumn

from microdrop_utils.traitsui_qt_helpers import (
    InPlaceToggleEditor, IconToggleEditor, ObjectColumn,
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

# Capture-chain table (issue #6): Add seeds a new row from the panel's
# current values (controller.add_capture — no inline row factory, Add owns
# creation); Run Capture fires the chain's ticked rows as a burst
# (controller.run_capture), gated the same way a running protocol gates the
# rest of the pane.
chain_table_editor = TableEditor(
    columns=[
        ObjectColumn(name="label", label="Label", editable=True),
        CheckboxColumn(name="run", label="Run"),
    ],
    editable=True,
    sortable=False,
    auto_size=True,
    selected="chain_selection",
    selection_mode="row",
)

chain_group = VGroup(
    HGroup(
        UItem("add_capture_button"),
        UItem("run_capture_button",
              enabled_when="connected and not protocol_running"),
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
)
