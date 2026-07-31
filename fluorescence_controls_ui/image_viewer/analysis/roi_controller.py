"""Controller for the ROI analysis: reacts to the analysis toolbuttons
and canvas events, keeps the per-experiment ROI config in sync,
orchestrates the cache-aware batch computation, and rebuilds the plot
series as results drain in. All observers run on the GUI thread; the
only off-thread work is inside RoiBatchRunner."""
import math
import queue
import time
from pathlib import Path

from traits.api import Bool, Dict, HasTraits, Instance, observe
from pyface.api import NO, YES

from logger.logger_service import get_logger
from microdrop_application.dialogs.pyface_wrapper import confirm

from device_viewer.consts import CAPTURES_DIR_NAME
from fluorescence_protocol_controls.capture_chain import sanitize_label

from ...consts import CAPTURE_TIMESTAMP_FORMAT
from ..discovery import UNGROUPED_BURST, capture_timestamp, \
    detect_wavelength
from ..model import FluorescenceImageViewerModel
from .roi_batch import (
    BATCH_FINISHED, BATCH_RESULT, INSTANT_RESULT, RoiBatchRunner,
)
from .roi_model import Roi, RoiAnalysisModel
from .roi_store import (
    analysis_directory, load_roi_config, save_roi_config,
    write_intensity_csv,
)

logger = get_logger(__name__)


class RoiAnalysisController(HasTraits):
    """Glue between the viewer model (whose ``paths`` IS the filtered
    series), the analysis model, and the batch runner."""

    viewer_model = Instance(FluorescenceImageViewerModel)
    analysis_model = Instance(RoiAnalysisModel)
    runner = Instance(RoiBatchRunner, ())

    #: Export requested while the cache was incomplete: write the CSV
    #: when the running batch finishes.
    _pending_export = Bool(False)

    #: (path str, roi_id) -> cache key, snapshotted at dispatch time so
    #: drained results land under the geometry they were computed with.
    _dispatched_keys = Dict()

    # ------------------------------------------------------------------ #
    # Interaction modes                                                    #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:draw_circle_button")
    def _arm_draw_circle(self, event):
        self.analysis_model.interaction_mode = "draw_circle"

    @observe("analysis_model:draw_box_button")
    def _arm_draw_box(self, event):
        self.analysis_model.interaction_mode = "draw_box"

    @observe("analysis_model:edit_mode")
    def _toggle_edit_mode(self, event):
        self.analysis_model.interaction_mode = ("edit" if event.new
                                                else "pan")

    def _rest_mode(self):
        return "edit" if self.analysis_model.edit_mode else "pan"

    # ------------------------------------------------------------------ #
    # Canvas events                                                        #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:canvas_roi_created")
    def _on_canvas_roi_created(self, event):
        kind, geometry = event.new
        current = self.viewer_model.current_path
        anchor = capture_timestamp(current) if current else 0.0
        roi = Roi(name=self.analysis_model.next_roi_name(), kind=kind,
                  geometry=[float(value) for value in geometry],
                  base_anchor=anchor)
        self.analysis_model.rois.append(roi)
        self.analysis_model.interaction_mode = self._rest_mode()
        self._save_config()
        self._restart_batch_if_running()
        self._instant_stats(roi)

    @observe("analysis_model:canvas_roi_edited")
    def _on_canvas_roi_edited(self, event):
        roi_id, geometry = event.new
        roi = self.analysis_model.roi_by_id(roi_id)
        current = self.viewer_model.current_path
        if roi is None or not current:
            return
        roi.apply_edit(capture_timestamp(current),
                       [float(value) for value in geometry])
        self._save_config()
        self._restart_batch_if_running()
        self._instant_stats(roi)

    # ------------------------------------------------------------------ #
    # Delete / clear / reset                                               #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:delete_roi_button")
    def _delete_selected_roi(self, event):
        roi = self.analysis_model.roi_by_id(
            self.analysis_model.selected_roi_id)
        if roi is None:
            self.analysis_model.roi_info_text = (
                "Select an ROI first (edit mode) to delete it")
            return
        self.analysis_model.rois.remove(roi)
        self.analysis_model.selected_roi_id = ""
        self._save_config()
        self._rebuild_plot_series()
        self._restart_batch_if_running()

    @observe("analysis_model:clear_rois_button")
    def _clear_rois(self, event):
        if not self.analysis_model.rois:
            return
        if confirm(message="Remove ALL ROIs (and their drift "
                           "overrides)?") != YES:
            return
        self.runner.cancel()
        self.analysis_model.rois = []
        self.analysis_model.selected_roi_id = ""
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self._save_config()
        self._rebuild_plot_series()

    @observe("analysis_model:reset_cache_button")
    def _reset_cache(self, event):
        result = confirm(
            message="Reset the calculated ROI intensities?",
            cancel=True, yes_label="Cache only",
            no_label="Cache + drift overrides")
        if result not in (YES, NO):
            return
        self.runner.cancel()
        self.analysis_model.cache = {}
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        if result == NO:
            for roi in self.analysis_model.rois:
                roi.clear_overrides()
            self._save_config()
        self._rebuild_plot_series()

    # ------------------------------------------------------------------ #
    # Batch orchestration                                                  #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:calculate_button")
    def _calculate(self, event):
        self._start_batch()

    @observe("analysis_model:export_csv_button")
    def _export(self, event):
        if not self.analysis_model.rois or not self.viewer_model.paths:
            self.analysis_model.progress_text = "Nothing to export"
            return
        self._dispatched_keys = {}
        work = self._missing_work()
        if work:
            self._pending_export = True
            self.analysis_model.progress_text = "Calculating for export…"
            self._start_batch(work)
            return
        self._write_export()

    @observe("viewer_model:paths.items, viewer_model:selected_wavelength,"
             " viewer_model:selected_burst")
    def _on_filter_changed(self, event):
        """The filtered series changed (mid-batch or not): rebuild the
        plot on the new snapshot first — a rescan can land a new
        ``paths`` after ``browsed_directory`` already swapped in the new
        experiment's cache/series, so the series must be rebuilt here
        even with no batch running — then restart any running batch on
        the new snapshot (the work list is a snapshot by design)."""
        self._rebuild_plot_series()
        self._restart_batch_if_running()

    def _missing_work(self):
        """[(path_str, {roi_id: (kind, geometry)}), ...] for every
        filtered image with at least one uncached (image, ROI) pair —
        only the missing ROIs are dispatched per image."""
        stat_cache = {}
        work = []
        for path in self.viewer_model.paths:
            missing = {}
            for roi in self.analysis_model.rois:
                key = self.analysis_model.cache_key(path, roi, stat_cache)
                if key not in self.analysis_model.cache:
                    missing[roi.roi_id] = (roi.kind,
                                           tuple(key[4]))
                    self._dispatched_keys[(str(path), roi.roi_id)] = key
            if missing:
                work.append((str(path), missing))
        return work

    def _start_batch(self, work=None):
        if not self.analysis_model.rois or not self.viewer_model.paths:
            return
        if work is None:
            self._dispatched_keys = {}
            work = self._missing_work()
        self.analysis_model.batch_done = 0
        self.analysis_model.batch_failed = 0
        self.analysis_model.batch_total = len(work)
        if not work:
            self.analysis_model.batch_running = False
            self.analysis_model.progress_text = "ROI stats up to date"
            self._rebuild_plot_series()
            if self._pending_export:
                self._write_export()
            return
        self.analysis_model.batch_running = True
        self._update_progress_text()
        self.runner.start(work)

    def _restart_batch_if_running(self):
        if self.analysis_model.batch_running:
            self._start_batch()

    def drain_results(self):
        """Called by the dock pane's drain QTimer (GUI thread): move
        finished results from the runner's queue into the model."""
        drained = False
        while True:
            try:
                kind, payload = self.runner.results.get_nowait()
            except queue.Empty:
                break
            drained = True
            if kind == BATCH_RESULT:
                self._absorb(payload)
                self.analysis_model.batch_done += 1
                if payload["error"]:
                    self.analysis_model.batch_failed += 1
                    logger.warning(f"ROI stats failed for "
                                   f"{payload['path']}: {payload['error']}")
                self._update_progress_text()
            elif kind == INSTANT_RESULT:
                self._absorb(payload)
                self._show_instant(payload)
            elif kind == BATCH_FINISHED:
                self.analysis_model.batch_running = False
                self._update_progress_text(finished=True)
                if self._pending_export:
                    self._write_export()
        if drained:
            self._rebuild_plot_series()

    def _absorb(self, payload):
        for roi_id, stats in payload["stats"].items():
            key = self._dispatched_keys.get((payload["path"], roi_id))
            if key is not None:
                self.analysis_model.cache[key] = stats

    def _update_progress_text(self, finished=False):
        model = self.analysis_model
        failed = f", {model.batch_failed} failed" if model.batch_failed \
            else ""
        state = "done" if finished else "calculating"
        model.progress_text = (
            f"ROI stats {model.batch_done}/{model.batch_total} "
            f"{state}{failed}")

    def _instant_stats(self, roi):
        """Kick off the instant single-image compute for ``roi`` on the
        shown image."""
        current = self.viewer_model.current_path
        if not current:
            return
        key = self.analysis_model.cache_key(current, roi)
        self._dispatched_keys[(current, roi.roi_id)] = key
        cached = self.analysis_model.cache.get(key)
        if cached is not None:
            self._show_instant({"path": current,
                                "stats": {roi.roi_id: cached},
                                "error": None})
            return
        self.runner.compute_single(current,
                                   {roi.roi_id: (roi.kind, tuple(key[4]))})

    def _show_instant(self, payload):
        """Derive the ROI from the payload itself (an instant payload
        carries exactly one roi_id) rather than trusting a controller-
        held "last drawn/edited" reference, which a second quick edit
        can race ahead of. An error payload has empty stats — there is
        no roi_id to key off, and the failure is already logged by the
        batch/instant compute layer, so it is skipped silently."""
        stats_by_roi = payload["stats"]
        roi_id = next(iter(stats_by_roi), None)
        roi = self.analysis_model.roi_by_id(roi_id)
        if roi is None:
            return
        stats = stats_by_roi[roi.roi_id]
        self.analysis_model.roi_info_text = (
            f"{roi.name}: mean {stats['mean']:.1f}  "
            f"std {stats['std']:.1f}  min {stats['min']:.0f}  "
            f"max {stats['max']:.0f}  n {int(stats['count'])}")

    # ------------------------------------------------------------------ #
    # Plot series                                                          #
    # ------------------------------------------------------------------ #
    def _rebuild_plot_series(self):
        model = self.analysis_model
        paths = list(self.viewer_model.paths)
        if not paths or not model.rois:
            model.plot_series = {}
            model.plot_revision += 1
            return
        #: One stat()/capture_timestamp() per path for this whole pass —
        #: cache_key() would otherwise re-stat every (image, ROI) pair,
        #: and this rebuilds ~5x/s while a batch drains.
        stat_cache = {}
        times = [model.stat_info(path, stat_cache)[1] for path in paths]
        start_time = times[0]
        series = {}
        for roi in model.rois:
            elapsed, means = [], []
            for path, capture_time in zip(paths, times):
                stats = model.cache.get(
                    model.cache_key(path, roi, stat_cache))
                elapsed.append(capture_time - start_time)
                means.append(stats["mean"] if stats else math.nan)
            series[roi.roi_id] = (roi.name, elapsed, means)
        model.plot_series = series
        model.plot_revision += 1

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #
    def _experiment_directory(self):
        """The folder analysis outputs belong to: the experiment folder
        when browsing its captures dir, else the browsed folder itself.
        None when nothing is resolved yet."""
        browsed = self.viewer_model.browsed_directory
        if not browsed:
            return None
        folder = Path(browsed)
        return folder.parent if folder.name == CAPTURES_DIR_NAME \
            else folder

    def _save_config(self):
        directory = self._experiment_directory()
        if directory is None:
            return
        try:
            save_roi_config(directory, self.analysis_model.rois)
        except Exception as error:
            logger.warning(f"Could not save ROI config: {error}")

    @observe("viewer_model:browsed_directory")
    def _on_experiment_changed(self, event):
        """A different folder is being browsed: its saved ROIs replace
        the current set; cache and series start over."""
        self.runner.cancel()
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self.analysis_model.roi_info_text = ""
        self.analysis_model.selected_roi_id = ""
        self.analysis_model.cache = {}
        directory = self._experiment_directory()
        self.analysis_model.rois = (load_roi_config(directory)
                                    if directory is not None else [])
        self._rebuild_plot_series()

    def _write_export(self):
        self._pending_export = False
        directory = self._experiment_directory()
        if directory is None:
            self.analysis_model.progress_text = "No experiment folder"
            return
        model = self.analysis_model
        paths = list(self.viewer_model.paths)
        stat_cache = {}
        times = [model.stat_info(path, stat_cache)[1] for path in paths]
        start_time = times[0] if times else 0.0
        rows = []
        for path, capture_time in zip(paths, times):
            stats_by_roi = {}
            for roi in model.rois:
                stats = model.cache.get(
                    model.cache_key(path, roi, stat_cache))
                if stats is not None:
                    stats_by_roi[roi.roi_id] = stats
            rows.append({
                "filename": Path(path).name,
                "time_utc": time.strftime(CAPTURE_TIMESTAMP_FORMAT,
                                          time.gmtime(capture_time)),
                "elapsed_sec": capture_time - start_time,
                "group": self._group_of(path),
                "wavelength": detect_wavelength(path),
                "stats": stats_by_roi,
            })
        # capture_service needs the camera stack, so the import stays
        # lazily deferred here — never at module load time (also what
        # keeps it mockable via sys.modules in tests).
        from fluorescence_controls_ui import capture_service
        name = (f"roi_intensities_"
                f"{sanitize_label(self.viewer_model.selected_burst)}_"
                f"{sanitize_label(self.viewer_model.selected_wavelength)}_"
                f"{capture_service.utc_stamp()}.csv")
        csv_path = analysis_directory(directory) / name
        try:
            write_intensity_csv(csv_path, rows, model.rois)
        except Exception as error:
            logger.warning(f"CSV export failed: {error}")
            model.progress_text = f"Export failed: {error}"
            return
        model.progress_text = f"Exported {csv_path.name}"
        logger.info(f"ROI intensities exported to {csv_path}")

    def _group_of(self, path):
        """The image-group (burst folder) name a capture belongs to."""
        burst_dir = Path(path).parent.parent
        browsed = self.viewer_model.browsed_directory
        if browsed and burst_dir == Path(browsed):
            return UNGROUPED_BURST
        return burst_dir.name
