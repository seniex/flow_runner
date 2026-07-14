from PySide6.QtCore import QSettings

_SHOW_ADVANCED_KEY = "editor/show_advanced"


class EditorPreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    @property
    def show_advanced(self) -> bool:
        value = self._settings.value(_SHOW_ADVANCED_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).casefold() in {"1", "true", "yes", "on"}

    @show_advanced.setter
    def show_advanced(self, visible: bool) -> None:
        self._settings.setValue(_SHOW_ADVANCED_KEY, visible)
