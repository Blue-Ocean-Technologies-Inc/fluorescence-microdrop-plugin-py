from traitsui.api import View, VGroup, Readonly

# Connection / board identity + the placeholder readout. Sections and controls
# for the real fluorescence workflow get ported from the standalone app.
status_group = VGroup(
    Readonly("connection_status_text", label="Connection"),
    Readonly("last_reading", label="Reading"),
    show_border=True,
)

UnifiedView = View(
    status_group,
    resizable=True,
)
