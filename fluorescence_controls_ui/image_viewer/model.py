"""Qt-free HasTraits model for the image viewer pane: the browsed folder,
its discovered images, the loaded pixel data, the display window, and the
slideshow state. Mutated only on the GUI thread (button events, timers,
the controller's loader), so no Qt bridging is needed.
"""
from traits.api import (
    Any, Bool, Button, Directory, Event, HasTraits, Instance, Int, List,
    Property, Str, observe,
)
from traits.observation.api import parse

from microdrop_utils.traitsui_qt_helpers import RangeWithViewHints

from ..consts import PERSISTED_VIEWER_TRAITS
from ..preferences import FluorescencePreferences

#: The wavelength filter's no-filter choice.
WAVELENGTH_FILTER_ALL = "All"


class FluorescenceImageViewerModel(HasTraits):
    """State for the 16-bit capture viewer."""

    #: Folder being browsed. '' follows the current experiment's raw-captures
    #: folder; the folder button points it elsewhere.
    directory = Directory()

    #: The RESOLVED folder the last rescan looked at (the experiment's
    #: captures dir when ``directory`` is ''); display-only — drives the
    #: dock pane's "Name - folder" title.
    browsed_directory = Str()

    #: Section collapse toggles (controls-pane parity; not persisted).
    #: Experiments starts collapsed — it is the occasional "browse another
    #: experiment" affordance, not the everyday view.
    show_experiments = Bool(False)
    show_bursts = Bool(True)
    show_images = Bool(True)
    show_contrast = Bool(True)

    #: Experiment folders that hold captures: ``[(name, captures_path), ...]``
    #: oldest first (discovery.discover_experiments). Selecting one repoints
    #: the viewer at that experiment's captures (``directory``).
    experiments = List()
    experiment_names = Property(List(Str), observe="experiments.items")
    selected_experiment = Str()
    experiment_index = Int(0)
    experiment_number = Property(Int, observe="experiment_index")
    max_experiment_number = Property(Int, observe="experiments.items")

    #: Discovered bursts: ``[(burst_name, [paths...]), ...]``, oldest
    #: first (discovery.discover_bursts). The VISIBLE image list below is
    #: the selected burst's paths through the wavelength filter.
    bursts = List()

    #: Burst dropdown choices (mirrors ``bursts``) and its selection.
    burst_names = Property(List(Str), observe="bursts.items")
    selected_burst = Str()

    #: Burst seek-slider position within ``bursts``.
    burst_index = Int(0)
    max_burst_index = Property(Int, observe="bursts.items")

    #: Wavelength filter: "All" plus every wavelength detected across the
    #: discovered files (discovery.detect_wavelength).
    wavelength_names = List(Str, value=[WAVELENGTH_FILTER_ALL])
    selected_wavelength = Str(WAVELENGTH_FILTER_ALL)

    #: Images shown for the current burst + filter (Path objects), oldest
    #: first. The dropdown / seek slider / position readout follow this.
    paths = List()

    #: Path of the displayed image ('' before the first load). Setting it
    #: is the ONE way an image gets shown — the controller loads it into
    #: ``array``.
    current_path = Str()

    #: Loaded pixel data (numpy uint16/uint8, gray or RGB), or None.
    array = Any()

    #: "name — WxH 16-bit gray" summary of the loaded image.
    info_text = Str()

    #: "(x, y) = value" readout under the cursor (true stored values).
    pixel_text = Str()

    #: Basename choices for the image dropdown (mirrors ``paths``).
    image_names = Property(List(Str), observe="paths.items")

    #: Basename of the displayed image — the dropdown selection ('' when
    #: showing an image from outside the browsed folder).
    selected_image = Str()

    #: Seek-slider position within ``paths``.
    image_index = Int(0)
    max_image_index = Property(Int, observe="paths.items")

    #: 1-based twins of the seek indices — what the sliders BIND to, so
    #: the view counts 1..N while every internal index stays 0-based.
    image_number = Property(Int, observe="image_index")
    max_image_number = Property(Int, observe="paths.items")
    burst_number = Property(Int, observe="burst_index")
    max_burst_number = Property(Int, observe="bursts.items")

    # Display window: percentile auto-contrast, or the manual min/max pair.
    auto_contrast = Bool(True, desc="Window the displayed intensities to "
                                    "the 0.1–99.9 percentile range")

    #:  Min/Max sliders — calibrates their scale (e.g. 4095 for 12-bit data).
    #: upper bound of the Min/Max sliders. Max - 1
    _max_window_min = Property(observe="window_max")

    window_min = RangeWithViewHints(
        0.0,
        "_max_window_min",
        0.0,
        desc="intensity displayed as black"
    )
    window_max = RangeWithViewHints(
        1.0,
        65535.0,
        10000.0,
        desc="intensity displayed as white"
    )

    #: Slideshow auto-advance (the play/pause toggle).
    playing = Bool(False)

    #: One-shot request to refit the image to the pane.
    fit_request = Event()

    # Toolbar buttons (view events; the controller reacts).
    directory_button = Button()
    #: Back to the current experiment's raw-captures folder (newest image).
    home_button = Button()
    fit_button = Button()
    previous_button = Button()
    next_button = Button()

    #: Persistence backing for the display window (two-way: edits push to
    #: preferences, external preference changes pull back) — the same
    #: pattern as FluorescenceStatusModel's control values.
    preferences = Instance(FluorescencePreferences, FluorescencePreferences())

    #: Guards the two-way preferences sync against echoing its own writes
    #: (declared trait, so the pull observer can read it in any ordering).
    _self_preference_change = Bool(False)

    #: "n/N" position across ALL the experiment's images ("–/N" when showing
    #: an image from elsewhere, '' when nothing is discovered) — the arrows
    #: traverse the whole experiment, so the counter spans every image group.
    position_text = Property(
        Str, observe=("bursts.items, burst_index, selected_wavelength, "
                      "paths.items, current_path"))

    def traits_init(self):
        self._self_preference_change = True
        self.trait_set(**{
            model_trait: getattr(self.preferences, preference_trait)
            for model_trait, preference_trait
            in PERSISTED_VIEWER_TRAITS.items()})
        self._self_preference_change = False

    @observe(f"[{','.join(PERSISTED_VIEWER_TRAITS)}]", post_init=True)
    def _push_preferences(self, event):
        self._self_preference_change = True
        setattr(self.preferences,
                PERSISTED_VIEWER_TRAITS[event.name], event.new)
        self._self_preference_change = False

    @observe(parse("preferences").match(
        lambda name, trait: name in set(PERSISTED_VIEWER_TRAITS.values())))
    def _pull_preferences(self, event):
        if self._self_preference_change:
            return
        for model_trait, preference_trait in PERSISTED_VIEWER_TRAITS.items():
            if preference_trait == event.name:
                self.trait_set(**{model_trait: event.new})

    def _get_image_names(self):
        return [path.name for path in self.paths]

    def _get_max_image_index(self):
        return max(len(self.paths) - 1, 0)

    def _get_burst_names(self):
        return [name for name, _paths in self.bursts]

    def _get_max_burst_index(self):
        return max(len(self.bursts) - 1, 0)

    def _get_experiment_names(self):
        return [name for name, _captures in self.experiments]

    def _get_experiment_number(self):
        return self.experiment_index + 1

    def _set_experiment_number(self, value):
        self.experiment_index = value - 1

    def _get_max_experiment_number(self):
        return max(len(self.experiments), 1)

    def experiment_captures(self, name):
        """The named experiment's captures dir, or None for an unknown name."""
        for exp_name, captures in self.experiments:
            if exp_name == name:
                return captures
        return None

    def _get_image_number(self):
        return self.image_index + 1

    def _set_image_number(self, value):
        self.image_index = value - 1

    def _get_max_image_number(self):
        return max(len(self.paths), 1)

    def _get_burst_number(self):
        return self.burst_index + 1

    def _set_burst_number(self, value):
        self.burst_index = value - 1

    def _get_max_burst_number(self):
        return max(len(self.bursts), 1)

    def burst_paths(self, burst_name):
        """The named burst's images, or [] for an unknown name."""
        for name, paths in self.bursts:
            if name == burst_name:
                return list(paths)
        return []

    def visible_of(self, paths):
        """``paths`` reduced by the active wavelength filter (all when the
        filter is "All"). The single source of the filter rule — the
        controller's visible-list build and the experiment-wide position
        counter both go through it."""
        if self.selected_wavelength == WAVELENGTH_FILTER_ALL:
            return list(paths)
        from .discovery import detect_wavelength
        return [path for path in paths
                if detect_wavelength(path) == self.selected_wavelength]

    def _get_position_text(self):
        """Position across every image group in the experiment (the arrows
        traverse them all), through the active wavelength filter — the
        images actually reachable. ``self.paths`` is already the current
        group's filtered list; the groups before it contribute their filtered
        counts."""
        total = sum(len(self.visible_of(paths)) for _name, paths in self.bursts)
        if total == 0:
            return ""
        before = sum(len(self.visible_of(paths))
                     for _name, paths in self.bursts[:self.burst_index])
        index = self.path_index()
        if index is not None:
            return f"{before + index + 1}/{total}"
        return f"–/{total}"

    def _get__max_window_min(self):
        return self.window_max - 1

    def path_index(self):
        """Index of the displayed image within ``paths``, or None when it
        came from elsewhere (or nothing is loaded)."""
        strings = [str(path) for path in self.paths]
        if self.current_path in strings:
            return strings.index(self.current_path)
        return None
