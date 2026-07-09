# This module's package.
PKG = '.'.join(__name__.split('.')[:-1])

PREVIEW_DOCK_PANE_ID = PKG + ".dock_pane"
PREVIEW_DOCK_PANE_NAME = "Fluorescence Camera"

START_PREVIEW_TOOLTIP = "Start the live camera preview"
STOP_PREVIEW_TOOLTIP = "Stop the live camera preview"
REFRESH_CAMERAS_TOOLTIP = "Re-scan for connected cameras"

# ASI capture settings (defaults from the standalone app's fluorescence mode).
ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX, ASI_EXPOSURE_DEFAULT = 32, 60_000_000, 20_000
ASI_GAIN_MIN, ASI_GAIN_MAX, ASI_GAIN_DEFAULT = 0, 600, 300
