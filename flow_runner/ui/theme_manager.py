from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget


class ThemeManager:
    def apply(self, app: QApplication, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        app.setStyleSheet(path.read_text(encoding="utf-8"))

    @staticmethod
    def refresh_widget(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
