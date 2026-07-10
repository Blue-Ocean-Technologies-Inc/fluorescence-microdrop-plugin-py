from traitsui.api import (
    CustomEditor, EnumEditor, Group, HGroup, Item, Readonly, UItem, VGroup,
    View,
)

from microdrop_utils.traitsui_qt_helpers import SteppedSliderEditor

from ..cameras.consts import (
    DISPLAY_BRIGHTNESS_MAX, DISPLAY_BRIGHTNESS_MIN, DISPLAY_CONTRAST_MAX,
    DISPLAY_CONTRAST_MIN, DISPLAY_GAMMA_MAX, DISPLAY_GAMMA_MIN,
)
from .temperature_canvas import temperature_canvas_factory

# Sensor readout shape: what the camera reads out and ships. These re-shape
# the stream on the next frame (no restart needed). Choices come from the
# model's dynamic dicts, narrowed to the connected camera's capabilities
# (resolutions turn concrete once the sensor size is known).
format_tab = VGroup(
    Item("binning", label="Binning",
         editor=EnumEditor(name="object.binning_choices")),
    Item("image_type", label="Image Type",
         editor=EnumEditor(name="object.image_type_choices")),
    Item("resolution", label="Resolution",
         editor=EnumEditor(name="object.resolution_choices")),
    UItem("format_defaults_button"),
    label="Format",
)

# Display adjustments (software, preview-only — like the ZWO native app's
# image panel), sliding in 0.1 increments. White balance only exists on
# color sensors, so it shows only when the camera reports color.
display_tab = VGroup(
    Item("display_gamma", label="Gamma",
         editor=SteppedSliderEditor(low=DISPLAY_GAMMA_MIN,
                                    high=DISPLAY_GAMMA_MAX, step=0.1)),
    Item("display_contrast", label="Contrast",
         editor=SteppedSliderEditor(low=DISPLAY_CONTRAST_MIN,
                                    high=DISPLAY_CONTRAST_MAX, step=0.1)),
    Item("display_brightness", label="Brightness",
         editor=SteppedSliderEditor(low=DISPLAY_BRIGHTNESS_MIN,
                                    high=DISPLAY_BRIGHTNESS_MAX, step=0.1)),
    Item("white_balance_red", label="WB Red",
         visible_when="camera_is_color"),
    Item("white_balance_blue", label="WB Blue",
         visible_when="camera_is_color"),
    UItem("display_defaults_button"),
    label="Display",
)

# Camera-side transfer / readout extras (the native app's USB tab).
usb_tab = VGroup(
    Item("offset", label="Brightness (Offset)"),
    Item("usb_bandwidth", label="USB Traffic (%)"),
    Item("high_speed_mode", label="High Speed"),
    Item("hardware_bin", label="Hardware Bin"),
    Item("mono_bin", label="Mono Bin", visible_when="camera_is_color"),
    Item("add_timestamp", label="Add Timestamp"),
    Item("flip", label="Flip",
         editor=EnumEditor(values={"none": "None",
                                   "horizontal": "Horizontal",
                                   "vertical": "Vertical",
                                   "both": "Both"})),
    UItem("usb_defaults_button"),
    label="USB",
)

# Software auto-exposure limits (the Auto checkboxes sit next to the
# exposure/gain sliders in the main fluorescence controls pane).
auto_tab = VGroup(
    Item("auto_target_brightness", label="Target Brightness"),
    Item("auto_max_gain", label="Max Gain Limit"),
    HGroup(
        Item("auto_max_exposure_value", label="Max Exposure Limit"),
        UItem("auto_max_exposure_unit"),
    ),
    UItem("auto_defaults_button"),
    label="Auto",
)

# Sensor temperature monitor.
temp_tab = VGroup(
    HGroup(
        Readonly("initial_temperature_text", label="Initial"),
        Readonly("current_temperature_text", label="Current"),
        Readonly("monitor_time_text", label="Time"),
    ),
    UItem("temperature_history",
          editor=CustomEditor(temperature_canvas_factory)),
    label="Temp",
)

advanced_camera_view = View(
    Group(
        format_tab,
        display_tab,
        usb_tab,
        auto_tab,
        temp_tab,
        layout="tabbed",
    ),
    resizable=True,
)
