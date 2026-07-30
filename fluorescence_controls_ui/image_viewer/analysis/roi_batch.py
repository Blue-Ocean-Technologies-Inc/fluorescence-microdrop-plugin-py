"""Off-GUI batch computation: a daemon orchestrator thread (the plugin's
established off-GUI pattern) fans the images out to a process pool and
streams results back through a thread-safe queue that the dock pane's
drain timer empties on the GUI thread. One batch at a time — start()
cancels any running one and swaps in a fresh queue, so a superseded
batch's stragglers die with the old queue."""
import os
import queue
import threading
from concurrent.futures import (
    ProcessPoolExecutor, ThreadPoolExecutor, as_completed,
)

from traits.api import Any, HasTraits

from logger.logger_service import get_logger

from .roi_compute import compute_image_stats

logger = get_logger(__name__)

#: Queue message kinds: per-image batch result, end-of-batch marker, and
#: the single-image instant-feedback result.
BATCH_RESULT = "result"
BATCH_FINISHED = "finished"
INSTANT_RESULT = "instant"


def _pool_workers():
    return max((os.cpu_count() or 2) - 1, 1)


class RoiBatchRunner(HasTraits):
    """Runs compute_image_stats over a work list off the GUI thread."""

    #: GUI-drained result queue of (kind, payload) tuples; replaced on
    #: every start() so a cancelled batch's late results are discarded.
    results = Any()

    _thread = Any()
    _cancel = Any()

    def _results_default(self):
        return queue.SimpleQueue()

    def __cancel_default(self):
        return threading.Event()

    def start(self, work_items):
        """``work_items``: [(path, effective_rois), ...] with
        ``effective_rois`` = roi_id -> (kind, geometry tuple)."""
        self.cancel()
        self.results = queue.SimpleQueue()
        self._cancel = threading.Event()
        cancel, results = self._cancel, self.results
        self._thread = threading.Thread(
            target=self._run, args=(list(work_items), cancel, results),
            daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def compute_single(self, path, effective_rois):
        """Instant feedback for a freshly drawn/edited ROI on the shown
        image: one off-thread compute, reported on the same queue."""
        results = self.results
        thread = threading.Thread(
            target=lambda: results.put(
                (INSTANT_RESULT, compute_image_stats(path, effective_rois))),
            daemon=True)
        thread.start()

    @staticmethod
    def _run(work_items, cancel, results):
        try:
            executor = ProcessPoolExecutor(max_workers=_pool_workers())
        except Exception as error:
            logger.warning(f"Process pool unavailable, falling back to "
                           f"threads: {error}")
            executor = ThreadPoolExecutor(max_workers=_pool_workers())
        with executor:
            futures = [executor.submit(compute_image_stats, path, rois)
                       for path, rois in work_items]
            for future in as_completed(futures):
                if cancel.is_set():
                    for pending in futures:
                        pending.cancel()
                    return
                try:
                    results.put((BATCH_RESULT, future.result()))
                except Exception as error:
                    # Pool infrastructure failure (the work unit itself
                    # reports its errors inside the payload).
                    logger.warning(f"ROI batch worker failed: {error}")
        if not cancel.is_set():
            results.put((BATCH_FINISHED, None))
