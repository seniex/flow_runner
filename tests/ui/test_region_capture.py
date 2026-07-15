from datetime import datetime

from PIL import Image

from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.capture_selection import CaptureSelectionSession
from flow_runner.ui.editors.model_form import ModelForm, PathFieldEditor, TupleFieldEditor
from flow_runner.ui.native_capture_overlay import SelectionMode
from flow_runner.ui.region_capture import RegionCaptureService, TemplateCapture


class _Preferences:
    hide_application = False


def test_region_capture_service_saves_selected_template_crop(tmp_path):
    image = Image.new("RGB", (100, 80), "black")
    for x in range(20, 60):
        for y in range(10, 50):
            image.putpixel((x, y), (20, 220, 60))
    targets = []

    def frame_provider(target):
        targets.append(target)
        return CapturedFrame(image=image, origin=(-100, 25))

    modes = []

    def selector(frame, mode, parent):
        modes.append(mode)
        return (20, 10, 60, 50)

    session = CaptureSelectionSession(
        frame_provider,
        _Preferences(),
        selector=selector,
    )
    service = RegionCaptureService(
        session,
        template_directory=tmp_path / "data" / "templates",
        now=lambda: datetime(2026, 7, 15, 1, 2, 3, 456000),
    )

    selected = service.capture_template("window:Game")

    assert selected.region == (20, 10, 60, 50)
    assert selected.path == (tmp_path / "data" / "templates" / "template_20260715_010203_456.png")
    assert Image.open(selected.path).size == (40, 40)
    assert Image.open(selected.path).getpixel((0, 0)) == (20, 220, 60)
    assert targets == ["window:Game"]
    assert modes == [SelectionMode.REGION]


def test_region_capture_service_cancel_does_not_create_template(tmp_path):
    session = CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        _Preferences(),
        selector=lambda frame, mode, parent: None,
    )
    service = RegionCaptureService(
        session,
        template_directory=tmp_path / "data" / "templates",
    )

    assert service.pick_region("desktop") is None
    assert service.capture_template("desktop") is None
    assert not (tmp_path / "data" / "templates").exists()


def test_model_form_region_and_template_capture_buttons_update_values(qtbot, tmp_path):
    picked_regions = []
    captured_targets = []

    def pick_region(target):
        picked_regions.append(target)
        return (1, 2, 31, 42)

    def capture_template(target):
        captured_targets.append(target)
        return TemplateCapture(
            region=(5, 6, 45, 56),
            path=tmp_path / "templates" / "button.png",
        )

    form = ModelForm(
        ImageConditionConfig,
        pick_region=pick_region,
        capture_template=capture_template,
    )
    qtbot.addWidget(form)
    region = form.editor("region")
    template_path = form.editor("template_path")

    assert isinstance(region, TupleFieldEditor)
    assert isinstance(template_path, PathFieldEditor)
    region.pick_button.click()
    assert form.values()["region"] == (1, 2, 31, 42)
    template_path.capture_button.click()

    assert form.values()["region"] == (5, 6, 45, 56)
    assert form.values()["template_path"] == str(tmp_path / "templates" / "button.png")
    assert picked_regions == ["desktop"]
    assert captured_targets == ["desktop"]
