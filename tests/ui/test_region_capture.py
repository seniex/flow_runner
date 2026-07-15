import importlib
from datetime import datetime

from PIL import Image

from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.editors.model_form import ModelForm, PathFieldEditor, TupleFieldEditor


def test_display_selection_maps_through_letterboxing_to_image_coordinates():
    capture = importlib.import_module("flow_runner.ui.region_capture")

    region = capture.map_selection_to_image(
        (50, 150, 450, 350),
        viewport_size=(500, 500),
        image_size=(1000, 500),
    )

    assert region == (100, 50, 900, 450)


def test_region_capture_service_saves_selected_template_crop(tmp_path):
    capture = importlib.import_module("flow_runner.ui.region_capture")
    image = Image.new("RGB", (100, 80), "black")
    for x in range(20, 60):
        for y in range(10, 50):
            image.putpixel((x, y), (20, 220, 60))
    targets = []

    def frame_provider(target):
        targets.append(target)
        return CapturedFrame(image=image, origin=(-100, 25))

    service = capture.RegionCaptureService(
        frame_provider,
        selector=lambda frame, parent: (20, 10, 60, 50),
        template_directory=tmp_path / "data" / "templates",
        now=lambda: datetime(2026, 7, 15, 1, 2, 3, 456000),
    )

    selected = service.capture_template("window:Game")

    assert selected.region == (20, 10, 60, 50)
    assert selected.path == (tmp_path / "data" / "templates" / "template_20260715_010203_456.png")
    assert Image.open(selected.path).size == (40, 40)
    assert Image.open(selected.path).getpixel((0, 0)) == (20, 220, 60)
    assert targets == ["window:Game"]


def test_region_capture_service_cancel_does_not_create_template(tmp_path):
    capture = importlib.import_module("flow_runner.ui.region_capture")
    service = capture.RegionCaptureService(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        selector=lambda frame, parent: None,
        template_directory=tmp_path / "data" / "templates",
    )

    assert service.pick_region("desktop") is None
    assert service.capture_template("desktop") is None
    assert not (tmp_path / "data" / "templates").exists()


def test_model_form_region_and_template_capture_buttons_update_values(qtbot, tmp_path):
    capture = importlib.import_module("flow_runner.ui.region_capture")
    picked_regions = []
    captured_targets = []

    def pick_region(target):
        picked_regions.append(target)
        return (1, 2, 31, 42)

    def capture_template(target):
        captured_targets.append(target)
        return capture.TemplateCapture(
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
