from traitsui.api import View, VGroup, HGroup, Item, UItem, Readonly, EnumEditor, Label

from microdrop_utils.traitsui_qt_helpers import InPlaceToggleEditor, IconToggleEditor

# Every section is collapsible: an arrow glyph acts as the section header and
# the bordered group below it is shown only while its `show_*` trait is ticked
# (same structure as the heater controls pane). Selecting a mode also
# auto-collapses the set it disables (see the model's mode observer).

# Connection / board identity / last board ack.
status_group = VGroup(
    Readonly("connection_status_text", label="Connection"),
    Readonly("board_id_text", label="Board"),
    Readonly("last_reading", label="Log"),
    visible_when="show_status",
    show_border=True,
)

# Imaging mode + master light toggle.
control_group = VGroup(
    HGroup(
        Item("mode", style="custom", show_label=False,
             editor=EnumEditor(values={"br": "Brightfield",
                                       "fl": "Fluorescence",
                                       "dual": "Dual"}, cols=3)),
        Item("light_on", label="Light", editor=InPlaceToggleEditor(on_label="Light On", off_label="Light Off"),
             enabled_when="connected"),
    ),
    visible_when="show_control",
    show_border=True,
)

# Per-mode LED sets. Enablement mirrors the standalone app: brightfield
# controls active in br+dual, fluorescence controls in fl+dual.
brightfield_group = VGroup(
    Item("br_wavelength", label="Wavelength"),
    Item("br_intensity", label="Intensity"),
    Item("br_frequency", label="Frequency"),
    Item("br_exposure", label="Exposure"),
    Item("br_gain", label="Gain"),
    visible_when="show_brightfield",
    enabled_when="mode != 'fl'",
    show_border=True,
)

fluorescence_group = VGroup(
    Item("fl_wavelength", label="Wavelength"),
    Item("fl_intensity", label="Intensity"),
    Item("fl_frequency", label="Frequency"),
    # In dual mode the camera runs on the brightfield pair (the controller
    # gives it priority), so these two stay editable only in fl mode.
    Item("fl_exposure", label="Exposure", enabled_when="mode == 'fl'"),
    Item("fl_gain", label="Gain", enabled_when="mode == 'fl'"),
    visible_when="show_fluorescence",
    enabled_when="mode != 'br'",
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

        _collapse_header("show_brightfield", "Brightfield"),
        brightfield_group,

        _collapse_header("show_fluorescence", "Fluorescence"),
        fluorescence_group,
    ),
    # Resizable so the pane can be dragged larger/smaller; scrollable so the
    # contents stay reachable when the dock is shorter than the sections.
    resizable=True,
    scrollable=True,
)
