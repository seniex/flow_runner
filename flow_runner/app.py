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
from flow_runner.capabilities.conditions.process import ProcessCondition
from flow_runner.capabilities.conditions.region_change import RegionChangeCondition
from flow_runner.capabilities.conditions.time import TimeCondition
from flow_runner.capabilities.conditions.variables import VariableCondition
from flow_runner.capabilities.conditions.window import WindowCondition
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.project import Project
from flow_runner.engine.context import StepContext
from flow_runner.engine.perception import PerceptionService
from flow_runner.engine.runner import Runner
from flow_runner.engine.step_executor import StepExecutor, StepRuntime
from flow_runner.infrastructure.capture.desktop import DesktopCapture
from flow_runner.infrastructure.input.keyboard import PyAutoGuiKeyboardDevice
from flow_runner.infrastructure.input.mouse import PyAutoGuiMouseDevice
from flow_runner.infrastructure.input.recording import (
    RecordingListenerFactory,
    RecordingPlayer,
    RecordingRecorder,
)
from flow_runner.infrastructure.ocr.tesseract import TesseractOcr
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.infrastructure.processes.launch import WindowsProcessLauncher
from flow_runner.infrastructure.processes.query import WindowsProcessQuery
from flow_runner.infrastructure.windowing.win32 import Win32WindowController, Win32WindowQuery
from flow_runner.ui.hotkeys import HotkeyConfig, HotkeyService, ListenerFactory
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
    hotkey_service: HotkeyService
    recorder: RecordingRecorder
    recording_path: Path

    def start_services(self) -> None:
        self.hotkey_service.start()

    def shutdown(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop(self.recording_path)
            self.window.set_recording_state(False)
        self.hotkey_service.stop()
        self.runner_bridge.shutdown()

    def toggle_recording(self) -> None:
        if self.recorder.is_recording:
            events = self.recorder.stop(self.recording_path)
            self.window.set_recording_state(False)
            self.window.statusBar().showMessage(f"录制已保存：{len(events)} 个事件")
        else:
            self.recorder.start()
            self.window.set_recording_state(True)
            self.window.statusBar().showMessage("正在录制输入")


def create_application(
    argv: Sequence[str] | None = None,
    *,
    project_path: Path | None = None,
    hotkey_config: HotkeyConfig | None = None,
    hotkey_listener_factory: ListenerFactory | None = None,
    recording_listener_factory: RecordingListenerFactory | None = None,
    recording_path: Path | None = None,
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
    recorder = RecordingRecorder(listener_factory=recording_listener_factory)
    hotkey_service = HotkeyService(
        hotkey_config or HotkeyConfig(),
        actions={
            "start": window.startRequested.emit,
            "pause": window.pauseRequested.emit,
            "stop": window.stopRequested.emit,
            "record": window.recordRequested.emit,
        },
        listener_factory=hotkey_listener_factory,
    )
    qss_path = Path(__file__).parent / "resources" / "styles" / "base.qss"
    ThemeManager().apply(app, qss_path)
    composition = ApplicationComposition(
        app=app,
        window=window,
        store=store,
        registry=registry,
        runner=runner,
        runner_bridge=runner_bridge,
        hotkey_service=hotkey_service,
        recorder=recorder,
        recording_path=recording_path or path.parent / "recordings" / "latest.json",
    )
    window.recordRequested.connect(lambda: composition.toggle_recording())
    app.aboutToQuit.connect(lambda: composition.shutdown())
    return composition


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
        WindowCondition(Win32WindowQuery()),
        ProcessCondition(WindowsProcessQuery()),
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
    composition.start_services()
    try:
        return composition.app.exec()
    finally:
        composition.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
