"""Controller-level tests for the ROI editing ergonomics: draw tools
that stay armed, and copying a shape into a new ROI."""
from fluorescence_controls_ui.image_viewer.analysis.consts import (
    PASTE_OFFSET_PX,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_controller import (
    RoiAnalysisController,
)
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    RoiAnalysisModel,
)
from fluorescence_controls_ui.image_viewer.model import (
    FluorescenceImageViewerModel,
)


def _controller():
    """A controller over its own analysis model: the one the viewer
    model hands out is an app-wide singleton, so tests sharing it would
    inherit each other's ROIs."""
    return RoiAnalysisController(
        viewer_model=FluorescenceImageViewerModel(),
        analysis_model=RoiAnalysisModel())


def test_a_drawn_roi_leaves_the_tool_armed():
    controller = _controller()
    model = controller.analysis_model
    model.draw_ellipse_button = True
    model.canvas_roi_created = ("ellipse", [10.0, 10.0, 5.0, 5.0, 0.0])

    assert model.interaction_mode == "draw_ellipse"
    model.canvas_roi_created = ("ellipse", [40.0, 10.0, 5.0, 5.0, 0.0])
    assert len(controller.session.rois) == 2
    assert [roi.name for roi in controller.session.rois] == ["ROI 1",
                                                             "ROI 2"]


def test_clicking_the_armed_tool_puts_it_away():
    # Its button shows itself pressed, so a second click must release
    # it rather than re-arm what is already armed.
    controller = _controller()
    model = controller.analysis_model
    model.draw_capsule_button = True
    assert model.interaction_mode == "draw_capsule"
    model.draw_capsule_button = True
    assert model.interaction_mode == "pan"

    model.draw_capsule_button = True
    model.draw_box_button = True     # a different tool just switches
    assert model.interaction_mode == "draw_box"


def test_escaping_a_draw_tool_returns_to_the_resting_mode():
    controller = _controller()
    model = controller.analysis_model
    model.draw_box_button = True
    model.canvas_draw_cancelled = True
    assert model.interaction_mode == "pan"

    model.edit_mode = True          # resting mode follows the toggle
    model.draw_box_button = True
    model.canvas_draw_cancelled = True
    assert model.interaction_mode == "edit"


def test_copy_and_paste_offsets_the_shape_and_renames_it():
    controller = _controller()
    model = controller.analysis_model
    model.canvas_roi_created = ("box", [10.0, 20.0, 30.0, 40.0, 0.0, 5.0])
    (original,) = controller.session.rois
    model.selected_roi_id = original.roi_id

    model.copy_roi_button = True
    model.paste_roi_button = True

    original, pasted = controller.session.rois
    assert pasted.kind == "box"
    assert pasted.geometry == [10.0 + PASTE_OFFSET_PX,
                               20.0 + PASTE_OFFSET_PX,
                               30.0, 40.0, 0.0, 5.0]
    assert pasted.name == "ROI 2"
    assert pasted.roi_id != original.roi_id
    # A shared colour would make the two curves indistinguishable.
    assert pasted.style.color != original.style.color
    assert model.selected_roi_id == pasted.roi_id


def test_one_copy_seeds_repeated_pastes():
    controller = _controller()
    model = controller.analysis_model
    model.canvas_roi_created = ("ellipse", [10.0, 10.0, 5.0, 5.0, 0.0])
    model.selected_roi_id = controller.session.rois[0].roi_id
    model.copy_roi_button = True

    model.paste_roi_button = True
    model.paste_roi_button = True
    assert len(controller.session.rois) == 3
    # Each paste offsets from the copied shape, not from the last
    # paste, so repeated pastes stack in one place by design.
    assert controller.session.rois[1].geometry == \
        controller.session.rois[2].geometry


def test_delete_removes_the_selected_roi_and_says_so_when_there_is_none():
    controller = _controller()
    model = controller.analysis_model
    model.canvas_roi_created = ("ellipse", [10.0, 10.0, 5.0, 5.0, 0.0])
    model.selected_roi_id = controller.session.rois[0].roi_id

    model.delete_roi_button = True
    assert controller.session.rois == []
    assert model.selected_roi_id == ""

    model.delete_roi_button = True
    assert "Select an ROI" in model.progress_text


def test_copy_with_nothing_selected_and_paste_with_nothing_copied():
    controller = _controller()
    model = controller.analysis_model

    model.copy_roi_button = True
    assert model.clipboard_kind == ""
    assert "Select an ROI" in model.progress_text

    model.paste_roi_button = True
    assert controller.session.rois == []
    assert model.progress_text == "Nothing copied yet"


def test_saved_fit_presets_load_whichever_order_the_models_arrive():
    # Both models are constructor arguments and traits assigns them one
    # at a time, so the observer has to wait for the second. The pane
    # passes viewer_model first, which is the order that used to raise
    # inside the notifier and quietly leave the dropdown empty.
    from fluorescence_controls_ui.image_viewer.analysis.fit_presets import (
        save_presets,
    )

    viewer = FluorescenceImageViewerModel()
    viewer.preferences.fluorescence_fit_presets = save_presets(
        [("Bleach", "a*exp(-b*x) + c")])
    for kwargs in (dict(viewer_model=viewer,
                        analysis_model=RoiAnalysisModel()),
                   dict(analysis_model=RoiAnalysisModel(),
                        viewer_model=viewer)):
        controller = RoiAnalysisController(**kwargs)
        assert [name for name, _text
                in controller.analysis_model.fit_presets] == ["Bleach"]
