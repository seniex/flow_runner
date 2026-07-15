import pytest
from PySide6.QtCore import QSettings, QSize

from flow_runner.ui.window_preferences import WindowPreferences


def test_window_preferences_round_trip_size(tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    preferences = WindowPreferences(settings)
    assert preferences.size is None

    preferences.size = QSize(1180, 760)
    settings.sync()

    reopened = WindowPreferences(
        QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    )
    assert reopened.size == QSize(1180, 760)


@pytest.mark.parametrize(
    ("width", "height"),
    [("bad", 700), (-1, 700), (900, 0), (True, 700)],
)
def test_window_preferences_reject_invalid_sizes(tmp_path, width, height):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    settings.setValue("window/width", width)
    settings.setValue("window/height", height)
    assert WindowPreferences(settings).size is None
