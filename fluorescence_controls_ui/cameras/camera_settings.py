"""Shared ASI camera settings — the single source of truth for the ACTIVE
exposure/gain.

Three parties meet here (all on the GUI thread):

* the fluorescence controls pane holds per-mode values (br_/fl_) and writes
  the current mode's pair here whenever they or the mode change;
* the device viewer's ASI settings row edits these traits directly;
* the running ASI feed observes them and applies changes to the camera.

Traits only notify on real changes, so the pane <-> settings back-sync
naturally terminates instead of looping.
"""
from traits.api import HasTraits, Int

from .consts import ASI_EXPOSURE_DEFAULT, ASI_GAIN_DEFAULT


class AsiCameraSettings(HasTraits):
    """Active exposure (microseconds) and gain for the ASI camera."""

    exposure = Int(ASI_EXPOSURE_DEFAULT)
    gain = Int(ASI_GAIN_DEFAULT)


#: Module-level singleton shared inside the fluorescence plugin.
asi_camera_settings = AsiCameraSettings()
