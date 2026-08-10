"""Help-menu installer for the optional SAM (osam) ROI-detection stack.

Runs ``pixi add --pypi osam`` (plus ``onnxruntime-directml`` on Windows, a
tolerated-failure optional GPU accelerator) from the pixi project root in a
worker thread, streaming output into a cancellable ``QProgressDialog``.
Mirrors ``image_viewer/sam_download.py``'s QThread + QProgressDialog
pattern for consistency.
"""
import importlib
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QProgressDialog

from logger.logger_service import get_logger

logger = get_logger(__name__)

#: Base label text the dialog stays pinned to; the latest output line (or
#: failure reason) is appended beneath it as the install progresses.
_INSTALL_LABEL = "Installing AI ROI support (osam)..."


def _pixi_project_root():
    """The pixi project root: walk up from the running interpreter's
    ``sys.prefix`` looking for a directory with a ``pixi.toml``, or a
    ``pyproject.toml`` whose text declares a ``[tool.pixi`` table. Falls
    back to the current working directory (logged) if neither is found."""
    start = Path(sys.prefix)
    for directory in (start, *start.parents):
        if (directory / "pixi.toml").exists():
            return directory
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(f"Could not read {pyproject}: {e}")
                text = ""
            if "[tool.pixi" in text:
                return directory
    logger.warning(
        f"No pixi.toml or pyproject.toml with [tool.pixi] found above "
        f"{start}; falling back to cwd {Path.cwd()}"
    )
    return Path.cwd()


class _InstallThread(QThread):
    """Runs ``pixi add --pypi osam`` (plus ``onnxruntime-directml`` on
    Windows, tolerated failure) in the pixi project root, streaming output
    lines and reporting success/failure."""

    output = Signal(str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self._root = root
        self._process = None

    def cancel(self):
        if self._process is not None:
            self._process.kill()

    def _run_step(self, args):
        """Run one pixi command, streaming its output line by line.
        Returns the exit code."""
        self._process = subprocess.Popen(
            args, cwd=self._root, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        for line in self._process.stdout:
            line = line.rstrip()
            if line:
                self.output.emit(line)
        return self._process.wait()

    def run(self):
        try:
            code = self._run_step(["pixi", "add", "--pypi", "osam"])
        except FileNotFoundError:
            self.failed.emit("pixi not found on PATH")
            return
        except Exception as e:
            self.failed.emit(f"Install failed: {e}")
            return

        if code != 0:
            self.failed.emit("Install failed")
            return

        if sys.platform == "win32":
            try:
                gpu_code = self._run_step(
                    ["pixi", "add", "--pypi", "onnxruntime-directml"])
            except Exception as e:
                gpu_code = None
                logger.warning(
                    f"onnxruntime-directml install could not run: {e} "
                    f"(optional GPU accelerator, continuing)"
                )
            if gpu_code:
                logger.warning(
                    f"pixi add --pypi onnxruntime-directml exited "
                    f"{gpu_code} (optional GPU accelerator, continuing)"
                )

        self.succeeded.emit()


def install_ai_support(parent=None):
    """Install the optional SAM (osam) segmentation stack with pixi,
    showing progress in a cancellable dialog. Returns True only if osam
    successfully imports afterwards. Never raises."""
    root = _pixi_project_root()

    dialog = QProgressDialog(_INSTALL_LABEL, "Cancel", 0, 0, parent)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setMinimumWidth(400)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    thread = _InstallThread(root=root, parent=parent)
    succeeded = False

    def _on_output(line):
        dialog.setLabelText(f"{_INSTALL_LABEL}\n{line}")

    def _on_succeeded():
        nonlocal succeeded
        succeeded = True
        dialog.close()

    def _on_failed(reason):
        logger.error(f"AI support install failed: {reason}")
        dialog.setRange(0, 1)
        dialog.setLabelText(f"{dialog.labelText()}\n{reason}")
        dialog.setCancelButtonText("Close")

    dialog.canceled.connect(thread.cancel)
    thread.output.connect(_on_output)
    thread.succeeded.connect(_on_succeeded)
    thread.failed.connect(_on_failed)

    dialog.show()
    thread.start()
    dialog.exec()

    thread.output.disconnect(_on_output)
    thread.succeeded.disconnect(_on_succeeded)
    thread.failed.disconnect(_on_failed)
    if not thread.wait(5000):
        thread.terminate()
        thread.wait()

    if not succeeded:
        return False

    importlib.invalidate_caches()
    try:
        # optional dependency: same exception granted to sam_detect.py's
        # osam import — this just-installed package may still fail to
        # import (e.g. a partial/incompatible install).
        import osam  # noqa: F401
    except ImportError as e:
        logger.warning(f"osam import still failing after install: {e}")
        return False
    return True
