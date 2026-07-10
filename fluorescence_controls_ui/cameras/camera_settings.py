"""Shared ASI camera settings — the single source of truth for the ACTIVE
exposure/gain and the device-viewer stream checkbox.

Three parties meet here (all on the GUI thread):

* the fluorescence controls pane holds per-mode values (br_/fl_) and writes
  the current mode's pair here whenever they or the mode change — plus the
  device-viewer stream checkbox;
* the device viewer's ASI settings row edits these traits directly;
* the running ASI feed observes them: exposure/gain changes are applied to
  the camera, and frames are emitted for the device viewer's video layer
  only while device_viewer_stream is on.

Traits only notify on real changes, so the pane <-> settings back-sync
naturally terminates instead of looping.
"""
from traits.api import Bool, HasTraits, Int

from .consts import ASI_EXPOSURE_DEFAULT, ASI_GAIN_DEFAULT


class AsiCameraSettings(HasTraits):
    """Active exposure (microseconds), gain, and preview state for the
    ASI camera."""

    exposure = Int(ASI_EXPOSURE_DEFAULT)
    gain = Int(ASI_GAIN_DEFAULT)
    device_viewer_stream = Bool(True)


#: Module-level singleton shared inside the fluorescence plugin.
asi_camera_settings = AsiCameraSettings()
