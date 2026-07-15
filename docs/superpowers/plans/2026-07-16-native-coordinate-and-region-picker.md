# Native Coordinate and Region Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scaled confirmation dialog with native-resolution desktop/window overlays, add one-click mouse coordinate capture, and execute fixed window coordinates relative to the window's current origin without breaking existing absolute or result-bound coordinates.

**Architecture:** Keep capture pixels and coordinate conversion in small testable services. A shared selection session owns temporary application hiding and frozen-frame capture; display mappings and overlay panes translate Qt logical coordinates to captured physical pixels. Mouse actions gain an independent target plus an explicit coordinate-space marker, while existing configs default to absolute screen coordinates.

**Tech Stack:** Python 3.12, PySide6, Pillow, Pydantic v2, Win32/pywin32, pytest/pytest-qt, Ruff, mypy

---

## Scope and Safety Rules

- Work in an isolated worktree created with `superpowers:using-git-worktrees`.
- Use the global `python` executable for every command.
- Follow strict red-green-refactor TDD; every behavior change starts with a failing test.
- Never stage or modify `data/project.json`; its existing column-width change belongs to the user.
- Preserve `$result...` binding syntax and absolute result positions.
- Do not update README until automated verification and real Windows handoff are complete.

### Task 1: Persist the Hide-Application Capture Preference and Restore Visibility Safely

**Files:**
- Create: `flow_runner/ui/capture_preferences.py`
- Create: `flow_runner/ui/application_visibility.py`
- Create: `tests/ui/test_capture_preferences.py`

- [ ] **Step 1: Write failing QSettings and visibility restoration tests**

Create `tests/ui/test_capture_preferences.py`:

```python
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from flow_runner.ui.application_visibility import temporarily_hidden_application
from flow_runner.ui.capture_preferences import CapturePreferences


def test_capture_preferences_round_trip_hide_application(tmp_path):
    path = tmp_path / "capture.ini"
    preferences = CapturePreferences(
        QSettings(str(path), QSettings.Format.IniFormat)
    )
    assert not preferences.hide_application

    preferences.hide_application = True

    reopened = CapturePreferences(
        QSettings(str(path), QSettings.Format.IniFormat)
    )
    assert reopened.hide_application


@pytest.mark.parametrize("stored", [True, "true", "1", "yes", "on"])
def test_capture_preferences_accept_qsettings_boolean_forms(tmp_path, stored):
    settings = QSettings(str(tmp_path / "capture.ini"), QSettings.Format.IniFormat)
    settings.setValue("capture/hide_application", stored)
    assert CapturePreferences(settings).hide_application


def test_visibility_guard_restores_only_previously_visible_windows(qtbot):
    visible = QWidget()
    hidden = QWidget()
    qtbot.addWidget(visible)
    qtbot.addWidget(hidden)
    visible.show()
    hidden.hide()

    with temporarily_hidden_application(True):
        assert not visible.isVisible()
        assert not hidden.isVisible()

    assert visible.isVisible()
    assert not hidden.isVisible()


def test_visibility_guard_restores_after_exception(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.show()

    with pytest.raises(RuntimeError, match="capture failed"):
        with temporarily_hidden_application(True):
            raise RuntimeError("capture failed")

    assert window.isVisible()
```

- [ ] **Step 2: Run the tests and verify the modules are absent**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_capture_preferences.py -q
```

Expected: collection fails because `capture_preferences` and `application_visibility` do not exist.

- [ ] **Step 3: Implement validated local capture preferences**

Create `flow_runner/ui/capture_preferences.py`:

```python
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
```

- [ ] **Step 4: Implement exception-safe application visibility restoration**

Create `flow_runner/ui/application_visibility.py`:

```python
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
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_capture_preferences.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the local preference and visibility guard**

```powershell
git add flow_runner/ui/capture_preferences.py flow_runner/ui/application_visibility.py tests/ui/test_capture_preferences.py
git commit -m "feat: add capture visibility preferences"
```

### Task 2: Map Logical Displays to Native Captured Pixels

**Files:**
- Create: `flow_runner/infrastructure/windowing/displays.py`
- Create: `flow_runner/ui/display_mapping.py`
- Create: `tests/ui/test_display_mapping.py`
- Create: `tests/unit/infrastructure/test_displays.py`

- [ ] **Step 1: Write failing pure mapping tests for DPI and negative origins**

Create `tests/ui/test_display_mapping.py`:

```python
from flow_runner.ui.display_mapping import (
    DisplayGeometry,
    build_display_mappings,
)


def test_display_mapping_converts_150_percent_logical_points_to_frame_pixels():
    display = DisplayGeometry(
        name="DISPLAY1",
        logical=(0, 0, 1707, 960),
        physical=(0, 0, 2560, 1440),
    )
    mapping = build_display_mappings(
        frame_origin=(0, 0),
        frame_size=(2560, 1440),
        displays=(display,),
    )[0]

    assert mapping.logical_to_frame((853, 480)) == (1279, 720)
    assert mapping.frame_to_logical((1279, 720)) == (853, 480)


def test_display_mapping_handles_negative_secondary_monitor_origin():
    displays = (
        DisplayGeometry(
            name="LEFT",
            logical=(-1536, 0, 0, 864),
            physical=(-1920, 0, 0, 1080),
        ),
        DisplayGeometry(
            name="PRIMARY",
            logical=(0, 0, 2560, 1440),
            physical=(0, 0, 2560, 1440),
        ),
    )
    mappings = build_display_mappings(
        frame_origin=(-1920, 0),
        frame_size=(4480, 1440),
        displays=displays,
    )

    assert mappings[0].logical_to_frame((-768, 432)) == (960, 540)
    assert mappings[1].logical_to_frame((1280, 720)) == (3200, 720)


def test_display_mapping_crops_window_capture_to_display_intersections():
    displays = (
        DisplayGeometry("LEFT", (-1000, 0, 0, 800), (-1000, 0, 0, 800)),
        DisplayGeometry("RIGHT", (0, 0, 1000, 800), (0, 0, 1000, 800)),
    )
    mappings = build_display_mappings(
        frame_origin=(-200, 100),
        frame_size=(600, 400),
        displays=displays,
    )

    assert [mapping.frame_region for mapping in mappings] == [
        (0, 0, 200, 400),
        (200, 0, 600, 400),
    ]
```

- [ ] **Step 2: Write failing native display-provider matching tests**

Create `tests/unit/infrastructure/test_displays.py`:

```python
from flow_runner.infrastructure.windowing.displays import PhysicalDisplay


def test_physical_display_exposes_device_name_and_pixel_rect():
    display = PhysicalDisplay("DISPLAY1", (-1920, 0, 0, 1080))
    assert display.name == "DISPLAY1"
    assert display.rect == (-1920, 0, 0, 1080)
```

- [ ] **Step 3: Run tests and verify the mapping types are missing**

Run:

```powershell
python -m pytest tests/ui/test_display_mapping.py tests/unit/infrastructure/test_displays.py -q
```

Expected: collection fails because both modules are absent.

- [ ] **Step 4: Implement physical display enumeration**

Create `flow_runner/infrastructure/windowing/displays.py` with the public immutable value and a Windows provider:

```python
from dataclasses import dataclass
from typing import Protocol

Rect = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PhysicalDisplay:
    name: str
    rect: Rect


class PhysicalDisplayProvider(Protocol):
    def displays(self) -> tuple[PhysicalDisplay, ...]: ...


class WindowsPhysicalDisplayProvider:
    def displays(self) -> tuple[PhysicalDisplay, ...]:
        return _enumerate_windows_displays()
```

Use this implementation below the public types:

```python
import ctypes
from ctypes import wintypes


class _MonitorInfoExW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _enumerate_windows_displays() -> tuple[PhysicalDisplay, ...]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    result: list[PhysicalDisplay] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    @callback_type
    def visit(monitor, device_context, rect, data):
        del device_context, rect, data
        info = _MonitorInfoExW()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        bounds = info.rcMonitor
        result.append(
            PhysicalDisplay(
                str(info.szDevice),
                (bounds.left, bounds.top, bounds.right, bounds.bottom),
            )
        )
        return True

    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(_MonitorInfoExW),
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        callback_type,
        wintypes.LPARAM,
    ]
    if not user32.EnumDisplayMonitors(None, None, visit, 0):
        raise OSError(ctypes.get_last_error(), "无法枚举显示器")
    if not result:
        raise OSError("未找到可用显示器")
    return tuple(result)
```

- [ ] **Step 5: Implement pure display/frame intersections and transforms**

Create `flow_runner/ui/display_mapping.py`:

```python
from dataclasses import dataclass

Point = tuple[int, int]
Rect = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class DisplayGeometry:
    name: str
    logical: Rect
    physical: Rect


@dataclass(frozen=True, slots=True)
class DisplayMapping:
    display: DisplayGeometry
    logical_region: Rect
    physical_region: Rect
    frame_region: Rect

    def logical_to_frame(self, point: Point) -> Point:
        physical = _scale_point(point, self.display.logical, self.display.physical)
        return (
            physical[0] - self.physical_region[0] + self.frame_region[0],
            physical[1] - self.physical_region[1] + self.frame_region[1],
        )

    def frame_to_logical(self, point: Point) -> Point:
        physical = (
            point[0] - self.frame_region[0] + self.physical_region[0],
            point[1] - self.frame_region[1] + self.physical_region[1],
        )
        return _scale_point(physical, self.display.physical, self.display.logical)


def build_display_mappings(
    *,
    frame_origin: Point,
    frame_size: Point,
    displays: tuple[DisplayGeometry, ...],
) -> tuple[DisplayMapping, ...]:
    frame_rect = (
        frame_origin[0],
        frame_origin[1],
        frame_origin[0] + frame_size[0],
        frame_origin[1] + frame_size[1],
    )
    mappings = []
    for display in displays:
        physical = intersect_rects(frame_rect, display.physical)
        if physical is None:
            continue
        logical = _map_rect(physical, display.physical, display.logical)
        mappings.append(
            DisplayMapping(
                display=display,
                logical_region=logical,
                physical_region=physical,
                frame_region=(
                    physical[0] - frame_origin[0],
                    physical[1] - frame_origin[1],
                    physical[2] - frame_origin[0],
                    physical[3] - frame_origin[1],
                ),
            )
        )
    if not mappings:
        raise ValueError("捕获画面不与任何可用显示器相交")
    return tuple(mappings)
```

Add the complete helpers:

```python
def _scale_axis(
    value: int,
    source_start: int,
    source_end: int,
    target_start: int,
    target_end: int,
) -> int:
    if source_end <= source_start or target_end <= target_start:
        raise ValueError("显示器矩形尺寸必须为正数")
    bounded = max(source_start, min(value, source_end))
    ratio = (bounded - source_start) / (source_end - source_start)
    return round(target_start + ratio * (target_end - target_start))


def _scale_point(point: Point, source: Rect, target: Rect) -> Point:
    return (
        _scale_axis(point[0], source[0], source[2], target[0], target[2]),
        _scale_axis(point[1], source[1], source[3], target[1], target[3]),
    )


def _map_rect(rect: Rect, source: Rect, target: Rect) -> Rect:
    left, top = _scale_point((rect[0], rect[1]), source, target)
    right, bottom = _scale_point((rect[2], rect[3]), source, target)
    return left, top, right, bottom


def intersect_rects(first: Rect, second: Rect) -> Rect | None:
    result = (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )
    return result if result[2] > result[0] and result[3] > result[1] else None


def contains(rect: Rect, point: Point) -> bool:
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]
```

Add the Qt/native adapter:

```python
def display_mappings_for_frame(
    frame: CapturedFrame,
    *,
    screens: tuple[QScreen, ...] | None = None,
    physical_provider: PhysicalDisplayProvider | None = None,
) -> tuple[DisplayMapping, ...]:
    qt_screens = screens or tuple(QGuiApplication.screens())
    provider = physical_provider or WindowsPhysicalDisplayProvider()
    physical = {
        display.name.casefold(): display for display in provider.displays()
    }
    geometries: list[DisplayGeometry] = []
    for screen in qt_screens:
        native = physical.get(screen.name().casefold())
        if native is None:
            raise ValueError(f"无法匹配显示器物理坐标：{screen.name()}")
        rect = screen.geometry()
        geometries.append(
            DisplayGeometry(
                screen.name(),
                (rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()),
                native.rect,
            )
        )
    return build_display_mappings(
        frame_origin=frame.origin,
        frame_size=frame.image.size,
        displays=tuple(geometries),
    )
```

- [ ] **Step 6: Run mapping tests**

Run:

```powershell
python -m pytest tests/ui/test_display_mapping.py tests/unit/infrastructure/test_displays.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit display geometry and mapping**

```powershell
git add flow_runner/infrastructure/windowing/displays.py flow_runner/ui/display_mapping.py tests/ui/test_display_mapping.py tests/unit/infrastructure/test_displays.py
git commit -m "feat: map capture pixels across displays"
```

### Task 3: Replace the Dialog With Immediate Native Overlay Selection

**Files:**
- Create: `flow_runner/ui/native_capture_overlay.py`
- Create: `tests/ui/test_native_capture_overlay.py`

- [ ] **Step 1: Write failing controller tests for click, drag, cross-display, and Esc**

Create `tests/ui/test_native_capture_overlay.py` using two `DisplayMapping` instances and the pure controller API:

```python
from flow_runner.ui.native_capture_overlay import SelectionController, SelectionMode


def test_point_selection_finishes_on_single_click(mapping):
    controller = SelectionController(SelectionMode.POINT, (mapping,))
    controller.finish((100, 80))
    assert controller.result == (100, 80)
    assert controller.finished


def test_region_selection_finishes_on_release_without_confirmation(mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    controller.begin((10, 20))
    controller.update((110, 120))
    controller.finish((110, 120))
    assert controller.result == (10, 20, 110, 120)
    assert controller.finished


def test_region_selection_can_cross_display_mappings(left_mapping, right_mapping):
    controller = SelectionController(
        SelectionMode.REGION,
        (left_mapping, right_mapping),
    )
    controller.begin((-100, 100))
    controller.finish((100, 300))
    assert controller.result == (900, 100, 1100, 300)


def test_escape_cancels_without_result(mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    controller.cancel()
    assert controller.finished
    assert controller.result is None
```

Add these pytest-qt cases using a `100 × 80` black `CapturedFrame` and a one-to-one mapping fixture:

```python
def test_native_pane_completes_region_on_mouse_release(qtbot, frame, mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    pane = NativeCapturePane(frame, mapping, controller)
    qtbot.addWidget(pane)
    pane.show()

    with qtbot.waitSignal(pane.completed):
        qtbot.mousePress(pane, Qt.MouseButton.LeftButton, pos=QPoint(10, 20))
        qtbot.mouseMove(pane, QPoint(60, 70))
        qtbot.mouseRelease(pane, Qt.MouseButton.LeftButton, pos=QPoint(60, 70))

    assert controller.result == (10, 20, 60, 70)


def test_native_pane_escape_cancels(qtbot, frame, mapping):
    controller = SelectionController(SelectionMode.POINT, (mapping,))
    pane = NativeCapturePane(frame, mapping, controller)
    qtbot.addWidget(pane)
    pane.show()

    with qtbot.waitSignal(pane.completed):
        qtbot.keyClick(pane, Qt.Key.Key_Escape)

    assert controller.result is None
    assert controller.finished
```

- [ ] **Step 2: Run tests and verify the overlay module is absent**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_native_capture_overlay.py -q
```

Expected: collection fails because `native_capture_overlay` does not exist.

- [ ] **Step 3: Implement the pure shared selection controller**

Create the following public API in `flow_runner/ui/native_capture_overlay.py`:

```python
from enum import StrEnum

from flow_runner.ui.display_mapping import DisplayMapping

Point = tuple[int, int]
Region = tuple[int, int, int, int]


class SelectionMode(StrEnum):
    POINT = "point"
    REGION = "region"


class SelectionController:
    def __init__(
        self,
        mode: SelectionMode,
        mappings: tuple[DisplayMapping, ...],
    ) -> None:
        self.mode = mode
        self.mappings = mappings
        self.start: Point | None = None
        self.current: Point | None = None
        self.result: Point | Region | None = None
        self.finished = False

    def begin(self, logical_global: Point) -> None:
        self.start = self._to_frame(logical_global)
        self.current = self.start

    def update(self, logical_global: Point) -> None:
        if self.start is not None:
            self.current = self._to_frame(logical_global)

    def finish(self, logical_global: Point) -> None:
        point = self._to_frame(logical_global)
        if self.mode is SelectionMode.POINT:
            self.result = point
        elif self.start is not None:
            left, right = sorted((self.start[0], point[0]))
            top, bottom = sorted((self.start[1], point[1]))
            if right > left and bottom > top:
                self.result = (left, top, right, bottom)
        self.finished = self.result is not None

    def cancel(self) -> None:
        self.result = None
        self.finished = True
```

Implement `_to_frame()` exactly as:

```python
def _to_frame(self, logical_global: Point) -> Point:
    for mapping in self.mappings:
        if contains(mapping.logical_region, logical_global):
            return mapping.logical_to_frame(logical_global)
    raise ValueError("选择位置不在捕获画面内")
```

- [ ] **Step 4: Implement per-display overlay panes and the modal event loop**

Add `NativeCapturePane(QWidget)` and `select_from_frame()`:

```python
def select_from_frame(
    frame: CapturedFrame,
    mode: SelectionMode,
    parent: QWidget | None = None,
    *,
    mappings: tuple[DisplayMapping, ...] | None = None,
) -> Point | Region | None:
    resolved = mappings or display_mappings_for_frame(frame)
    controller = SelectionController(mode, resolved)
    loop = QEventLoop()
    panes = [NativeCapturePane(frame, mapping, controller) for mapping in resolved]
    for pane in panes:
        pane.completed.connect(loop.quit)
        pane.show()
    panes[0].activateWindow()
    panes[0].grabKeyboard()
    loop.exec()
    for pane in panes:
        pane.releaseKeyboard()
        pane.close()
        pane.deleteLater()
    return controller.result
```

`NativeCapturePane` must:

- use frameless, topmost, tool-window flags;
- set its geometry to `mapping.logical_region`;
- crop `frame.image` by `mapping.frame_region` without resizing;
- paint the crop and its portion of the shared selection rectangle;
- forward global logical mouse positions to `SelectionController`;
- emit `completed` immediately on point click or region release;
- call `controller.cancel()` and emit `completed` on Esc.

Do not add `QDialogButtonBox`, hint labels, or double-click confirmation.

Use this event implementation; `_global_point()` converts `event.globalPosition()` to an integer tuple, and `_update_all()` calls `update()` on every pane assigned through `set_peers()`:

```python
class NativeCapturePane(QWidget):
    completed = Signal()

    def __init__(
        self,
        frame: CapturedFrame,
        mapping: DisplayMapping,
        controller: SelectionController,
    ) -> None:
        super().__init__(None)
        self.mapping = mapping
        self.controller = controller
        self._peers: tuple[NativeCapturePane, ...] = (self,)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        left, top, right, bottom = mapping.logical_region
        self.setGeometry(left, top, right - left, bottom - top)
        crop = frame.image.crop(mapping.frame_region)
        self._pixmap = QPixmap.fromImage(_pil_to_qimage(crop))
        physical_width = mapping.physical_region[2] - mapping.physical_region[0]
        logical_width = right - left
        self._pixmap.setDevicePixelRatio(physical_width / logical_width)

    def set_peers(self, panes: tuple["NativeCapturePane", ...]) -> None:
        self._peers = panes

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        point = _global_point(event)
        if self.controller.mode is SelectionMode.POINT:
            self.controller.finish(point)
            self.completed.emit()
        else:
            self.controller.begin(point)
            self.grabMouse()
            self._update_all()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.controller.start is not None:
            self.controller.update(_global_point(event))
            self._update_all()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        self.releaseMouse()
        self.controller.finish(_global_point(event))
        self._update_all()
        if self.controller.finished:
            self.completed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
            self.completed.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        selection = _selection_rect_for_mapping(self.controller, self.mapping)
        if selection is not None:
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawRect(selection.translated(-self.x(), -self.y()))

    def _update_all(self) -> None:
        for pane in self._peers:
            pane.update()
```

After constructing panes in `select_from_frame()`, call `pane.set_peers(tuple(panes))` for each pane. Add these helpers:

```python
def _global_point(event: QMouseEvent) -> Point:
    point = event.globalPosition()
    return round(point.x()), round(point.y())


def _selection_rect_for_mapping(
    controller: SelectionController,
    mapping: DisplayMapping,
) -> QRect | None:
    if controller.start is None or controller.current is None:
        return None
    frame_selection = (
        min(controller.start[0], controller.current[0]),
        min(controller.start[1], controller.current[1]),
        max(controller.start[0], controller.current[0]),
        max(controller.start[1], controller.current[1]),
    )
    overlap = intersect_rects(frame_selection, mapping.frame_region)
    if overlap is None:
        return None
    left, top = mapping.frame_to_logical((overlap[0], overlap[1]))
    right, bottom = mapping.frame_to_logical((overlap[2], overlap[3]))
    return QRect(left, top, right - left, bottom - top)
```

Import `intersect_rects()` from `display_mapping.py`; do not duplicate different boundary rules in the overlay.

- [ ] **Step 5: Run overlay and mapping tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_native_capture_overlay.py tests/ui/test_display_mapping.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the native overlay**

```powershell
git add flow_runner/ui/native_capture_overlay.py tests/ui/test_native_capture_overlay.py
git commit -m "feat: add native capture selection overlay"
```

### Task 4: Route Region, Template, and Point Selection Through One Safe Session

**Files:**
- Create: `flow_runner/ui/capture_selection.py`
- Modify: `flow_runner/ui/region_capture.py`
- Modify: `tests/ui/test_region_capture.py`
- Create: `tests/ui/test_point_capture.py`

- [ ] **Step 1: Write failing selection-session restoration tests**

Create tests for this public API:

```python
from dataclasses import dataclass

from PIL import Image
from PySide6.QtWidgets import QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.capture_preferences import CapturePreferences
from flow_runner.ui.capture_selection import CaptureSelectionSession
from flow_runner.ui.native_capture_overlay import SelectionMode


@dataclass
class FakePreferences:
    hide_application: bool


def test_selection_session_hides_before_capture_and_restores_after_selection(qtbot):
    events = []
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    preferences = FakePreferences(hide_application=True)

    def frame_provider(target):
        events.append(("capture", parent.isVisible(), target))
        return CapturedFrame(Image.new("RGB", (100, 80)), origin=(-10, 20))

    def selector(frame, mode, owner):
        events.append(("select", owner.isVisible(), mode, frame.origin))
        return (10, 20)

    session = CaptureSelectionSession(frame_provider, preferences, selector=selector)
    result = session.select("desktop", SelectionMode.POINT, parent)

    assert result is not None
    assert result.value == (10, 20)
    assert result.frame.origin == (-10, 20)
    assert events[0][:2] == ("capture", False)
    assert events[1][0:2] == ("select", False)
    assert parent.isVisible()


def test_selection_session_restores_after_cancel(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    session = CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        FakePreferences(hide_application=True),
        selector=lambda frame, mode, owner: None,
    )
    assert session.select("desktop", SelectionMode.REGION, parent) is None
    assert parent.isVisible()


def test_selection_session_restores_after_selector_error(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()

    def fail(frame, mode, owner):
        raise RuntimeError("overlay failed")

    session = CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        FakePreferences(hide_application=True),
        selector=fail,
    )
    with pytest.raises(RuntimeError, match="overlay failed"):
        session.select("desktop", SelectionMode.REGION, parent)
    assert parent.isVisible()
```

- [ ] **Step 2: Write failing region/template and point conversion tests**

Update `tests/ui/test_region_capture.py` so the selector receives `SelectionMode.REGION` and region release requires no accept call. Preserve the current exact template crop assertions.

Create `tests/ui/test_point_capture.py`:

```python
def test_desktop_point_adds_virtual_desktop_origin(session):
    service = PointCaptureService(session)
    selected = service.pick_point("desktop")
    assert selected == PointCapture(position=(-90, 45), coordinate_space="screen")


def test_window_point_stays_relative_to_captured_window(session):
    service = PointCaptureService(session)
    selected = service.pick_point("window:Game")
    assert selected == PointCapture(position=(10, 20), coordinate_space="target")


def test_cancel_keeps_point_empty(cancelled_session):
    assert PointCaptureService(cancelled_session).pick_point("desktop") is None
```

Use a session fixture whose frame origin is `(-100, 25)` and whose selector returns `(10, 20)`.

- [ ] **Step 3: Run tests and verify the session and point service are missing**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_region_capture.py tests/ui/test_point_capture.py -q
```

Expected: tests fail because the new selection session and point APIs do not exist.

- [ ] **Step 4: Implement the shared selection session**

Create `flow_runner/ui/capture_selection.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.application_visibility import temporarily_hidden_application
from flow_runner.ui.capture_preferences import CapturePreferences
from flow_runner.ui.native_capture_overlay import (
    Point,
    Region,
    SelectionMode,
    select_from_frame,
)

FrameProvider = Callable[[str], CapturedFrame]
Selector = Callable[
    [CapturedFrame, SelectionMode, QWidget | None],
    Point | Region | None,
]


@dataclass(frozen=True, slots=True)
class SelectionCapture:
    value: Point | Region
    frame: CapturedFrame


class CaptureSelectionSession:
    def __init__(
        self,
        frame_provider: FrameProvider,
        preferences: CapturePreferences,
        *,
        selector: Selector = select_from_frame,
    ) -> None:
        self._frame_provider = frame_provider
        self._preferences = preferences
        self._selector = selector

    def select(
        self,
        target: str,
        mode: SelectionMode,
        parent: QWidget | None = None,
    ) -> SelectionCapture | None:
        with temporarily_hidden_application(self._preferences.hide_application):
            frame = self._frame_provider(target)
            value = self._selector(frame, mode, parent)
        return None if value is None else SelectionCapture(value, frame)
```

- [ ] **Step 5: Refactor region capture and implement point capture**

Keep `Region`, `TemplateCapture`, and the public `RegionCaptureService` import path in `region_capture.py`. Replace its direct frame provider/selector ownership with a `CaptureSelectionSession`:

```python
class RegionCaptureService:
    def __init__(
        self,
        session: CaptureSelectionSession,
        *,
        template_directory: Path,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._session = session
        self._template_directory = template_directory
        self._now = now

    @property
    def template_directory(self) -> Path:
        return self._template_directory

    def pick_region(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> Region | None:
        captured = self._session.select(target, SelectionMode.REGION, parent)
        return None if captured is None else cast(Region, captured.value)

    def capture_template(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> TemplateCapture | None:
        captured = self._session.select(target, SelectionMode.REGION, parent)
        if captured is None:
            return None
        region = cast(Region, captured.value)
        self._template_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = self._template_directory / f"template_{timestamp}.png"
        captured.frame.image.crop(region).save(path, format="PNG")
        return TemplateCapture(region, path)


@dataclass(frozen=True, slots=True)
class PointCapture:
    position: tuple[int, int]
    coordinate_space: Literal["screen", "target"]


class PointCaptureService:
    def __init__(self, session: CaptureSelectionSession) -> None:
        self._session = session

    def pick_point(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> PointCapture | None:
        captured = self._session.select(target, SelectionMode.POINT, parent)
        if captured is None:
            return None
        x, y = cast(tuple[int, int], captured.value)
        if target == "desktop":
            return PointCapture(
                (x + captured.frame.origin[0], y + captured.frame.origin[1]),
                "screen",
            )
        if target.startswith("window:"):
            return PointCapture((x, y), "target")
        raise ValueError(f"不支持的鼠标目标：{target}")
```

Remove `RegionSelectionDialog`, `RegionSelectionCanvas`, `_fitted_rect()`, `map_selection_to_image()`, their dialog/button imports, and the old letterbox-mapping test. The new display-mapping and overlay tests replace that coverage.

- [ ] **Step 6: Run service and existing editor tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_region_capture.py tests/ui/test_point_capture.py tests/ui/test_step_editors.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the safe selection services**

```powershell
git add flow_runner/ui/capture_selection.py flow_runner/ui/region_capture.py tests/ui/test_region_capture.py tests/ui/test_point_capture.py
git commit -m "feat: unify region and point capture sessions"
```

### Task 5: Add Backward-Compatible Mouse Targets and Runtime Coordinate Conversion

**Files:**
- Modify: `flow_runner/capabilities/actions/mouse.py`
- Create: `flow_runner/infrastructure/windowing/geometry.py`
- Modify: `flow_runner/app.py`
- Modify: `tests/integration/test_actions.py`
- Modify: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Write failing model compatibility and runtime conversion tests**

Add to `tests/integration/test_actions.py`:

```python
def test_old_mouse_config_defaults_to_absolute_desktop_coordinates():
    config = MouseActionConfig.model_validate(
        {"operation": "click", "position": [10, 20]}
    )
    assert config.target == "desktop"
    assert config.coordinate_space == "screen"


@pytest.mark.asyncio
async def test_window_target_coordinate_uses_current_window_origin():
    mouse = FakeMouse()
    origins = []

    async def window_origin(target):
        origins.append(target)
        return (300, 200)

    action = MouseAction(mouse, window_origin=window_origin)
    result = await action.execute(
        MouseActionConfig(
            operation="click",
            target="window:Game",
            coordinate_space="target",
            position=(25, 40),
        ),
        None,
    )

    assert result.outcome is StepOutcome.SUCCESS
    assert origins == ["window:Game"]
    assert mouse.calls == [
        ("click", {"position": (325, 240), "button": "left", "clicks": 1, "interval": 0.0})
    ]


@pytest.mark.asyncio
async def test_screen_coordinate_on_window_target_is_not_offset_again():
    mouse = FakeMouse()
    action = MouseAction(
        mouse,
        window_origin=lambda target: pytest.fail("absolute binding was offset"),
    )
    await action.execute(
        MouseActionConfig(
            operation="click",
            target="window:Game",
            coordinate_space="screen",
            position=(325, 240),
        ),
        None,
    )
    assert mouse.calls[0][1]["position"] == (325, 240)


def test_window_mouse_action_locks_mouse_and_canonical_window_resource():
    action = MouseAction(FakeMouse())
    config = MouseActionConfig(
        operation="click",
        target="window:background:Game",
        position=(1, 2),
    )
    assert action.required_resources(config) == frozenset({"mouse", "window:Game"})
```

Add exact validation assertions:

```python
@pytest.mark.parametrize(
    "config",
    [
        {"operation": "click", "position": [1, 2], "coordinate_space": "target"},
        {"operation": "click", "position": [1, 2], "target": "process:game"},
    ],
)
def test_mouse_config_rejects_invalid_target_coordinate_combinations(config):
    with pytest.raises(ValueError):
        MouseActionConfig.model_validate(config)
```

- [ ] **Step 2: Run focused tests and verify new fields are absent**

Run:

```powershell
python -m pytest tests/integration/test_actions.py -q
```

Expected: failures show `target`, `coordinate_space`, and `window_origin` are not implemented.

- [ ] **Step 3: Implement async Win32 window-origin lookup**

Create `flow_runner/infrastructure/windowing/geometry.py`:

```python
import asyncio
import importlib
from typing import Protocol

from flow_runner.domain.capture_targets import parse_window_capture_target

Point = tuple[int, int]


class WindowOriginProvider(Protocol):
    async def origin(self, target: str) -> Point: ...


class Win32WindowGeometry:
    def __init__(self, backend: object | None = None) -> None:
        self.backend = backend or importlib.import_module("win32gui")

    async def origin(self, target: str) -> Point:
        _mode, title = parse_window_capture_target(target)
        return await asyncio.to_thread(self._origin_for_title, title)

    def _origin_for_title(self, title: str) -> Point:
        matches: list[int] = []

        def visit(handle: int, extra: object) -> None:
            del extra
            if self.backend.IsWindowVisible(handle) and title in self.backend.GetWindowText(handle):
                matches.append(handle)

        self.backend.EnumWindows(visit, None)
        if not matches:
            raise LookupError(f"找不到目标窗口：{title}")
        left, top, right, bottom = self.backend.GetWindowRect(matches[0])
        if right <= left or bottom <= top:
            raise ValueError(f"目标窗口边界无效：{(left, top, right, bottom)}")
        return int(left), int(top)
```

- [ ] **Step 4: Implement mouse config validation and coordinate resolution**

In `flow_runner/capabilities/actions/mouse.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import model_validator

from flow_runner.domain.capture_targets import canonical_capture_target
from flow_runner.domain.errors import ActionError

WindowOrigin = Callable[[str], Awaitable[tuple[int, int]]]


class MouseActionConfig(BaseModel):
    target: str = "desktop"
    coordinate_space: Literal["screen", "target"] = "screen"

    @model_validator(mode="after")
    def validate_target_coordinate_space(self) -> "MouseActionConfig":
        if self.target != "desktop" and not self.target.startswith("window:"):
            raise ValueError("mouse target must be desktop or window:<title>")
        if self.coordinate_space == "target" and not self.target.startswith("window:"):
            raise ValueError("target coordinates require a window target")
        return self
```

Keep every existing `MouseActionConfig` field unchanged and append the two fields above after `settle_delay`. Add `window_origin: WindowOrigin | None = None` to `MouseAction.__init__`. At the start of `execute()`:

```python
position = config.position
if config.coordinate_space == "target":
    if self.window_origin is None:
        raise ActionError("窗口相对坐标解析器未配置")
    origin = await self.window_origin(config.target)
    position = (position[0] + origin[0], position[1] + origin[1])
position = (position[0] + config.offset[0], position[1] + config.offset[1])
```

Retain the current jitter, settle delay, click/move/scroll/down/up/drag behavior after this conversion. In `required_resources()`, add `canonical_capture_target(config.target)` only for window targets.

- [ ] **Step 5: Wire the geometry provider into both registries**

In `create_application()`, create one `Win32WindowGeometry`. Add it to `_build_registry()` and register mouse actions as:

```python
registry.register_action(
    MouseAction(mouse_device, window_origin=window_geometry.origin)
)
```

Pass the same provider to the execution registry built by `step_executor_factory`. Update app smoke-test helpers for the expanded `_build_registry()` signature.

- [ ] **Step 6: Run action, engine, and app smoke tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/integration/test_actions.py tests/unit/engine/test_step_executor.py tests/ui/test_app_smoke.py -q
```

Expected: all tests pass, including existing result-binding revalidation tests.

- [ ] **Step 7: Commit mouse target runtime support**

```powershell
git add flow_runner/capabilities/actions/mouse.py flow_runner/infrastructure/windowing/geometry.py flow_runner/app.py tests/integration/test_actions.py tests/ui/test_app_smoke.py
git commit -m "feat: execute window-relative mouse coordinates"
```

### Task 6: Add Point Picking and the Hide Toggle to Guided Forms

**Files:**
- Modify: `flow_runner/ui/editors/model_form.py`
- Modify: `flow_runner/ui/editors/action_editor.py`
- Modify: `flow_runner/ui/editor_metadata.py`
- Modify: `flow_runner/ui/localization.py`
- Modify: `flow_runner/ui/panels/property_panel.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/app.py`
- Modify: `tests/ui/test_step_editors.py`
- Modify: `tests/ui/test_property_panel_modes.py`
- Modify: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Write failing model-form point-picker tests**

Add to `tests/ui/test_step_editors.py`:

```python
def test_mouse_form_point_picker_uses_its_target_and_sets_coordinate_space(qtbot):
    calls = []

    def pick_point(target):
        calls.append(target)
        return PointCapture(position=(25, 40), coordinate_space="target")

    form = ModelForm(MouseActionConfig, pick_point=pick_point)
    qtbot.addWidget(form)
    form.editor("target").setText("window:Game")
    position = form.editor("position")
    position.point_button.click()

    assert calls == ["window:Game"]
    assert form.values()["position"] == (25, 40)
    assert form.values()["coordinate_space"] == "target"


def test_mouse_point_cancel_preserves_existing_values(qtbot):
    form = ModelForm(MouseActionConfig, pick_point=lambda target: None)
    qtbot.addWidget(form)
    form.set_values(
        {
            "target": "window:Game",
            "coordinate_space": "target",
            "position": (8, 9),
        }
    )
    form.editor("position").point_button.click()
    assert form.values()["position"] == (8, 9)
    assert form.values()["coordinate_space"] == "target"


def test_switching_mouse_position_to_binding_forces_screen_space(qtbot):
    form = ModelForm(MouseActionConfig)
    qtbot.addWidget(form)
    form.set_values(
        {
            "target": "window:Game",
            "coordinate_space": "target",
            "position": (8, 9),
        }
    )
    form.editor("position").setBinding("$result.primary.position")
    assert form.values()["coordinate_space"] == "screen"
```

Assert the point button is visible only for `MouseActionConfig.position`; region forms retain `框选区域` and other tuple fields have no point button.

- [ ] **Step 2: Write failing property-panel preference tests**

Add to `tests/ui/test_property_panel_modes.py`:

```python
def test_capture_hide_checkbox_persists_without_marking_project_pending(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "capture.ini"), QSettings.Format.IniFormat)
    preferences = CapturePreferences(settings)
    panel = _panel(qtbot, capture_preferences=preferences)

    panel.hide_during_capture_check.setChecked(True)

    assert preferences.hide_application
    assert not panel.has_pending_edits
```

Add this action-editor integration test:

```python
def test_action_editor_serializes_picked_window_point(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    editor = ActionEditor(
        capabilities,
        pick_point=lambda target: PointCapture((25, 40), "target"),
    )
    qtbot.addWidget(editor)
    target = editor.config_form.editor("target")
    target.setText("window:Game")
    editor.config_form.editor("position").point_button.click()
    editor.add_button.click()

    assert editor.action_specs()[0].config == {
        "operation": "click",
        "position": (25, 40),
        "offset": (0, 0),
        "button": "left",
        "clicks": 1,
        "interval": 0.0,
        "duration": 0.0,
        "scroll_units": 1,
        "jitter_pixels": 0,
        "settle_delay": 0.0,
        "target": "window:Game",
        "coordinate_space": "target",
    }
```

- [ ] **Step 3: Run tests and verify point-picker arguments are absent**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py -q
```

Expected: failures show `pick_point`, `point_button`, and the hide checkbox are missing.

- [ ] **Step 4: Extend tuple editors and ModelForm for mouse point picking**

Add a distinct `point_button` to `TupleFieldEditor`:

```python
self.point_button = QPushButton("点选坐标")
self.point_button.setObjectName("pickMousePointButton")
self.point_button.setVisible(allow_point_pick)
layout.addWidget(self.point_button)
```

Add `pick_point: Callable[[str], PointCapture | None] | None = None` to `ModelForm.__init__`. Set `allow_point_pick` only when `model_type is MouseActionConfig and name == "position"`. Connect the point button to:

```python
def _pick_point(self) -> None:
    if self._pick_point_callback is None:
        return
    try:
        captured = self._pick_point_callback(self._capture_target())
    except Exception as error:
        self._report_error(f"点选坐标失败：{error}")
        return
    if captured is None:
        return
    position = self.editors.get("position")
    coordinate_space = self.editors.get("coordinate_space")
    if isinstance(position, TupleFieldEditor) and isinstance(coordinate_space, QComboBox):
        blocked = self.blockSignals(True)
        try:
            position.setValue(captured.position)
            coordinate_space.setCurrentIndex(
                coordinate_space.findData(captured.coordinate_space)
            )
        finally:
            self.blockSignals(blocked)
        self.changed.emit()
```

Connect the mouse position mode combo to:

```python
def _update_mouse_coordinate_space(self) -> None:
    position = self.editors.get("position")
    coordinate_space = self.editors.get("coordinate_space")
    if not (
        isinstance(position, TupleFieldEditor)
        and isinstance(coordinate_space, QComboBox)
        and position.mode_combo.currentData() == "binding"
    ):
        return
    index = coordinate_space.findData("screen")
    if index >= 0:
        coordinate_space.setCurrentIndex(index)
```

Call this once after loading mouse values and on every position-mode change. Do not change coordinate space for ordinary fixed-value manual edits.

Also change the three selection error paths to preserve raw details behind Chinese context:

```python
self._report_error(f"框选区域失败：{error}")
self._report_error(f"框选并截图失败：{error}")
self._report_error(f"点选坐标失败：{error}")
```

- [ ] **Step 5: Propagate point capture through ActionEditor and PropertyPanel**

Add `pick_point` to `ActionEditor.__init__`, store it, and pass it to every rebuilt `ModelForm`. Add `point_capture: PointCaptureService | None` and `capture_preferences: CapturePreferences | None` to `PropertyPanel.__init__`. Construct `ActionEditor` with:

```python
pick_point=(
    (lambda target: point_capture.pick_point(target, self))
    if point_capture is not None
    else None
)
```

Create `hide_during_capture_check = QCheckBox("框选时隐藏程序界面")`, initialize it from `CapturePreferences`, and add it before `show_advanced_check`. Connect it directly to the preference setter; do not connect it to `_mark_pending()`.

- [ ] **Step 6: Update common fields and localized labels**

Change mouse common fields to include `target`:

```python
"input.mouse": frozenset(
    {"target", "operation", "position", "button", "clicks"}
),
```

Keep `coordinate_space` advanced. Add `coordinate_space` → `坐标空间`, `screen` → `绝对屏幕坐标`, and `target` → `目标相对坐标` choice labels. Because `target` is also used by visual conditions, use this label expression in the ModelForm field loop:

```python
label = (
    "操作目标"
    if model_type is MouseActionConfig and name == "target"
    else field_label(name)
)
self.form_layout.addField(label, editor, name)
```

This retains `检测目标` for condition forms.

- [ ] **Step 7: Wire services through MainWindow and create_application**

Add `point_capture` and `capture_preferences` optional parameters to `MainWindow`, then pass them to `PropertyPanel`.

In `create_application()`:

```python
capture_preferences = CapturePreferences()
selection_session = CaptureSelectionSession(
    lambda target: _capture_frame_for_ui(capture, target),
    capture_preferences,
)
region_capture = RegionCaptureService(
    selection_session,
    template_directory=paths.template_directory,
)
point_capture = PointCaptureService(selection_session)
```

Pass all three objects into `MainWindow`. Update app smoke assertions to verify the checkbox and both services are wired while the project remains clean.

- [ ] **Step 8: Run all guided-editor and smoke tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py tests/ui/test_region_capture.py tests/ui/test_point_capture.py tests/ui/test_app_smoke.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit guided point picking and preference UI**

```powershell
git add flow_runner/ui/editors/model_form.py flow_runner/ui/editors/action_editor.py flow_runner/ui/editor_metadata.py flow_runner/ui/localization.py flow_runner/ui/panels/property_panel.py flow_runner/ui/main_window.py flow_runner/app.py tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py tests/ui/test_app_smoke.py
git commit -m "feat: add guided mouse point picking"
```

### Task 7: Compatibility, Documentation, Full Verification, and Real-Windows Handoff

**Files:**
- Modify: `README.md`
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md`
- Modify: `tests/ui/test_localized_ui.py`
- Modify: `tests/ui/test_model_form_modes.py`
- Modify: `tests/unit/capabilities/test_registry.py`

- [ ] **Step 1: Add final compatibility and localization coverage**

Extend localization coverage with exact assertions:

```python
def test_mouse_coordinate_fields_and_choices_are_localized():
    assert field_label("coordinate_space") == "坐标空间"
    assert choice_label("screen") == "绝对屏幕坐标"
    assert choice_label("target") == "目标相对坐标"
```

Add a project round-trip test:

```python
def test_legacy_mouse_action_without_target_round_trips_as_absolute_desktop(registry):
    project = Project.model_validate(
        {
            "name": "legacy",
            "groups": [
                {
                    "name": "g",
                    "workflows": [
                        {
                            "name": "w",
                            "steps": [
                                {
                                    "name": "click",
                                    "actions": [
                                        {
                                            "capability": "input.mouse",
                                            "config": {
                                                "operation": "click",
                                                "position": [10, 20],
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    registry.validate_project_or_raise(project)
    action = project.groups[0].workflows[0].steps[0].actions[0]
    assert action.config == {"operation": "click", "position": [10, 20]}
```

This assertion protects the raw legacy JSON from eager migration while runtime model defaults provide compatibility.

- [ ] **Step 2: Run the complete automated suite before documentation claims**

Run:

```powershell
python -m compileall flow_runner tests
python -m ruff check .
python -m ruff format --check .
python -m mypy flow_runner
python -m pip check
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
```

Expected: every command exits 0. Record the exact pytest count and mypy source count.

- [ ] **Step 3: Update README to describe only implemented behavior**

Document:

- the `点选坐标` button and independent mouse target;
- desktop absolute versus window target-relative fixed coordinates;
- dynamic bindings remain absolute;
- native frozen desktop/window overlay;
- region release and point click complete immediately;
- Esc cancellation;
- the locally remembered hide-application checkbox.

Remove the old statement that selection uses a fixed dialog or an OK button. Do not claim mixed-DPI/multi-monitor real acceptance until it is performed.

- [ ] **Step 4: Add concrete real-Windows checklist entries**

Append unchecked items:

```markdown
- [ ] At 100%, 125%, and 150% DPI, select a desktop region and point; verify native image detail and exact coordinates.
- [ ] On a negative-origin secondary monitor, verify complete virtual-desktop coverage and cross-screen selection.
- [ ] Select a full window region and point; verify mouse release/click completes immediately and Esc cancels.
- [ ] Toggle hide-application off and on, restart, and verify both behavior and local preference persistence.
- [ ] Pick a window-relative point, move the window, execute the action, and verify the same in-window location is clicked.
- [ ] Execute a `$result...position` mouse action and verify no window-origin offset is added twice.
- [ ] Capture a template and verify the PNG dimensions and pixels exactly match the selected native region.
```

- [ ] **Step 5: Review all diffs and protect runtime data**

Run:

```powershell
git status --short
git diff --check
git diff --stat
git diff -- data/project.json
```

Expected: `data/project.json` shows only the user's existing column-width change and is never staged. Review every other path against this plan.

- [ ] **Step 6: Perform or hand off real Windows acceptance**

Launch with the global Python entry point. Perform every new checklist item with the real GUI when Windows Computer Use is available. If it is unavailable, leave the boxes unchecked and explicitly hand them to the user; do not substitute offscreen tests for DPI, text fitting, physical clicking, or multi-monitor evidence.

- [ ] **Step 7: Commit documentation and verification records**

```powershell
git add README.md REAL_ENVIRONMENT_CHECKLIST.md tests/ui/test_localized_ui.py tests/ui/test_model_form_modes.py tests/unit/capabilities/test_registry.py
git commit -m "docs: describe native coordinate selection"
```

- [ ] **Step 8: Final branch verification**

Run once more after the final commit:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
git status --short --branch
```

Expected: the complete suite passes; only the user's `data/project.json` remains modified.
