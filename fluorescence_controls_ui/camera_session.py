# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Fallback capture-camera session for protocol runs.

A protocol that captures needs an open ASI feed (``current_feed()``). Before
the session starts, the chain column has the device viewer show the ASI camera
(DEVICE_VIEWER_CAMERA_SELECT_SOURCE, confirmed or the run stops), so
``activate`` normally finds the viewer's feed running and reuses it — the
operator sees the run's camera, and the column restores the viewer's pre-run
camera at the end. Only when no feed is running (e.g. the viewer's feed failed
to start) does the run open its OWN headless feed, closed again when the run
ends — the camera and LEDs never sit idle heating up.

A reused feed is never closed here. The Device View Camera Feed checkbox the
session turns on is the pane controller's concern
(``_on_protocol_session_active``).

``activate`` / ``deactivate`` touch Qt camera objects, so they must run on the
GUI thread — the message handler marshals them there via ``GUI.invoke_later``.
"""

# Local imports.
from .cameras.provider import AsiCameraSourceProvider, current_feed

# Logger import.
from logger.logger_service import get_logger

logger = get_logger(__name__)

#: The feed THIS session opened, or None when idle / when a feed the device
#: viewer already had open is being reused (that one must not be closed here).
_session_feed = None


def activate():
    """Open a headless ASI feed for the run if none is already running (the
    device viewer's own ASI feed, normally, is)."""
    global _session_feed
    if current_feed() is not None:
        logger.info("Capture camera already running; reusing it for the run.")
        return
    provider = AsiCameraSourceProvider()
    sources = provider.list_sources()
    if not sources:
        logger.warning(
            "No ASI camera found; the run's captures will fail until one is connected."
        )
        return
    _label, camera_id = sources[0]
    try:
        feed = provider.open(camera_id)
        feed.start()
    except Exception as e:
        logger.warning(f"Could not open the capture camera for the run: {e}")
        return
    _session_feed = feed
    logger.info("Opened a headless capture camera for the protocol run.")


def deactivate():
    """Close the feed this session opened (a device-viewer-owned feed is left
    running)."""
    global _session_feed
    if _session_feed is None:
        return
    try:
        _session_feed.stop()
        logger.info("Closed the protocol's capture camera (idle).")
    except Exception as e:
        logger.warning(f"Could not close the capture camera: {e}")
    finally:
        _session_feed = None
