import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from flow_runner.ui.application_visibility import temporarily_hidden_application
from flow_runner.ui.capture_preferences import CapturePreferences


def test_capture_preferences_round_trip_hide_application(tmp_path):
    path = tmp_path / "capture.ini"
    preferences = CapturePreferences(QSettings(str(path), QSettings.Format.IniFormat))
    assert not preferences.hide_application

    preferences.hide_application = True

    reopened = CapturePreferences(QSettings(str(path), QSettings.Format.IniFormat))
    assert reopened.hide_application


@pytest.mark.parametrize("stored", [True, "true", "1", "yes", "on"])
def test_capture_preferences_accept_qsettings_boolean_forms(tmp_path, stored):
    settings = QSettings(str(tmp_path / "capture.ini"), QSettings.Format.IniFormat)
    settings.setValue("capture/hide_application", stored)
    assert CapturePreferences(settings).hide_application


def test_visibility_guard_restores_only_previously_visible_windows(qtbot):
    visible = QWidget()
    hidden = QWidget()
    qtbot.addWidget(visible)
    qtbot.addWidget(hidden)
    visible.show()
    hidden.hide()

    with temporarily_hidden_application(True):
        assert not visible.isVisible()
        assert not hidden.isVisible()

    assert visible.isVisible()
    assert not hidden.isVisible()


def test_visibility_guard_restores_after_exception(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.show()

    with pytest.raises(RuntimeError, match="capture failed"):
        with temporarily_hidden_application(True):
            raise RuntimeError("capture failed")

    assert window.isVisible()
