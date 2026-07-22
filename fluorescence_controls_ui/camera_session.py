"""Headless capture-camera session for protocol runs.

A protocol that captures needs an open ASI feed (``current_feed()``), but
today that only exists if the operator manually turned the camera on in the
device viewer. So a run opens its OWN headless feed just to snap pictures and
closes it when the run ends — the camera and LEDs never sit idle heating up.

The device-viewer live preview stays independent: if the operator has already
pointed it at the ASI camera, that feed is reused (and left alone at the end)
rather than opening a second one on the single camera.

``activate`` / ``deactivate`` touch Qt camera objects, so they must run on the
GUI thread — the message handler marshals them there via ``GUI.invoke_later``.
"""
from logger.logger_service import get_logger

from .cameras.provider import AsiCameraSourceProvider, current_feed

logger = get_logger(__name__)

#: The feed THIS session opened, or None when idle / when a feed the device
#: viewer already had open is being reused (that one must not be closed here).
_session_feed = None


def activate():
    """Open a headless ASI feed for the run if none is already running."""
    global _session_feed
    if current_feed() is not None:
        logger.info("Capture camera already running; reusing it for the run.")
        return
    provider = AsiCameraSourceProvider()
    sources = provider.list_sources()
    if not sources:
        logger.warning("No ASI camera found; the run's captures will fail "
                       "until one is connected.")
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
