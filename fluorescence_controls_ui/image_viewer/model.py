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


class FluorescenceImageViewerModel(HasTraits):
    """State for the 16-bit capture viewer."""

    #: Folder being browsed. '' follows the current experiment's raw-captures
    #: folder; the folder button points it elsewhere.
    directory = Directory()

    #: Discovered images in the browsed folder (Path objects), oldest first.
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

    #: "n/N" position within the discovered images ("–/N" when showing an
    #: image from elsewhere, '' when nothing is discovered).
    position_text = Property(Str, observe="paths.items, current_path")

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

    def _get_position_text(self):
        index = self.path_index()
        if index is not None:
            return f"{index + 1}/{len(self.paths)}"
        if self.paths:
            return f"–/{len(self.paths)}"
        return ""

    def _get__max_window_min(self):
        return self.window_max - 1

    def path_index(self):
        """Index of the displayed image within ``paths``, or None when it
        came from elsewhere (or nothing is loaded)."""
        strings = [str(path) for path in self.paths]
        if self.current_path in strings:
            return strings.index(self.current_path)
        return None

    def relative_path(self, step):
        """The discovered image ``step`` away from the current one
        (wrapping). From an image opened outside the list, stepping enters
        the list at its start/end. None when nothing is discovered."""
        if not self.paths:
            return None
        index = self.path_index()
        if index is not None:
            index = (index + step) % len(self.paths)
        else:
            index = 0 if step > 0 else len(self.paths) - 1
        return self.paths[index]
