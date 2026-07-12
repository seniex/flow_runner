from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication

from flow_runner.capabilities.actions.keyboard import KeyboardAction
from flow_runner.capabilities.actions.mouse import MouseAction
from flow_runner.capabilities.actions.process import LaunchProcessAction
from flow_runner.capabilities.actions.script import PlaybackScriptAction
from flow_runner.capabilities.actions.variables import SetVariableAction
from flow_runner.capabilities.actions.wait import WaitAction
from flow_runner.capabilities.actions.window import WindowAction
from flow_runner.capabilities.conditions.count import CountCondition
from flow_runner.capabilities.conditions.image import ImageCondition
from flow_runner.capabilities.conditions.ocr import OcrCondition
from flow_runner.capabilities.conditions.pixel import PixelCondition
from flow_runner.capabilities.conditions.region_change import RegionChangeCondition
from flow_runner.capabilities.conditions.time import TimeCondition
from flow_runner.capabilities.conditions.variables import VariableCondition
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.project import Project
from flow_runner.engine.context import StepContext
from flow_runner.engine.perception import PerceptionService
from flow_runner.engine.runner import Runner
from flow_runner.engine.step_executor import StepExecutor, StepRuntime
from flow_runner.infrastructure.capture.desktop import DesktopCapture
from flow_runner.infrastructure.input.keyboard import PyAutoGuiKeyboardDevice
from flow_runner.infrastructure.input.mouse import PyAutoGuiMouseDevice
from flow_runner.infrastructure.input.recording import RecordingPlayer
from flow_runner.infrastructure.ocr.tesseract import TesseractOcr
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.infrastructure.processes.launch import WindowsProcessLauncher
from flow_runner.infrastructure.windowing.win32 import Win32WindowController
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.theme_manager import ThemeManager


@dataclass(frozen=True, slots=True)
class ApplicationComposition:
    app: QApplication
    window: MainWindow
    store: ProjectStore
    registry: CapabilityRegistry
    runner: Runner
    runner_bridge: RunnerBridge


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
    perception = PerceptionService(DesktopCapture())
    registry = _build_registry(perception, asyncio.sleep)

    def step_executor_factory(token: object) -> StepExecutor:
        from flow_runner.engine.cancellation import CancellationToken

        if not isinstance(token, CancellationToken):
            raise TypeError("runner supplied an invalid cancellation token")
        execution_registry = _build_registry(perception, token.sleep)
        return StepExecutor(
            StepRuntime(
                registry=execution_registry,
                context=StepContext(),
                cancellation=token,
            )
        )

    runner = Runner(step_executor_factory=step_executor_factory)
    runner_bridge = RunnerBridge(runner)
    window = MainWindow(project, runner_bridge=runner_bridge)
    qss_path = Path(__file__).parent / "resources" / "styles" / "base.qss"
    ThemeManager().apply(app, qss_path)
    return ApplicationComposition(
        app=app,
        window=window,
        store=store,
        registry=registry,
        runner=runner,
        runner_bridge=runner_bridge,
    )


def _build_registry(
    perception: PerceptionService,
    sleep: Callable[[float], Awaitable[None]],
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for condition in (
        OcrCondition(perception, TesseractOcr()),
        ImageCondition(perception),
        PixelCondition(perception),
        RegionChangeCondition(perception),
        TimeCondition(),
        CountCondition(),
        VariableCondition(),
    ):
        registry.register_condition(condition)
    registry.register_action(MouseAction(PyAutoGuiMouseDevice()))
    registry.register_action(KeyboardAction(PyAutoGuiKeyboardDevice()))
    registry.register_action(WaitAction(sleep))
    registry.register_action(SetVariableAction())
    registry.register_action(LaunchProcessAction(WindowsProcessLauncher()))
    registry.register_action(PlaybackScriptAction(RecordingPlayer(sleep=sleep)))
    registry.register_action(WindowAction(Win32WindowController()))
    return registry


def main() -> int:
    composition = create_application(sys.argv)
    composition.window.show()
    return composition.app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
