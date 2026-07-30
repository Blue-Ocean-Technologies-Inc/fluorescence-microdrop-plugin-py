"""Qt-free ROI analysis state: the ROI definitions (shared base geometry
plus forward drift-overrides), the intensity-stats cache, batch progress,
and the plot-ready series. Mutated only on the GUI thread (button events
and the dock pane's drain timer), so no Qt bridging is needed."""
import uuid
from pathlib import Path

from traits.api import (
    Bool, Button, Dict, Enum, Event, Float, HasTraits, Instance, Int, List,
    Str,
)

from ..discovery import capture_timestamp


class Roi(HasTraits):
    """One region of interest: a shared base geometry applying everywhere,
    plus optional overrides anchored at capture times that apply from
    their anchor forward (drift compensation)."""

    #: Stable identity used in cache keys and result columns.
    roi_id = Str()

    #: Display name (also the CSV column prefix and plot legend label).
    name = Str()

    #: Shape. Circle geometry is [center_x, center_y, radius]; box
    #: geometry is [x, y, width, height] with (x, y) the top-left corner.
    #: All values are image-pixel floats.
    kind = Enum("circle", "box")

    #: Base geometry, applying to every image without a later override.
    geometry = List(Float)

    #: Capture time of the image the ROI was created on — edits at or
    #: before it update the base instead of adding an override.
    base_anchor = Float(0.0)

    #: anchor capture time -> geometry; an override applies from its
    #: anchor forward until the next override.
    overrides = Dict(Float, List)

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


class RoiAnalysisModel(HasTraits):
    """Shared state between the viewer pane (ROI editing, toolbuttons)
    and the plot pane (series display)."""

    rois = List(Instance(Roi))

    #: Canvas interaction: pan (normal navigation), one-shot draw modes,
    #: or edit (move/resize/select existing ROIs).
    interaction_mode = Enum("pan", "draw_circle", "draw_box", "edit")

    #: roi_id of the canvas-selected ROI (edit mode), '' when none.
    selected_roi_id = Str()

    #: (path str, mtime, roi_id, kind, geometry tuple) -> stats dict.
    #: The geometry in the key makes invalidation implicit: an edit only
    #: misses on the images its override actually covers.
    cache = Dict()

    #: Instant-stats readout for the ROI just drawn/edited.
    roi_info_text = Str()

    #: Batch progress readout ("12/40, 1 failed"; '' when idle).
    progress_text = Str()
    batch_total = Int(0)
    batch_done = Int(0)
    batch_failed = Int(0)
    batch_running = Bool(False)

    #: Plot-ready series: roi_id -> (name, [elapsed_sec...], [mean...]).
    plot_series = Dict()

    #: Bumped whenever plot_series is rebuilt (the plot canvas polls it).
    plot_revision = Int(0)

    # Toolbar buttons (view events; RoiAnalysisController reacts).
    draw_circle_button = Button()
    draw_box_button = Button()
    edit_mode = Bool(False)
    delete_roi_button = Button()
    clear_rois_button = Button()
    calculate_button = Button()
    export_csv_button = Button()
    reset_cache_button = Button()

    #: View -> controller channels fired by the canvas ROI layer.
    canvas_roi_created = Event()   # (kind, geometry)
    canvas_roi_edited = Event()    # (roi_id, geometry)

    def roi_by_id(self, roi_id):
        for roi in self.rois:
            if roi.roi_id == roi_id:
                return roi
        return None

    def next_roi_name(self):
        return f"ROI {len(self.rois) + 1}"

    def cache_key(self, path, roi):
        """Cache key for one (image, ROI) pair: the file identity/mtime
        plus the geometry in force at the image's capture time."""
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        return (str(path), mtime, roi.roi_id, roi.kind,
                tuple(roi.effective_geometry(capture_timestamp(path))))

    def effective_for(self, path):
        """[(roi_id, name, kind, geometry), ...] in force for ``path`` —
        what the canvas draws and the batch computes for that image."""
        capture_time = capture_timestamp(path)
        return [(roi.roi_id, roi.name, roi.kind,
                 roi.effective_geometry(capture_time))
                for roi in self.rois]


#: The single analysis state shared by the viewer pane and the plot pane
#: (both owned by this plugin) — the media_capture_event_model pattern.
roi_analysis_model = RoiAnalysisModel()
