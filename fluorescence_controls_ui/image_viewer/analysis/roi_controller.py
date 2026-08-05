"""Controller for the ROI analysis: reacts to the analysis toolbuttons
and canvas events, keeps the per-experiment ROI config in sync, and
orchestrates the cache-aware batch computation. All observers run on
the GUI thread; the only off-thread work is inside RoiBatchRunner."""
import queue
import time
from pathlib import Path

from traits.api import Bool, Dict, Float, HasTraits, Instance, observe
from pyface.api import NO, YES

from logger.logger_service import get_logger
from microdrop_application.dialogs.pyface_wrapper import confirm

from device_viewer.consts import CAPTURES_DIR_NAME
from fluorescence_protocol_controls.capture_chain import sanitize_label

from ...consts import CAPTURE_TIMESTAMP_FORMAT
from ..discovery import UNGROUPED_BURST, capture_timestamp, \
    detect_wavelength
from ..model import FluorescenceImageViewerModel
from ..scale_bar import area_unit, format_length, pixel_area
from .consts import DEFAULT_ROI_COLORS, STATS_SAVE_DEBOUNCE_S
from .roi_batch import (
    BATCH_FINISHED, BATCH_RESULT, INSTANT_RESULT, RoiBatchRunner,
    pool_is_warm,
)
from .roi_model import AnalysisSession, Roi, RoiAnalysisModel, RoiStyle
from .roi_store import (
    analysis_directory, load_roi_stats, load_session, save_roi_stats,
    save_session, write_intensity_csv,
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

    #: The stats store changed since the last write; flushed by the
    #: dock pane's drain tick after STATS_SAVE_DEBOUNCE_S of quiet.
    _stats_dirty = Bool(False)
    _stats_dirty_since = Float(0.0)

    @property
    def session(self):
        return self.analysis_model.session

    # ------------------------------------------------------------------ #
    # Interaction modes                                                    #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:draw_ellipse_button")
    def _arm_draw_ellipse(self, event):
        self.analysis_model.interaction_mode = "draw_ellipse"

    @observe("analysis_model:draw_box_button")
    def _arm_draw_box(self, event):
        self.analysis_model.interaction_mode = "draw_box"

    @observe("analysis_model:draw_capsule_button")
    def _arm_draw_capsule(self, event):
        self.analysis_model.interaction_mode = "draw_capsule"

    @observe("analysis_model:draw_polygon_button")
    def _arm_draw_polygon(self, event):
        self.analysis_model.interaction_mode = "draw_polygon"

    @observe("analysis_model:calibrate_scale_button")
    def _arm_calibrate_scale(self, event):
        self.analysis_model.interaction_mode = "draw_scale"

    @observe("analysis_model:session, "
             "analysis_model:session:scale:metres_per_pixel")
    def _on_scale_changed(self, event):
        """Keep the status-row readout current: the bar alone cannot
        say whether a calibration was measured here or seeded."""
        scale = self.session.scale
        self.viewer_model.scale_text = (
            f"1 px = {format_length(scale.metres_per_pixel)}"
            if scale.calibrated() else "Scale: not set")

    @observe("analysis_model:show_background_ring")
    def _on_show_background_ring(self, event):
        if self.session.ring.show_on_canvas != event.new:
            self.session.ring.show_on_canvas = event.new
            self._save_config()

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
        roi = Roi(name=self.session.next_roi_name(), kind=kind,
                  geometry=[float(value) for value in geometry],
                  base_anchor=anchor,
                  style=RoiStyle(color=DEFAULT_ROI_COLORS[
                      len(self.session.rois) % len(DEFAULT_ROI_COLORS)]))
        self.session.rois.append(roi)
        self.analysis_model.interaction_mode = self._rest_mode()
        self._save_config()
        self._restart_batch_if_running()
        self._instant_stats(roi)

    @observe("analysis_model:canvas_roi_edited")
    def _on_canvas_roi_edited(self, event):
        roi_id, geometry = event.new
        roi = self.session.roi_by_id(roi_id)
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
        session = self.session
        roi = session.roi_by_id(self.analysis_model.selected_roi_id)
        if roi is None:
            self.analysis_model.progress_text = (
                "Select an ROI first (edit mode) to delete it")
            return
        session.rois.remove(roi)
        self.analysis_model.selected_roi_id = ""
        self._save_config()
        self._restart_batch_if_running()

    @observe("analysis_model:clear_rois_button")
    def _clear_rois(self, event):
        session = self.session
        if not session.rois:
            return
        if confirm(message="Remove ALL ROIs (and their drift "
                           "overrides)?") != YES:
            return
        self.runner.cancel()
        self._pending_export = False
        session.rois = []
        self.analysis_model.selected_roi_id = ""
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self._save_config()

    @observe("analysis_model:reset_cache_button")
    def _reset_cache(self, event):
        result = confirm(
            message="Reset the calculated ROI intensities?",
            cancel=True, yes_label="Cache only",
            no_label="Drift also?")
        if result not in (YES, NO):
            return
        session = self.session
        self.runner.cancel()
        self._pending_export = False
        session.stats = {}
        session.stats_revision += 1
        self._mark_stats_dirty()
        self.flush_stats(force=True)
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        if result == NO:
            for roi in session.rois:
                roi.clear_overrides()
            self._save_config()

    # ------------------------------------------------------------------ #
    # Batch orchestration                                                  #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:calculate_button")
    def _calculate(self, event):
        self._start_batch()

    @observe("analysis_model:export_csv_button")
    def _export(self, event):
        if not self.session.rois or not self.viewer_model.paths:
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
        """The filtered series changed mid-batch: restart on the new
        snapshot (the work list is a snapshot by design; the plot pane
        observes the filters itself)."""
        self._restart_batch_if_running()

    def _missing_work(self):
        """[(path_str, {roi_id: (kind, geometry)}), ...] for every
        filtered image with at least one uncached (image, ROI) pair —
        only the missing ROIs are dispatched per image."""
        session = self.session
        stat_cache = {}
        work = []
        for path in self.viewer_model.paths:
            missing = {}
            for roi in session.rois:
                key = session.cache_key(path, roi, stat_cache)
                if key not in session.stats:
                    missing[roi.roi_id] = (roi.kind,
                                           tuple(key[4]))
                    self._dispatched_keys[(str(path), roi.roi_id)] = key
            if missing:
                work.append((str(path), missing,
                             (session.ring.gap_px,
                              session.ring.thickness_px)))
        return work

    def _start_batch(self, work=None):
        if not self.session.rois or not self.viewer_model.paths:
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
            if self._pending_export:
                self._write_export()
            return
        self.analysis_model.batch_running = True
        if pool_is_warm():
            self._update_progress_text()
        else:
            # First batch of the session: the pool spawns before any
            # image can finish, so say that rather than sit at 0/N.
            self.analysis_model.progress_text = (
                f"Starting workers for {len(work)} images…")
        self.runner.start(work)

    def _restart_batch_if_running(self):
        if self.analysis_model.batch_running:
            self._start_batch()

    def drain_results(self):
        """Called by the dock pane's drain QTimer (GUI thread): move
        finished results from the runner's queue into the model.

        The count advances one image at a time, so the readout reads
        1/N, 2/N, 3/N — the editor showing it repaints on each write.
        What stays coalesced is the expensive part: a stats_revision
        bump redraws the plot, refitting every ROI, and doing that per
        result starved the GUI that has to paint the progress."""
        absorbed = False
        finished = False
        while True:
            try:
                kind, payload = self.runner.results.get_nowait()
            except queue.Empty:
                break
            if kind == BATCH_RESULT:
                absorbed = self._absorb(payload) or absorbed
                self.analysis_model.batch_done += 1
                if payload["error"]:
                    self.analysis_model.batch_failed += 1
                    logger.warning(f"ROI stats failed for "
                                   f"{payload['path']}: {payload['error']}")
                self._update_progress_text()
            elif kind == INSTANT_RESULT:
                absorbed = self._absorb(payload) or absorbed
            elif kind == BATCH_FINISHED:
                finished = True
        if absorbed:
            self.session.stats_revision += 1
            self._mark_stats_dirty()
        if finished:
            self.analysis_model.batch_running = False
            self._update_progress_text(finished=True)
            self.flush_stats(force=True)
            if self._pending_export:
                self._write_export()

    def _absorb(self, payload):
        """True when anything landed — the caller bumps the revision
        once per drain instead of once per result."""
        absorbed = False
        for roi_id, stats in payload["stats"].items():
            key = self._dispatched_keys.get((payload["path"], roi_id))
            if key is not None:
                self.session.stats[key] = stats
                absorbed = True
        return absorbed

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
        shown image; already-cached stats need no compute — the table
        reads the session cache directly."""
        current = self.viewer_model.current_path
        if not current:
            return
        key = self.session.cache_key(current, roi)
        self._dispatched_keys[(current, roi.roi_id)] = key
        if key in self.session.stats:
            return
        ring = self.session.ring
        self.runner.compute_single(
            current, {roi.roi_id: (roi.kind, tuple(key[4]))},
            (ring.gap_px, ring.thickness_px))

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
            save_session(directory, self.session)
        except Exception as error:
            logger.warning(f"Could not save ROI config: {error}")

    def _mark_stats_dirty(self):
        self._stats_dirty_since = time.monotonic()
        self._stats_dirty = True

    def flush_stats(self, force=False):
        """Write the stats store if it changed — debounced (waits
        STATS_SAVE_DEBOUNCE_S seconds of quiet since the last change
        before writing) unless ``force``d (batch finish, session swap,
        reset)."""
        if not self._stats_dirty:
            return
        if not force and (time.monotonic() - self._stats_dirty_since
                          < STATS_SAVE_DEBOUNCE_S):
            return
        directory = self.session.directory
        if not directory:
            self._stats_dirty = False
            return
        try:
            save_roi_stats(directory, self.session.stats)
            self._stats_dirty = False
        except Exception as error:
            logger.warning(f"Could not save ROI stats: {error}")

    @observe("viewer_model:browsed_directory")
    def _on_experiment_changed(self, event):
        """A different folder is being browsed: swap in its saved
        session wholesale (ROIs, styles, figure settings), persisting
        the outgoing experiment's stats first."""
        self.runner.cancel()
        self._pending_export = False
        self.flush_stats(force=True)
        self.analysis_model.batch_running = False
        self.analysis_model.progress_text = ""
        self.analysis_model.selected_roi_id = ""
        directory = self._experiment_directory()
        session = (load_session(directory) if directory is not None
                   else AnalysisSession())
        if directory is not None:
            session.stats = load_roi_stats(directory)
            session.stats_revision += 1
        preferences = self.viewer_model.preferences
        seed = preferences.fluorescence_last_scale_metres_per_px
        if not session.scale.calibrated() and seed > 0:
            # Seed from the last calibration and write it straight into
            # this experiment, so its record states what it was measured
            # with instead of drifting with later calibrations.
            session.scale.trait_set(
                metres_per_pixel=seed,
                unit=preferences.fluorescence_last_scale_unit)
            if directory is not None:
                try:
                    save_session(directory, session)
                except Exception as error:
                    logger.warning(f"Could not seed the scale: {error}")
        self.analysis_model.session = session
        self.analysis_model.show_background_ring =             session.ring.show_on_canvas
        self._dispatched_keys = {}

    @observe("analysis_model:session:plot_stat, "
             "analysis_model:session:figure:export_format, "
             "analysis_model:session:figure:export_dpi, "
             "analysis_model:session:figure:x_auto, "
             "analysis_model:session:figure:x_min, "
             "analysis_model:session:figure:x_max, "
             "analysis_model:session:figure:y_auto, "
             "analysis_model:session:figure:y_min, "
             "analysis_model:session:figure:y_max, "
             "analysis_model:session:figure:fit_method, "
             "analysis_model:session:figure:trim_poor_fit, "
             "analysis_model:session:figure:show_legend, "
             "analysis_model:session:figure:show_fit_equations, "
             "analysis_model:session:figure:show_second_derivative_max, "
             "analysis_model:session:figure:show_second_derivative_min, "
             "analysis_model:session:figure:second_derivative_vline, "
             "analysis_model:session:figure:second_derivative_hline, "
             "analysis_model:session:figure:second_derivative_coords, "
             "analysis_model:session:figure:view_mode, "
             "analysis_model:session:figure:log_x, "
             "analysis_model:session:figure:log_y, "
             "analysis_model:session:figure:normalize, "
             "analysis_model:session:figure:subtract_first, "
             "analysis_model:session:rois:items:name, "
             "analysis_model:session:rois:items:style:color, "
             "analysis_model:session:rois:items:style:line_style, "
             "analysis_model:session:rois:items:style:marker, "
             "analysis_model:session:rois:items:style:marker_size, "
             "analysis_model:session:rois:items:style:visible, "
             "analysis_model:session:rois:items:style:alpha, "
             "analysis_model:session:scale:metres_per_pixel, "
             "analysis_model:session:scale:value, "
             "analysis_model:session:scale:unit, "
             "analysis_model:session:ring:gap_px, "
             "analysis_model:session:ring:thickness_px, "
             "analysis_model:session:ring:show_on_canvas")
    def _on_plot_settings_changed(self, event):
        self._save_config()

    @observe("viewer_model:paths.items")
    def _mirror_filtered_paths(self, event):
        self.analysis_model.filtered_paths = [
            str(path) for path in self.viewer_model.paths]

    @observe("viewer_model:current_path")
    def _mirror_current_image(self, event):
        self.analysis_model.current_image_path = \
            self.viewer_model.current_path

    def _write_export(self):
        self._pending_export = False
        directory = self._experiment_directory()
        if directory is None:
            self.analysis_model.progress_text = "No experiment folder"
            return
        session = self.session
        paths = list(self.viewer_model.paths)
        stat_cache = {}
        times = [session.stat_info(path, stat_cache)[1] for path in paths]
        start_time = times[0] if times else 0.0
        rows = []
        for path, capture_time in zip(paths, times):
            stats_by_roi = {}
            for roi in session.rois:
                stats = session.stats.get(
                    session.cache_key(path, roi, stat_cache))
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
        scale = session.scale
        try:
            write_intensity_csv(
                csv_path, rows, session.rois,
                pixel_area(scale.metres_per_pixel, scale.unit),
                area_unit(scale.metres_per_pixel, scale.unit),
                session.plot_stat if session.figure.normalize else None)
        except Exception as error:
            logger.warning(f"CSV export failed: {error}")
            self.analysis_model.progress_text = f"Export failed: {error}"
            return
        self.analysis_model.progress_text = f"Exported {csv_path.name}"
        logger.info(f"ROI intensities exported to {csv_path}")

    def _group_of(self, path):
        """The image-group (burst folder) name a capture belongs to."""
        burst_dir = Path(path).parent.parent
        browsed = self.viewer_model.browsed_directory
        if browsed and burst_dir == Path(browsed):
            return UNGROUPED_BURST
        return burst_dir.name
