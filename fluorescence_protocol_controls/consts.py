# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ")

#: Column id (the row trait + storage key).
FLUORESCENCE_COLUMN_ID = "fluorescence"

#: Seconds the handler waits after publishing a step's LED/camera state so
#: the light and exposure settle before the capture bucket (priority 10)
#: fires — the standalone app's led_stabilization_time, doubled for the
#: pub/sub hop to the board.
LED_STABILIZATION_S = 0.2

#: Protocol-run scratch flag: a step turned a light on during this run,
#: so the run's end publishes ALL_LEDS_OFF.
LIGHT_USED_SCRATCH_KEY = "fluorescence_protocol_controls.light_used"
