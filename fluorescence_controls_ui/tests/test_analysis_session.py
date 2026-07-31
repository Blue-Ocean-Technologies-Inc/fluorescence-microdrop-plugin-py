"""Session-object unit tests: defaults, name sequencing, and the
geometry-hashed cache keys on the session."""
from fluorescence_controls_ui.image_viewer.analysis.roi_model import (
    AnalysisSession, PLOT_STATS, Roi, RoiAnalysisModel,
)


def test_session_defaults_are_empty_and_mean():
    session = AnalysisSession()
    assert session.directory == ""
    assert session.rois == []
    assert session.stats == {}
    assert session.plot_stat == "mean"
    assert session.figure.x_auto and session.figure.y_auto
    assert session.figure.export_dpi == 300
    assert session.figure.export_format == "png"
    assert "bg_corrected" in PLOT_STATS


def test_roi_default_style_and_session_name_sequence():
    session = AnalysisSession()
    roi = Roi(name=session.next_roi_name(), kind="circle",
              geometry=[10.0, 10.0, 5.0])
    assert roi.style.line_style == "solid"
    assert roi.style.marker == "none"
    session.rois.append(roi)
    assert session.next_roi_name() == "ROI 2"
    assert session.roi_by_id(roi.roi_id) is roi
    assert session.roi_by_id("nope") is None


def test_session_cache_key_uses_effective_geometry(tmp_path):
    image = tmp_path / "a_2026_07_20-10_00_00_raw.png"
    image.write_bytes(b"")
    roi = Roi(name="ROI 1", kind="circle", geometry=[5.0, 5.0, 2.0])
    session = AnalysisSession(rois=[roi])
    key = session.cache_key(str(image), roi)
    assert key[2] == roi.roi_id and key[3] == "circle"
    assert key[4] == (5.0, 5.0, 2.0)


def test_model_gains_session_and_mirrors():
    model = RoiAnalysisModel()
    assert isinstance(model.session, AnalysisSession)
    assert model.filtered_paths == []
    assert model.current_image_path == ""
