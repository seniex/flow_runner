import pytest
from PySide6.QtCore import QSettings

import flow_runner.ui.window_preferences as window_preferences_module


@pytest.fixture(autouse=True)
def isolate_default_window_preferences(monkeypatch, tmp_path):
    settings_path = tmp_path / "default-window-preferences.ini"

    def isolated_settings():
        return QSettings(str(settings_path), QSettings.Format.IniFormat)

    monkeypatch.setattr(window_preferences_module, "QSettings", isolated_settings)
