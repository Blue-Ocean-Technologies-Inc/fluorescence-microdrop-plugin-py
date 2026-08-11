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
from .consts import (
    DEFAULT_ROI_COLORS, PASTE_OFFSET_PX, STATS_SAVE_DEBOUNCE_S,
)
from .curve_fit import FIT_LABELS, fit_series
from .fit_presets import fit_arguments, load_presets, save_presets
from .plot_series import analysed_series
from .roi_geometry import translated
from .roi_batch import (
    BATCH_FINISHED, BATCH_RESULT, INSTANT_RESULT, RoiBatchRunner,
    pool_is_warm,
)
from .roi_model import AnalysisSession, Roi, RoiAnalysisModel, RoiStyle
from .roi_store import (
    analysis_directory, load_roi_stats, load_session, save_fit_equations,
    save_roi_stats, save_session, write_intensity_csv,
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

    #: When the running batch started, for the finished-in log line.
    _batch_started = Float(0.0)

    #: A drift re-check updated an ROI's geometry since the last save —
    #: flushed by drain_results() once per drain tick rather than once
    #: per tracked frame.
    _ai_config_dirty = Bool(False)

    @property
    def session(self):
        return self.analysis_model.session

    # ------------------------------------------------------------------ #
    # Saved fit equations (app-wide, so they live in preferences rather   #
    # than in any one experiment's config)                                #
    # ------------------------------------------------------------------ #
    @observe("viewer_model, analysis_model")
    def _load_fit_presets(self, event):
        """Both models are constructor arguments, and traits assigns
        them one at a time — so this watches both and acts when the
        second arrives, whichever order the caller passed them in."""
        if self.viewer_model is None or self.analysis_model is None:
            return
        self.analysis_model.fit_presets = load_presets(
            self.viewer_model.preferences.fluorescence_fit_presets)

    @observe("analysis_model:fit_presets.items, analysis_model:fit_presets")
    def _store_fit_presets(self, event):
        if self.viewer_model is None:
            return
        preferences = self.viewer_model.preferences
        stored = save_presets(list(self.analysis_model.fit_presets))
        if preferences.fluorescence_fit_presets != stored:
            preferences.fluorescence_fit_presets = stored

    # ------------------------------------------------------------------ #
    # Interaction modes                                                    #
    # ------------------------------------------------------------------ #
    def _arm(self, mode):
        """Arm a drawing tool, or put it away if it is the one already
        armed — its button shows itself pressed, so a second click
        releasing it is what that appearance promises."""
        model = self.analysis_model
        model.interaction_mode = (self._rest_mode()
                                  if model.interaction_mode == mode
                                  else mode)

    @observe("analysis_model:draw_ellipse_button")
    def _arm_draw_ellipse(self, event):
        self._arm("draw_ellipse")

    @observe("analysis_model:draw_box_button")
    def _arm_draw_box(self, event):
        self._arm("draw_box")

    @observe("analysis_model:draw_capsule_button")
    def _arm_draw_capsule(self, event):
        self._arm("draw_capsule")

    @observe("analysis_model:draw_polygon_button")
    def _arm_draw_polygon(self, event):
        self._arm("draw_polygon")

    @observe("analysis_model:calibrate_scale_button")
    def _arm_calibrate_scale(self, event):
        self._arm("draw_scale")

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

    @observe("analysis_model:rolling_ball_enabled")
    def _on_rolling_ball_toggled(self, event):
        if self.session.ball.enabled != event.new:
            self.session.ball.enabled = event.new
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
        # The tool stays armed: drawing a row of ROIs should not mean a
        # trip to the toolbar between each. Escape puts it away.
        kind, geometry = event.new
        self._create_roi(kind, geometry)

    @observe("analysis_model:canvas_draw_cancelled")
    def _on_canvas_draw_cancelled(self, event):
        self.analysis_model.interaction_mode = self._rest_mode()

    def _create_roi(self, kind, geometry):
        """Add an ROI anchored at the displayed image and start
        measuring it — the one path a drawn or pasted shape takes."""
        current = self.viewer_model.current_path
        anchor = capture_timestamp(current) if current else 0.0
        roi = Roi(name=self.session.next_roi_name(), kind=kind,
                  geometry=[float(value) for value in geometry],
                  base_anchor=anchor,
                  style=RoiStyle(color=DEFAULT_ROI_COLORS[
                      len(self.session.rois) % len(DEFAULT_ROI_COLORS)]))
        self.session.rois.append(roi)
        self._save_config()
        self._restart_batch_if_running()
        self._instant_stats(roi)
        return roi

    @observe("analysis_model:ai_rois_accepted")
    def _on_ai_rois_accepted(self, event):
        pairs, anchor = event.new
        self._create_rois(pairs, anchor)

    def _create_rois(self, pairs, anchor):
        """Bulk sibling of _create_roi for accepted AI candidates: one
        save and one batch restart for the whole set."""
        created = []
        for kind, geometry in pairs:
            roi = Roi(name=self.session.next_roi_name(), kind=kind,
                      geometry=[float(value) for value in geometry],
                      base_anchor=anchor,
                      style=RoiStyle(color=DEFAULT_ROI_COLORS[
                          len(self.session.rois) % len(DEFAULT_ROI_COLORS)]))
            self.session.rois.append(roi)
            created.append(roi)
        if not created:
            return created
        self._save_config()
        self._restart_batch_if_running()
        for roi in created:
            self._instant_stats(roi)
        return created

    @observe("analysis_model:ai_roi_tracked")
    def _on_ai_roi_tracked(self, event):
        roi_id, capture_time, geometry = event.new
        roi = self.session.roi_by_id(roi_id)
        if roi is not None:
            roi.apply_edit(capture_time,
                           [float(value) for value in geometry])
            self._ai_config_dirty = True

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
    # Copy / paste                                                         #
    # ------------------------------------------------------------------ #
    @observe("analysis_model:copy_roi_button")
    def _copy_roi(self, event):
        """Hold the selected ROI's shape as it stands on the displayed
        image — the shape the user is looking at, which a drift
        override may have moved away from the base geometry."""
        model = self.analysis_model
        roi = self.session.roi_by_id(model.selected_roi_id)
        if roi is None:
            model.progress_text = (
                "Select an ROI first (edit mode) to copy it")
            return
        current = self.viewer_model.current_path
        model.clipboard_kind = roi.kind
        model.clipboard_geometry = roi.effective_geometry(
            capture_timestamp(current) if current else 0.0)
        model.progress_text = f"Copied {roi.name}"

    @observe("analysis_model:paste_roi_button")
    def _paste_roi(self, event):
        """Place a copy, nudged clear of the original so it cannot hide
        under it. It gets its own name and the next colour in the
        cycle: two curves in one colour cannot be told apart."""
        model = self.analysis_model
        if not model.clipboard_kind:
            model.progress_text = "Nothing copied yet"
            return
        roi = self._create_roi(
            model.clipboard_kind,
            translated(model.clipboard_kind, model.clipboard_geometry,
                       PASTE_OFFSET_PX, PASTE_OFFSET_PX))
        model.selected_roi_id = roi.roi_id
        model.progress_text = f"Pasted {roi.name}"

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
            if session.is_excluded(path):
                continue
            missing = {}
            for roi in session.rois:
                key = session.cache_key(path, roi, stat_cache)
                if key not in session.stats:
                    missing[roi.roi_id] = (roi.kind,
                                           tuple(key[4]))
                    self._dispatched_keys[(str(path), roi.roi_id)] = key
            if missing:
                work.append((str(path), missing,
                             session.correction_key()))
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
        gap, width, ball = self.session.correction_key()
        logger.info(
            f"ROI batch: {len(work)} images x {len(self.session.rois)} "
            f"ROIs; ring gap={gap}px width={width}px; rolling ball="
            f"{f'r={ball}px' if ball else 'off'}")
        self._batch_started = time.monotonic()
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
            elapsed = time.monotonic() - (self._batch_started
                                          or time.monotonic())
            logger.info(
                f"ROI batch finished: {self.analysis_model.batch_done} "
                f"done, {self.analysis_model.batch_failed} failed, in "
                f"{elapsed:.1f}s")
            self._update_progress_text(finished=True)
            self.flush_stats(force=True)
            if self._pending_export:
                self._write_export()
        if self._ai_config_dirty:
            self._ai_config_dirty = False
            self._save_config()

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
        if not current or self.session.is_excluded(current):
            return
        key = self.session.cache_key(current, roi)
        self._dispatched_keys[(current, roi.roi_id)] = key
        if key in self.session.stats:
            return
        self.runner.compute_single(
            current, {roi.roi_id: (roi.kind, tuple(key[4]))},
            self.session.correction_key())

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
        self.analysis_model.rolling_ball_enabled = session.ball.enabled
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
             "analysis_model:session:figure:custom_expression, "
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
             "analysis_model:session:figure:subtract_background_ref, "
             "analysis_model:session:figure:remove_outliers, "
             "analysis_model:session:figure:outlier_threshold, "
             "analysis_model:session:figure:outlier_window, "
             "analysis_model:session:figure:smooth_method, "
             "analysis_model:session:figure:savgol_window, "
             "analysis_model:session:figure:savgol_order, "
             "analysis_model:session:figure:butter_order, "
             "analysis_model:session:figure:butter_cutoff, "
             "analysis_model:session:figure:show_method_group, "
             "analysis_model:session:figure:show_metrics_group, "
             "analysis_model:session:rois:items:name, "
             "analysis_model:session:rois:items:is_background_ref, "
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
             "analysis_model:session:ring:show_on_canvas, "
             "analysis_model:session:ball:enabled, "
             "analysis_model:session:ball:radius_px")
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

    # ------------------------------------------------------------------ #
    # Exclude-from-analysis (sidebar checkbox <-> session)                 #
    # ------------------------------------------------------------------ #
    #: Guards the checkbox observer while the mirror below writes it.
    _syncing_excluded = Bool(False)

    @observe("analysis_model:current_image_path, analysis_model:session")
    def _mirror_current_image_excluded(self, event):
        """Point the checkbox at the displayed image's exclusion state
        (image navigation and session swaps both land here)."""
        current = self.analysis_model.current_image_path
        self._syncing_excluded = True
        try:
            self.analysis_model.current_image_excluded = (
                bool(current) and self.session.is_excluded(current))
        finally:
            self._syncing_excluded = False

    @observe("analysis_model:current_image_excluded")
    def _on_current_image_excluded(self, event):
        """The checkbox was toggled by the user: mark/unmark the
        displayed image and re-run whatever is consuming the series."""
        if self._syncing_excluded:
            return
        current = self.analysis_model.current_image_path
        if not current:
            return
        name = Path(current).name
        excluded = list(self.session.excluded_images)
        if event.new and name not in excluded:
            self.session.excluded_images = excluded + [name]
        elif not event.new and name in excluded:
            self.session.excluded_images = [entry for entry in excluded
                                            if entry != name]
        else:
            return
        # The plot derives its series from the (now different) included
        # set; stats_revision is what it redraws on.
        self.session.stats_revision += 1
        self._save_config()
        self._restart_batch_if_running()

    def _write_export(self):
        self._pending_export = False
        directory = self._experiment_directory()
        if directory is None:
            self.analysis_model.progress_text = "No experiment folder"
            return
        session = self.session
        paths = [path for path in self.viewer_model.paths
                 if not session.is_excluded(path)]
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
        fitted, outlier_flags = self._analysed_series()
        self._write_fit_equations(directory, fitted)
        scale = session.scale
        try:
            write_intensity_csv(
                csv_path, rows, session.rois,
                pixel_area(scale.metres_per_pixel, scale.unit),
                area_unit(scale.metres_per_pixel, scale.unit),
                session.plot_stat if session.figure.normalize else None,
                session.correction_key(), outlier_flags)
        except Exception as error:
            logger.warning(f"CSV export failed: {error}")
            self.analysis_model.progress_text = f"Export failed: {error}"
            return
        self.analysis_model.progress_text = f"Exported {csv_path.name}"
        logger.info(f"ROI intensities exported to {csv_path}")

    def _analysed_series(self):
        """(series, outlier flags) for the export: the same pipeline
        the plot fits, less the visibility filter — a hidden ROI is a
        display choice, and the CSV has always carried them all."""
        return analysed_series(self.session,
                               self.analysis_model.filtered_paths,
                               visible_only=False)

    def _write_fit_equations(self, directory, series):
        """Record the fitted parameters beside the CSV, keyed by the
        equation — the numbers behind the curves the export describes,
        which the CSV itself has no column for. ``series`` is the
        analysed one, so these are the fits the plot drew."""
        session = self.session
        method, expression = fit_arguments(session.figure,
                                           self.analysis_model.fit_presets)
        if method == "none":
            return
        fits = {}
        for roi_id, (name, elapsed, values) in series.items():
            fit = fit_series(elapsed, values, method,
                             session.figure.trim_poor_fit, expression,
                             session.figure.initial_guesses)
            if fit is None:
                continue
            finite = [time for time, value in zip(elapsed, values)
                      if value == value]
            series_end = max(finite) if finite else fit.fitted_end
            fits[name] = {
                "params": fit.params,
                "r_squared": fit.r_squared,
                # The span actually solved on, and whether that is
                # short of the data — a parameter set from a trimmed
                # fit describes only that stretch, and read without
                # this it looks like it describes the whole series.
                "fitted_range_sec": [fit.fitted_start, fit.fitted_end],
                "trimmed": bool(fit.fitted_end < series_end),
            }
        try:
            equation = expression or FIT_LABELS.get(method, method)
            save_fit_equations(directory, equation, fits)
            logger.info(f"Fitted {len(fits)} ROIs to {equation!r} "
                        f"(trim={session.figure.trim_poor_fit})")
        except Exception as error:
            logger.warning(f"Could not write fit equations: {error}")

    def _group_of(self, path):
        """The image-group (burst folder) name a capture belongs to."""
        burst_dir = Path(path).parent.parent
        browsed = self.viewer_model.browsed_directory
        if browsed and burst_dir == Path(browsed):
            return UNGROUPED_BURST
        return burst_dir.name
