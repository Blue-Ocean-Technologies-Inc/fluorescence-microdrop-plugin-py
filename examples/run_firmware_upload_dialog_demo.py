# (C) Copyright 2024-2026 Blue Ocean Technologies, Inc., Toronto, ON
# All rights reserved.
#
# This software is provided without warranty under the terms of the AGPL-3.0
# license included in LICENSE and may be redistributed only under the
# conditions described in the aforementioned license. The license is also
# available online at https://www.gnu.org/licenses/agpl-3.0.txt
#
# Thanks for using Microdrop open source!

"""Runnable demo: the firmware-upload dialog against a live backend.

Run: pixi run python examples/run_firmware_upload_dialog_demo.py
(from microdrop-py, with the plugin packages installed editable).

In-process harness (dropbot_protocol_controls demo pattern): Redis + dramatiq
workers + message router + the composed fluorescence backend + the real
firmware-upload dialog (fluorescence_controls_ui.firmware_upload). In the
app the plugin's FluorescenceMessageHandler ferries the backend's
firmware-upload signals into live_state; here a small demo listener does the
same job, so the dialog code runs identically in both. To exercise the
proxy-port path, publish START_DEVICE_MONITORING before uploading.
"""

# Standard library imports.
import sys

# Third-party imports.
from PySide6.QtWidgets import QApplication

# Microdrop package imports.
from fluorescence_controller.consts import (
    ACTOR_TOPIC_DICT,
    FIRMWARE_UPLOAD_FINISHED,
    FIRMWARE_UPLOAD_LOG,
    FIRMWARE_UPLOAD_STARTED,
)
from fluorescence_controller.fluorescence_controller_base import (
    FluorescenceControllerBase,
)
from fluorescence_controller.services.fluorescence_firmware_upload_service import (
    FluorescenceFirmwareUploadService,
)
from fluorescence_controller.services.fluorescence_monitor_mixin_service import (
    FluorescenceMonitorMixinService,
)
from fluorescence_controls_ui.firmware_upload.controller import (
    make_firmware_upload_controller,
)
from fluorescence_controls_ui.live_state import fluorescence_live_state

# Microdrop utils imports.
from microdrop_utils.dramatiq_controller_base import (
    generate_class_method_dramatiq_listener_actor,
)
from microdrop_utils.dramatiq_pub_sub_helpers import MessageRouterActor

# Dramatiq listener receiving the backend's firmware-upload signals.
DEMO_LISTENER_NAME = "firmware_upload_demo_listener"


def _on_backend_message(timestamped_message, topic):
    """Demo stand-in for the plugin's FluorescenceMessageHandler (worker
    thread): ferry each firmware-upload signal into live_state — the dialog
    controller's dispatch="ui" observer applies it on the GUI thread."""
    fluorescence_live_state.firmware_upload_message = (topic, str(timestamped_message))


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    from microdrop_style.helpers import style_app

    style_app(app)

    router = MessageRouterActor()

    # Compose the backend exactly like the plugin does (mixin services onto
    # the controller base); keep the reference alive for the app's lifetime.
    demo_backend_class = type(
        "DemoFluorescenceBackend",
        (
            FluorescenceFirmwareUploadService,
            FluorescenceMonitorMixinService,
            FluorescenceControllerBase,
        ),
        {},
    )
    backend = demo_backend_class()

    generate_class_method_dramatiq_listener_actor(
        listener_name=DEMO_LISTENER_NAME, class_method=_on_backend_message
    )

    for backend_listener_name, topics in ACTOR_TOPIC_DICT.items():
        for topic in topics:
            router.message_router_data.add_subscriber_to_topic(
                topic, backend_listener_name
            )
    for topic in (
        FIRMWARE_UPLOAD_STARTED,
        FIRMWARE_UPLOAD_LOG,
        FIRMWARE_UPLOAD_FINISHED,
    ):
        router.message_router_data.add_subscriber_to_topic(topic, DEMO_LISTENER_NAME)

    controller = make_firmware_upload_controller()
    controller.open()
    app.exec()
    backend.cleanup()


if __name__ == "__main__":
    from microdrop_utils.broker_server_helpers import (
        dramatiq_workers_context,
        redis_server_context,
    )

    with redis_server_context():
        with dramatiq_workers_context():
            main()
