from PySide6.QtCore import QSettings, QSize


class WindowPreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    @property
    def size(self) -> QSize | None:
        width = self._positive_int(self._settings.value("window/width"))
        height = self._positive_int(self._settings.value("window/height"))
        return QSize(width, height) if width is not None and height is not None else None

    @size.setter
    def size(self, value: QSize) -> None:
        self._settings.setValue("window/width", value.width())
        self._settings.setValue("window/height", value.height())

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
