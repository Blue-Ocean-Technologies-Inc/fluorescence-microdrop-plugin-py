"""Qt-free ROI analysis state: the ROI definitions (shared base geometry
plus forward drift-overrides), the intensity-stats cache, and batch
progress. Mutated only on the GUI thread (button events and the dock
pane's drain timer), so no Qt bridging is needed."""
import re
import uuid
from pathlib import Path

from traits.api import (
    Bool, Button, Dict, Enum, Event, Float, HasTraits, Instance, Int, List,
    Range, Str,
)

from ..discovery import capture_timestamp
from ..scale_bar import DEFAULT_UNIT, UNITS
from .consts import VIEW_MODES
from .curve_fit import FIT_METHODS

#: Matches the "ROI N" names next_roi_name() itself produces, to find
#: the next free number.
ROI_NAME_PATTERN = re.compile(r"^ROI (\d+)$")

#: Stats the plot can show. "bg_corrected" is interior mean minus the
#: outline-ring mean — the standard fluorescence background correction
#: the ring exists for. The last four are size-aware: "integrated" is
#: the ROI's total signal, and "per_area" its density — which is the
#: mean times a constant, since the pixel counts cancel (see the
#: area-statistics design note).
PLOT_STATS = ("mean", "bg_corrected", "median", "min", "max",
              "outline_mean", "integrated", "bg_integrated",
              "per_area", "bg_per_area")


class RoiStyle(HasTraits):
    """Plot styling for one ROI's line (persisted per experiment)."""

    color = Str("#1f77b4")
    line_style = Enum("solid", "dashed", "dotted", "dashdot")
    marker = Enum("none", ".", "o", "s", "^", "x")
    marker_size = Float(4.0)

    #: Whether this ROI is drawn on the figure at all, and how opaque —
    #: the device viewer's eye/alpha pair, as a percentage. Both are
    #: display-only: a hidden ROI is still computed, still listed in the
    #: stats table, and still exported to CSV. Range needs the explicit
    #: default, or it would start every ROI fully transparent.
    visible = Bool(True)
    alpha = Range(0, 100, 100, mode="spinner")

    @property
    def plot_alpha(self):
        """``alpha`` as the 0-1 fraction matplotlib wants."""
        return self.alpha / 100.0


class FigureSettings(HasTraits):
    """Figure-level plot settings (axis limits and export defaults)."""

    x_auto = Bool(True)
    x_min = Float(0.0)
    x_max = Float(1.0)
    y_auto = Bool(True)
    y_min = Float(0.0)
    y_max = Float(1.0)
    export_format = Enum("png", "svg", "pdf", "tiff")
    export_dpi = Enum(300, 150, 600)
    fit_method = Enum(*FIT_METHODS)
    #: Refit on a shorter leading slice when R² is poor, for series
    #: whose tail the model does not describe (a bleached plateau).
    trim_poor_fit = Bool(False)
    show_legend = Bool(True)
    #: Corner box with each ROI's fitted equation.
    show_fit_equations = Bool(False)
    #: Mark where the fitted curve's second derivative peaks/troughs.
    show_second_derivative_max = Bool(False)
    show_second_derivative_min = Bool(False)
    #: Marker dressing for the enabled extrema.
    second_derivative_vline = Bool(True)
    second_derivative_hline = Bool(False)
    second_derivative_coords = Bool(True)
    #: Which chart the plot pane renders.
    view_mode = Enum(*VIEW_MODES)


class ScaleCalibration(HasTraits):
    """Image scale for the on-canvas bar (persisted per experiment).
    Display-only: nothing computed from the images depends on it."""

    #: Metres one image pixel spans; 0.0 means not calibrated.
    metres_per_pixel = Float(0.0)
    #: What the user typed, kept for the readout and for re-editing.
    value = Float(0.0)
    #: Enum's first argument is the default, so mm wins over m.
    unit = Enum(DEFAULT_UNIT, UNITS)
    show_bar = Bool(True)

    def calibrated(self):
        return self.metres_per_pixel > 0.0


class Roi(HasTraits):
    """One region of interest: a shared base geometry applying everywhere,
    plus optional overrides anchored at capture times that apply from
    their anchor forward (drift compensation)."""

    #: Stable identity used in cache keys and result columns.
    roi_id = Str()

    #: Display name (also the CSV column prefix and plot legend label).
    name = Str()

    #: Shape, with the geometry lists roi_geometry defines: ellipse
    #: [cx, cy, rx, ry, angle], box [x, y, width, height, angle] with
    #: (x, y) the unrotated top-left corner, capsule [cx, cy,
    #: half_length, radius, angle], polygon [x1, y1, x2, y2, ...] (a
    #: contour's vertex list, with any rotation already applied to the
    #: coordinates). All values are image-pixel floats bar the angle,
    #: which is degrees clockwise.
    kind = Enum("ellipse", "box", "capsule", "polygon")

    #: Base geometry, applying to every image without a later override.
    geometry = List(Float)

    #: Capture time of the image the ROI was created on — edits at or
    #: before it update the base instead of adding an override.
    base_anchor = Float(0.0)

    #: anchor capture time -> geometry; an override applies from its
    #: anchor forward until the next override.
    overrides = Dict(Float, List)

    #: Plot styling (line color/style/marker); persisted with the ROI.
    style = Instance(RoiStyle, ())

    def _roi_id_default(self):
        return uuid.uuid4().hex[:8]

    def effective_geometry(self, capture_time):
        """The geometry in force for an image captured at
        ``capture_time``: the override with the greatest anchor at or
        before it, else the base geometry."""
        anchors = [anchor for anchor in self.overrides
                   if anchor <= capture_time]
        if anchors:
            return list(self.overrides[max(anchors)])
        return list(self.geometry)

    def apply_edit(self, capture_time, geometry):
        """Record an edit made while viewing the image captured at
        ``capture_time``: at or before the base anchor it updates the
        base, later it upserts a forward override."""
        if capture_time <= self.base_anchor:
            self.geometry = list(geometry)
        else:
            self.overrides[capture_time] = list(geometry)

    def clear_overrides(self):
        self.overrides = {}


class AnalysisSession(HasTraits):
    """Everything belonging to one experiment's analysis, swapped
    wholesale when the browsed experiment changes: the ROI set, the
    computed-stats store, and the plot configuration."""

    #: Experiment directory this session was loaded from ('' = none).
    directory = Str()

    rois = List(Instance(Roi))

    #: (path str, mtime, roi_id, kind, geometry tuple) -> stats dict.
    #: The geometry in the key makes invalidation implicit: an edit only
    #: misses on the images its override actually covers.
    stats = Dict()

    #: Bumped after every drain absorption and after a store load — Dict
    #: item writes don't notify, so observers watch this instead.
    stats_revision = Int(0) #TODO: convert to Event trait

    #: Which stat the plot shows.
    plot_stat = Enum(*PLOT_STATS)

    figure = Instance(FigureSettings, ())

    #: Image scale for the canvas bar (display-only).
    scale = Instance(ScaleCalibration, ())

    def roi_by_id(self, roi_id):
        for roi in self.rois:
            if roi.roi_id == roi_id:
                return roi
        return None

    def next_roi_name(self):
        """'ROI N' with N one past the highest numbered existing ROI
        name, so a deleted ROI's number isn't reissued to collide with
        a surviving one (duplicate names would double up CSV columns
        and plot legend labels)."""
        highest = 0
        for roi in self.rois:
            match = ROI_NAME_PATTERN.match(roi.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"ROI {highest + 1}"

    def stat_info(self, path, stat_cache=None):
        """(mtime, capture_time) for ``path``. Pass a dict as
        ``stat_cache`` (path str -> (mtime, capture_time)) to memoize
        the filesystem stat and timestamp parse across many calls in
        the same pass (a rebuild calls this once per image, cache_key()
        once per image per ROI)."""
        key = str(path)
        if stat_cache is not None and key in stat_cache:
            return stat_cache[key]
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        info = (mtime, capture_timestamp(path))
        if stat_cache is not None:
            stat_cache[key] = info
        return info

    def cache_key(self, path, roi, stat_cache=None):
        """Cache key for one (image, ROI) pair: the file identity/mtime
        plus the geometry in force at the image's capture time. Pass
        ``stat_cache`` through from stat_info() to avoid re-stating the
        same path for every ROI."""
        mtime, capture_time = self.stat_info(path, stat_cache)
        return (str(path), mtime, roi.roi_id, roi.kind,
                tuple(roi.effective_geometry(capture_time)))

    def effective_for(self, path):
        """[(roi_id, name, kind, geometry), ...] in force for ``path`` —
        what the canvas draws and the batch computes for that image."""
        capture_time = capture_timestamp(path)
        return [(roi.roi_id, roi.name, roi.kind,
                 roi.effective_geometry(capture_time))
                for roi in self.rois]


class RoiAnalysisModel(HasTraits):
    """Shared tool-state between the viewer pane (ROI editing,
    toolbuttons) and the plot pane; the per-experiment data lives in
    ``session``."""

    #: Canvas interaction: pan (normal navigation), one-shot draw modes,
    #: or edit (move/resize/select existing ROIs).
    interaction_mode = Enum("pan", "draw_ellipse", "draw_box",
                            "draw_capsule", "draw_polygon", "draw_scale",
                            "edit")

    #: roi_id of the canvas-selected ROI (edit mode), '' when none.
    selected_roi_id = Str()

    #: Batch progress readout ("12/40, 1 failed"; '' when idle).
    progress_text = Str()
    batch_total = Int(0)
    batch_done = Int(0)
    batch_failed = Int(0)
    batch_running = Bool(False)

    # Toolbar buttons (view events; RoiAnalysisController reacts).
    draw_ellipse_button = Button()
    draw_box_button = Button()
    draw_capsule_button = Button()
    draw_polygon_button = Button()
    calibrate_scale_button = Button()

    #: Live mirror of session.scale.show_bar — the toolbar is built
    #: once against this model while sessions swap underneath it.
    show_scale_bar = Bool(True)
    edit_mode = Bool(False)
    delete_roi_button = Button()
    clear_rois_button = Button()
    calculate_button = Button()
    export_csv_button = Button()
    reset_cache_button = Button()
    #: Render the current plot to an image file at the session's export
    #: settings (handled by the plot dock pane, which owns the canvas).
    save_plot_button = Button()
    #: Open the non-modal table of fitted equations per ROI.
    fit_equations_button = Button()

    #: View -> controller channels fired by the canvas ROI layer.
    canvas_roi_created = Event()   # (kind, geometry)
    canvas_roi_edited = Event()    # (roi_id, geometry)

    #: The per-experiment analysis state (swapped on experiment change).
    session = Instance(AnalysisSession, ())

    #: Mirrors of the viewer's filtered image list and displayed image
    #: (str paths), maintained by RoiAnalysisController so the plot
    #: pane and stats table never need the viewer model.
    filtered_paths = List(Str)
    current_image_path = Str()


#: The single analysis state shared by the viewer pane and the plot pane
#: (both owned by this plugin) — the media_capture_event_model pattern.
roi_analysis_model = RoiAnalysisModel()
