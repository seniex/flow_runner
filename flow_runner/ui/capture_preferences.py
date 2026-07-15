from PySide6.QtCore import QSettings

_HIDE_APPLICATION_KEY = "capture/hide_application"


class CapturePreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    @property
    def hide_application(self) -> bool:
        value = self._settings.value(_HIDE_APPLICATION_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).casefold() in {"1", "true", "yes", "on"}

    @hide_application.setter
    def hide_application(self, hidden: bool) -> None:
        self._settings.setValue(_HIDE_APPLICATION_KEY, bool(hidden))
