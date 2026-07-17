# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])
PKG_name = PKG.title().replace("_", " ")

#: Capture-chain field (row trait): list of ChainEntry dicts, or None/[].
#: Replaces the retired fluorescence_on / fluorescence_settings columns
#: (removed in Task 9 / v1.0.0); old step settings are not migrated —
#: users rebuild chains.
FLUORESCENCE_CHAIN_COLUMN_ID = "fluorescence_chain"

#: Seconds the handler waits after publishing a step's LED/camera state so
#: the light and exposure settle before the capture bucket (priority 10)
#: fires — the standalone app's led_stabilization_time, doubled for the
#: pub/sub hop to the board.
LED_STABILIZATION_S = 0.2

