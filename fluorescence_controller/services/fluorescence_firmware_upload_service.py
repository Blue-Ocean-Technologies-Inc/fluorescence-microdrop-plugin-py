import json
import threading

from traits.api import provides, Any, HasTraits, Instance

from microdrop_utils.dramatiq_pub_sub_helpers import publish_message

from ..consts import (
    FIRMWARE_UPLOAD_FINISHED, FIRMWARE_UPLOAD_LOG, FIRMWARE_UPLOAD_STARTED,
    START_DEVICE_MONITORING,
)
from ..firmware_uploader import upload_firmware
from ..interfaces.i_fluorescence_control_mixin_service import IFluorescenceControlMixinService
from ..fluorescence_serial_proxy import FluorescenceSerialProxy
from ..datamodels import UploadFirmwareData

from logger.logger_service import get_logger
logger = get_logger(__name__)


@provides(IFluorescenceControlMixinService)
class FluorescenceFirmwareUploadService(HasTraits):
    """Flashes the fluorescence board's MicroPython firmware.

    Runs firmware_uploader.upload_firmware (the in-repo port of the
    standalone app's upload script) on a worker thread, streaming each
    progress line onto FIRMWARE_UPLOAD_LOG so any frontend can render a live
    console. The accepted run is announced on FIRMWARE_UPLOAD_STARTED and
    the outcome ({"success": bool}, or {"error": str} on a crash) on
    FIRMWARE_UPLOAD_FINISHED.

    Port resolution: an explicit requested port wins; otherwise a connected
    proxy's stored port is reused directly — the board is already
    identified, no whoami probing needed. Whenever the target port is the
    proxy's own, the proxy is released first via the composed controller's
    ``cleanup()`` (the uploader needs exclusive port access, and cleanup
    also stops the monitor so it can't reclaim the port mid-flash), and
    device monitoring is re-requested once the upload ends so the freshly
    flashed board reconnects.

    The upload thread and the timeout timer publish from non-worker threads
    — same precedent as the proxy's telemetry reader thread. Cancel and
    timeout both set the run's cancel event, which the uploader honours
    between steps.
    """

    proxy = Instance(FluorescenceSerialProxy)

    #: The running upload thread (None / dead while idle).
    upload_thread = Instance(threading.Thread)
    #: Set to abort the running upload (cancel request or timeout).
    upload_cancel_event = Instance(threading.Event)
    #: Cancels the upload at the request's timeout (None when no timeout).
    upload_timeout_timer = Instance(threading.Timer)
    #: Serializes upload start/cancel against the upload thread's completion.
    upload_state_lock = Any()

    def _upload_state_lock_default(self):
        return threading.Lock()

    # ---- request handlers ------------------------------------------------

    def on_upload_firmware_request(self, body):
        """Validate an UploadFirmwareData payload and launch one upload;
        a request arriving while an upload runs is logged and ignored."""
        data = UploadFirmwareData(**json.loads(body))
        with self.upload_state_lock:
            if self.upload_thread is not None and self.upload_thread.is_alive():
                publish_message(
                    message="A firmware upload is already running — "
                            "request ignored.",
                    topic=FIRMWARE_UPLOAD_LOG)
                return
            port, proxy_released = self._resolve_upload_port(data)
            self.upload_cancel_event = threading.Event()
            publish_message(
                message=f"Starting firmware upload from "
                        f"{data.single_file or data.firmware_dir} "
                        f"(port: {port or 'auto-detect'}"
                        f"{', dry run' if data.dry_run else ''})",
                topic=FIRMWARE_UPLOAD_STARTED)
            if data.upload_timeout_s > 0:
                self.upload_timeout_timer = threading.Timer(
                    data.upload_timeout_s, self._cancel_timed_out_upload,
                    args=(self.upload_cancel_event, data.upload_timeout_s))
                self.upload_timeout_timer.daemon = True
                self.upload_timeout_timer.start()
            self.upload_thread = threading.Thread(
                target=self._run_upload,
                args=(data, port, proxy_released, self.upload_cancel_event),
                daemon=True)
            self.upload_thread.start()

    def on_cancel_firmware_upload_request(self, body):
        """Abort the running upload; the uploader stops at the next step
        boundary and reports through the normal finish path."""
        with self.upload_state_lock:
            if self.upload_thread is None or not self.upload_thread.is_alive():
                return
            publish_message(
                message="Cancel requested — stopping the upload at the next "
                        "step.",
                topic=FIRMWARE_UPLOAD_LOG)
            self.upload_cancel_event.set()

    # ---- upload run ------------------------------------------------------

    def _resolve_upload_port(self, data):
        """The port to flash and whether the proxy was released for it.

        Whenever the target port is the connected proxy's own (explicitly, or
        because the empty auto port resolves to it), the proxy must go: the
        uploader needs exclusive access to the port.
        """
        port = data.port
        if self.proxy is not None:
            if not port:
                port = self.proxy.port
            if port == self.proxy.port:
                publish_message(
                    message=f"Disconnecting the board on {port} to free the "
                            f"port for the upload.",
                    topic=FIRMWARE_UPLOAD_LOG)
                self.cleanup()
                return port, True
        return port, False

    def _run_upload(self, data, port, proxy_released, cancel_event):
        """Upload thread: run the uploader with a topic-publishing log, then
        report the outcome; if the proxy was released for this upload,
        re-request monitoring so the freshly flashed board reconnects."""
        try:
            success = upload_firmware(
                firmware_path=data.firmware_dir,
                port=port or None,
                reset_device=data.reset_after_upload,
                single_file=data.single_file or None,
                no_format=data.skip_filesystem_format,
                update_config=data.update_config,
                device_id=data.device_id,
                dry_run=data.dry_run,
                log=self._publish_upload_log_line,
                cancel_event=cancel_event,
            )
            finished_payload = {"success": success}
        except Exception as e:
            logger.exception("Firmware upload crashed")
            finished_payload = {"error": str(e)}
        with self.upload_state_lock:
            if self.upload_timeout_timer is not None:
                self.upload_timeout_timer.cancel()
                self.upload_timeout_timer = None
        publish_message(message=json.dumps(finished_payload),
                        topic=FIRMWARE_UPLOAD_FINISHED)
        if proxy_released:
            publish_message(message="", topic=START_DEVICE_MONITORING)

    @staticmethod
    def _publish_upload_log_line(line):
        publish_message(message=line, topic=FIRMWARE_UPLOAD_LOG)

    @staticmethod
    def _cancel_timed_out_upload(cancel_event, upload_timeout_s):
        if cancel_event.is_set():
            return
        publish_message(
            message=f"Upload timed out after {upload_timeout_s} s — "
                    f"aborting.",
            topic=FIRMWARE_UPLOAD_LOG)
        cancel_event.set()
