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
from flow_runner.domain.capture_targets import WindowCaptureMode
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import Project
from flow_runner.engine.context import StepContext
from flow_runner.engine.perception import OcrProvider, PerceptionService
from flow_runner.engine.resources import ResourceCoordinator
from flow_runner.engine.runner import Runner
from flow_runner.engine.step_executor import StepExecutor, StepRuntime
from flow_runner.infrastructure.capture.desktop import DesktopCapture
from flow_runner.infrastructure.capture.targets import (
    TargetCapture,
    WindowCapture,
)
from flow_runner.infrastructure.capture.windows_graphics import WindowsGraphicsCapture
from flow_runner.infrastructure.input.keyboard import KeyboardDevice, PyAutoGuiKeyboardDevice
from flow_runner.infrastructure.input.mouse import MouseDevice, PyAutoGuiMouseDevice
from flow_runner.infrastructure.input.recording import (
    RecordingListenerFactory,
    RecordingPlayer,
    RecordingRecorder,
)
from flow_runner.infrastructure.logging.sinks import JsonLinesEventSink
from flow_runner.infrastructure.ocr.paddle_json import PaddleJsonOcr, PaddleJsonProcessClient
from flow_runner.infrastructure.ocr.tesseract import TesseractOcr
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.infrastructure.processes.launch import WindowsProcessLauncher
from flow_runner.infrastructure.processes.query import WindowsProcessQuery
from flow_runner.infrastructure.windowing.dpi import enable_per_monitor_dpi_awareness
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
    resource_coordinator: ResourceCoordinator
    ocr_client: PaddleJsonProcessClient | None
    mouse_device: MouseDevice
    keyboard_device: KeyboardDevice

    def start_services(self) -> None:
        self.hotkey_service.start()

    def shutdown(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop(self.recording_path)
            self.window.set_recording_state(False)
        self.hotkey_service.stop()
        self.runner_bridge.shutdown()
        self.release_inputs()
        if self.ocr_client is not None:
            self.ocr_client.stop()

    def release_inputs(self) -> None:
        self.mouse_device.release_all()
        self.keyboard_device.release_all()

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
    mouse_device: MouseDevice | None = None,
    keyboard_device: KeyboardDevice | None = None,
) -> ApplicationComposition:
    enable_per_monitor_dpi_awareness()
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(list(argv or []))
    path = project_path or Path.cwd() / "project.json"
    store = ProjectStore(path)
    project = store.load() if path.exists() else Project(name="新项目")
    perception = PerceptionService(_build_capture(project))
    resource_coordinator = ResourceCoordinator(perception)
    ocr_provider, ocr_client = _build_ocr_provider(project, path.parent)
    mouse = mouse_device or PyAutoGuiMouseDevice()
    keyboard = keyboard_device or PyAutoGuiKeyboardDevice()
    registry = _build_registry(perception, asyncio.sleep, ocr_provider, mouse, keyboard)
    registry.validate_project_or_raise(project)

    def save_project(candidate: Project) -> None:
        registry.validate_project_or_raise(candidate)
        store.save(candidate)

    def step_executor_factory(token: object) -> StepExecutor:
        from flow_runner.engine.cancellation import CancellationToken

        if not isinstance(token, CancellationToken):
            raise TypeError("runner supplied an invalid cancellation token")
        execution_registry = _build_registry(
            perception,
            token.sleep,
            ocr_provider,
            mouse,
            keyboard,
        )
        return StepExecutor(
            StepRuntime(
                registry=execution_registry,
                context=StepContext(),
                cancellation=token,
                resources=resource_coordinator,
            )
        )

    runner = Runner(step_executor_factory=step_executor_factory)
    resource_coordinator.event_sink = runner.report_resource_event
    runner_bridge = RunnerBridge(
        runner,
        persistent_event_sink=JsonLinesEventSink(path.parent / "logs" / "runtime.jsonl"),
    )
    window = MainWindow(
        project,
        runner_bridge=runner_bridge,
        save_project=save_project,
        project_path=path,
        registry=registry,
    )
    recorder = RecordingRecorder(listener_factory=recording_listener_factory)
    configured_hotkeys = hotkey_config or HotkeyConfig.model_validate(
        project.settings.get("hotkeys", {})
    )
    hotkey_service = HotkeyService(
        configured_hotkeys,
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
        resource_coordinator=resource_coordinator,
        ocr_client=ocr_client,
        mouse_device=mouse,
        keyboard_device=keyboard,
    )
    window.recordRequested.connect(lambda: composition.toggle_recording())
    runner_bridge.terminated.connect(lambda: composition.release_inputs())
    app.aboutToQuit.connect(lambda: composition.shutdown())
    return composition


def _build_registry(
    perception: PerceptionService,
    sleep: Callable[[float], Awaitable[None]],
    ocr_provider: OcrProvider,
    mouse_device: MouseDevice,
    keyboard_device: KeyboardDevice,
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for condition in (
        OcrCondition(perception, ocr_provider),
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
    registry.register_action(MouseAction(mouse_device))
    registry.register_action(KeyboardAction(keyboard_device))
    registry.register_action(WaitAction(sleep))
    registry.register_action(SetVariableAction())
    registry.register_action(LaunchProcessAction(WindowsProcessLauncher()))
    registry.register_action(PlaybackScriptAction(RecordingPlayer(sleep=sleep)))
    registry.register_action(WindowAction(Win32WindowController()))
    return registry


def _build_capture(project: Project) -> TargetCapture:
    try:
        mode = WindowCaptureMode(
            str(project.settings.get("window_capture_mode", "foreground")).casefold()
        )
        timeout_value = project.settings.get("window_capture_timeout_seconds", 3.0)
        if isinstance(timeout_value, bool):
            raise ValueError("window capture timeout must be numeric")
        timeout_seconds = float(timeout_value)
        if timeout_seconds <= 0:
            raise ValueError("window capture timeout must be positive")
        fallback = project.settings.get("window_capture_fallback", True)
        if not isinstance(fallback, bool):
            raise ValueError("window capture fallback must be boolean")
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"invalid window capture settings: {error}") from error
    return TargetCapture(
        DesktopCapture(),
        WindowCapture(),
        background_window=WindowsGraphicsCapture(timeout_seconds=timeout_seconds),
        default_window_mode=mode,
        fallback_to_foreground=fallback,
    )


def _build_ocr_provider(
    project: Project,
    project_directory: Path,
) -> tuple[OcrProvider, PaddleJsonProcessClient | None]:
    engine = str(project.settings.get("ocr_engine", "tesseract")).strip().casefold()
    if engine == "tesseract":
        return TesseractOcr(), None
    if engine != "paddle":
        raise ConfigurationError(f"unsupported OCR engine: {engine}")
    configured_path = str(project.settings.get("paddle_exe_path", "")).strip()
    if not configured_path:
        raise ConfigurationError("paddle_exe_path is required when ocr_engine is paddle")
    executable = Path(configured_path)
    if not executable.is_absolute():
        executable = project_directory / executable
    client = PaddleJsonProcessClient(executable)
    return PaddleJsonOcr(client), client


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
