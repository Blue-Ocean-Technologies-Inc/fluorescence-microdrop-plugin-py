# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ")

#: Compound unit id (PPT-11): the persistence discriminator on each field's
#: JSON column entry and the ack-wait grid key.
FLUORESCENCE_COMPOUND_BASE_ID = "fluorescence"
#: Checkbox field (row trait): apply this step's fluorescence state, or
#: leave it untouched.
FLUORESCENCE_ON_COLUMN_ID = "fluorescence_on"
#: Settings field (row trait): dict snapshot of the live controls, or None.
FLUORESCENCE_SETTINGS_COLUMN_ID = "fluorescence_settings"

#: The scalar dict keys a step's fluorescence snapshot stores — identical
#: to the controls-pane model's trait names, so the pane and the column
#: exchange snapshots without translation. The advanced camera settings
#: ride separately under the "advanced" key.
STEP_SETTING_TRAITS = (
    "mode", "light_on",
    "br_wavelength", "br_intensity", "br_frequency", "br_exposure", "br_gain",
    "fl_wavelength", "fl_intensity", "fl_frequency", "fl_exposure", "fl_gain",
    "auto_exposure", "auto_gain",
)

#: Seconds the handler waits after publishing a step's LED/camera state so
#: the light and exposure settle before the capture bucket (priority 10)
#: fires — the standalone app's led_stabilization_time, doubled for the
#: pub/sub hop to the board.
LED_STABILIZATION_S = 0.2

