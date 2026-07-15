from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtWidgets import QApplication, QWidget


@contextmanager
def temporarily_hidden_application(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        yield
        return
    visible: list[QWidget] = [
        widget for widget in app.topLevelWidgets() if widget.isVisible()
    ]
    active = app.activeWindow()
    for widget in visible:
        widget.hide()
    app.processEvents()
    try:
        yield
    finally:
        for widget in visible:
            widget.show()
        if active in visible:
            active.raise_()
            active.activateWindow()
        app.processEvents()
