from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flow_runner.domain.project import Project
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.theme_manager import ThemeManager


@dataclass(frozen=True, slots=True)
class ApplicationComposition:
    app: QApplication
    window: MainWindow
    store: ProjectStore


def create_application(
    argv: Sequence[str] | None = None,
    *,
    project_path: Path | None = None,
) -> ApplicationComposition:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(list(argv or []))
    path = project_path or Path.cwd() / "project.json"
    store = ProjectStore(path)
    project = store.load() if path.exists() else Project(name="新项目")
    window = MainWindow(project)
    qss_path = Path(__file__).parent / "resources" / "styles" / "base.qss"
    ThemeManager().apply(app, qss_path)
    return ApplicationComposition(app=app, window=window, store=store)


def main() -> int:
    composition = create_application(sys.argv)
    composition.window.show()
    return composition.app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
