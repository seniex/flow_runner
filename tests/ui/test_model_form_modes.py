import importlib

import pytest
from PySide6.QtCore import QSettings

from flow_runner.capabilities.actions.keyboard import KeyboardActionConfig
from flow_runner.capabilities.actions.mouse import MouseActionConfig
from flow_runner.capabilities.actions.process import LaunchProcessConfig
from flow_runner.capabilities.actions.wait import WaitActionConfig
from flow_runner.capabilities.actions.window import WindowActionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.ui.editors.model_form import ModelForm


def test_common_field_metadata_covers_initial_capabilities():
    metadata = importlib.import_module("flow_runner.ui.editor_metadata")

    assert metadata.COMMON_FIELDS == {
        "vision.ocr": frozenset({"target", "region", "keywords"}),
        "input.mouse": frozenset({"operation", "position", "button", "clicks"}),
        "input.keyboard": frozenset({"operation", "key", "keys", "text", "count"}),
        "system.wait": frozenset({"seconds"}),
        "system.launch": frozenset({"path", "arguments", "run_as_admin"}),
        "system.window_action": frozenset({"operation", "title", "geometry"}),
    }
    assert metadata.common_fields_for("unknown.capability") is None


def test_editor_preferences_persist_only_advanced_visibility(tmp_path):
    preferences_module = importlib.import_module("flow_runner.ui.editor_preferences")
    settings_path = tmp_path / "editor.ini"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    preferences = preferences_module.EditorPreferences(settings)

    assert not preferences.show_advanced

    preferences.show_advanced = True
    settings.sync()
    reopened_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    reopened = preferences_module.EditorPreferences(reopened_settings)

    assert reopened.show_advanced
    assert reopened_settings.allKeys() == ["editor/show_advanced"]


@pytest.mark.parametrize(
    ("model_type", "common_fields", "common_field", "advanced_field"),
    [
        (OcrConditionConfig, frozenset({"target", "region", "keywords"}), "keywords", "language"),
        (
            MouseActionConfig,
            frozenset({"operation", "position", "button", "clicks"}),
            "position",
            "settle_delay",
        ),
        (
            KeyboardActionConfig,
            frozenset({"operation", "key", "keys", "text", "count"}),
            "key",
            "interval",
        ),
        (
            LaunchProcessConfig,
            frozenset({"path", "arguments", "run_as_admin"}),
            "path",
            "hide_window",
        ),
        (WaitActionConfig, frozenset({"seconds"}), "seconds", None),
        (
            WindowActionConfig,
            frozenset({"operation", "title", "geometry"}),
            "title",
            None,
        ),
    ],
)
def test_model_form_separates_common_and_advanced_fields(
    qtbot,
    model_type,
    common_fields,
    common_field,
    advanced_field,
):
    form = ModelForm(model_type, common_fields=common_fields)
    qtbot.addWidget(form)

    assert not form.editor(common_field).isHidden()
    if advanced_field is None:
        assert all(not editor.isHidden() for editor in form.editors.values())
        return

    assert form.editor(advanced_field).isHidden()

    form.set_advanced_visible(True)

    assert not form.editor(advanced_field).isHidden()


def test_hidden_advanced_values_are_preserved_and_counted(qtbot):
    form = ModelForm(
        OcrConditionConfig,
        common_fields=frozenset({"target", "region", "keywords"}),
    )
    qtbot.addWidget(form)
    form.set_values(
        {
            "keywords": "开始",
            "language": "eng",
            "preprocessing": "threshold",
            "scale": 2.0,
        }
    )

    assert form.editor("language").isHidden()
    assert form.values()["language"] == "eng"
    assert form.values()["preprocessing"] == "threshold"
    assert form.values()["scale"] == 2.0
    assert form.advanced_non_default_count() == 3


def test_model_form_without_field_metadata_keeps_existing_all_fields_behavior(qtbot):
    form = ModelForm(OcrConditionConfig)
    qtbot.addWidget(form)

    assert all(not editor.isHidden() for editor in form.editors.values())
    assert form.advanced_non_default_count() == 0
