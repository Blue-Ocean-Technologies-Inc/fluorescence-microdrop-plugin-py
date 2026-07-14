# ASI capture settings (defaults from the standalone app's fluorescence mode).
ASI_EXPOSURE_MIN, ASI_EXPOSURE_MAX, ASI_EXPOSURE_DEFAULT = 32, 60_000_000, 20_000
ASI_GAIN_MIN, ASI_GAIN_MAX, ASI_GAIN_DEFAULT = 0, 600, 300

# Advanced SDK controls (SDK-typical bounds/defaults; the wrapper clamps
# every write to the connected camera's own reported control caps, so
# cameras with narrower ranges stay safe). Offset bounds match the native
# app's Brightness(Offset) slider for this camera family.
ASI_WHITE_BALANCE_MIN, ASI_WHITE_BALANCE_MAX = 1, 99
ASI_WHITE_BALANCE_RED_DEFAULT = 52
ASI_WHITE_BALANCE_BLUE_DEFAULT = 95
ASI_OFFSET_MIN, ASI_OFFSET_MAX, ASI_OFFSET_DEFAULT = 0, 350, 3
ASI_USB_BANDWIDTH_MIN, ASI_USB_BANDWIDTH_MAX, ASI_USB_BANDWIDTH_DEFAULT = 0, 100, 100

# Software auto-exposure / auto-gain (the SDK's own auto controls only
# iterate in video-capture mode, which the snapshot-based capture thread
# doesn't use — so the thread converges frame brightness itself, native
# app's Auto tab semantics: target is an 8-bit display mean).
AUTO_TARGET_BRIGHTNESS_MIN, AUTO_TARGET_BRIGHTNESS_MAX = 50, 160
AUTO_TARGET_BRIGHTNESS_DEFAULT = 100
AUTO_MAX_GAIN_DEFAULT = 300
AUTO_MAX_EXPOSURE_MS_DEFAULT = 100
AUTO_MAX_EXPOSURE_UNITS = ("ms", "s")
AUTO_MAX_EXPOSURE_UNIT_HIGHS = {"ms": 1000, "s": 60}
AUTO_MAX_EXPOSURE_UNIT_US = {"ms": 1_000, "s": 1_000_000}
#: Dead band around the target mean (8-bit units) before adjusting.
AUTO_BRIGHTNESS_TOLERANCE = 5

#: Sensor temperature poll cadence in the capture thread.
TEMPERATURE_POLL_INTERVAL_S = 2.0

# Device-viewer preview stream limits: frames composited under the
# electrodes are full-scene repaints, and the viewport is far smaller than
# the sensor — so preview frames are rate-capped and downscaled BEFORE the
# heavy 16-bit display conversion. Captures always keep the full-rate,
# full-resolution raw frames.
DEVICE_VIEWER_STREAM_MAX_FPS = 20
DEVICE_VIEWER_STREAM_MAX_WIDTH = 960

# Display adjustments (like the ZWO native app's image panel): software
# post-processing applied to the live preview only — NOT camera controls,
# and never applied to the saved raw captures. 1.0 = neutral for all three.
DISPLAY_GAMMA_MIN, DISPLAY_GAMMA_MAX, DISPLAY_GAMMA_DEFAULT = 0.1, 2.0, 1.0
DISPLAY_CONTRAST_MIN, DISPLAY_CONTRAST_MAX, DISPLAY_CONTRAST_DEFAULT = 0.0, 10.0, 1.0
DISPLAY_BRIGHTNESS_MIN, DISPLAY_BRIGHTNESS_MAX, DISPLAY_BRIGHTNESS_DEFAULT = 0.0, 2.0, 1.0

# ROI format choices (see zwoasi.ASI_IMG_TYPES / set_roi): sensor binning,
# output image type, and a centered crop of the binned field. The label
# dicts drive the advanced pane's dropdowns; once a camera reports its
# capabilities they narrow to the supported subset.
ASI_BINNING_CHOICES = (1, 2, 3, 4)
ASI_BINNING_LABELS = {1: "1x1 (full)", 2: "2x2", 3: "3x3", 4: "4x4"}
ASI_IMAGE_TYPE_CHOICES = ("raw16", "raw8", "rgb24", "y8")
ASI_IMAGE_TYPE_LABELS = {"raw16": "RAW 16-bit", "raw8": "RAW 8-bit",
                         "rgb24": "RGB 24-bit", "y8": "Mono 8-bit"}
# Standard centered-crop resolutions offered alongside "full" (like the
# ZWO native GUI's list); each pane run filters them to what fits the
# binned sensor.
ASI_RESOLUTION_PRESETS = (
    (3840, 2160), (2560, 1440), (1920, 1080), (1600, 900), (1280, 720),
    (960, 540), (800, 600), (640, 480), (320, 240),
)
ASI_FLIP_CHOICES = ("none", "horizontal", "vertical", "both")
