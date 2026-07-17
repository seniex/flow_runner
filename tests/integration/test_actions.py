import asyncio

import pytest

from flow_runner.capabilities.actions.keyboard import KeyboardAction, KeyboardActionConfig
from flow_runner.capabilities.actions.mouse import MouseAction, MouseActionConfig
from flow_runner.capabilities.actions.process import LaunchProcessAction, LaunchProcessConfig
from flow_runner.capabilities.actions.script import PlaybackScriptAction, PlaybackScriptConfig
from flow_runner.capabilities.actions.variables import SetVariableAction, SetVariableConfig
from flow_runner.capabilities.actions.wait import WaitAction, WaitActionConfig
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ActionError
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import StepContext
from flow_runner.infrastructure.input.keyboard import PyAutoGuiKeyboardDevice
from flow_runner.infrastructure.input.mouse import PyAutoGuiMouseDevice
from flow_runner.infrastructure.input.recording import (
    RecordedEvent,
    RecordingPlayer,
    RecordingRecorder,
    RecordingStore,
)
from flow_runner.infrastructure.processes import launch as process_launch_module
from flow_runner.infrastructure.processes.launch import WindowsProcessLauncher


@pytest.mark.asyncio
async def test_wait_action_uses_injected_cancellable_sleep():
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    result = await WaitAction(sleep).execute(WaitActionConfig(seconds=1.25), StepContext())

    assert result.outcome is StepOutcome.SUCCESS
    assert delays == [1.25]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["task", "workflow", "persistent"])
async def test_set_variable_action_writes_the_selected_scope(scope):
    context = StepContext()
    action = SetVariableAction()

    result = await action.execute(SetVariableConfig(scope=scope, name="counter", value=3), context)

    assert result.outcome is StepOutcome.SUCCESS
    assert getattr(context, f"{scope}_variables")["counter"] == 3


def test_wait_and_variable_actions_declare_no_desktop_resources():
    assert (
        WaitAction(lambda seconds: None).required_resources(WaitActionConfig(seconds=0))
        == frozenset()
    )
    assert (
        SetVariableAction().required_resources(SetVariableConfig(scope="task", name="x", value=1))
        == frozenset()
    )


class FakeMouse:
    def __init__(self):
        self.calls = []

    async def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    async def move(self, **kwargs):
        self.calls.append(("move", kwargs))

    async def scroll(self, **kwargs):
        self.calls.append(("scroll", kwargs))

    async def button_down(self, **kwargs):
        self.calls.append(("button_down", kwargs))

    async def button_up(self, **kwargs):
        self.calls.append(("button_up", kwargs))

    async def drag(self, **kwargs):
        self.calls.append(("drag", kwargs))


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    async def press(self, key, count, interval):
        self.calls.append(("press", key, count, interval))

    async def hotkey(self, keys):
        self.calls.append(("hotkey", keys))

    async def write(self, text, interval, mode="keys"):
        self.calls.append(("write", text, interval, mode))

    async def key_down(self, key):
        self.calls.append(("key_down", key))

    async def key_up(self, key):
        self.calls.append(("key_up", key))


def test_old_mouse_config_defaults_to_absolute_desktop_coordinates():
    config = MouseActionConfig.model_validate({"operation": "click", "position": [10, 20]})
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
        (
            "click",
            {
                "position": (325, 240),
                "button": "left",
                "clicks": 1,
                "interval": 0.0,
            },
        )
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


@pytest.mark.asyncio
async def test_target_coordinates_require_window_origin_provider():
    action = MouseAction(FakeMouse())
    with pytest.raises(ActionError, match="窗口相对坐标解析器未配置"):
        await action.execute(
            MouseActionConfig(
                operation="click",
                target="window:Game",
                coordinate_space="target",
                position=(25, 40),
            ),
            None,
        )


def test_window_mouse_action_locks_mouse_and_canonical_window_resource():
    action = MouseAction(FakeMouse())
    config = MouseActionConfig(
        operation="click",
        target="window:background:Game",
        position=(1, 2),
    )
    assert action.required_resources(config) == frozenset({"mouse", "window:Game"})


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


@pytest.mark.asyncio
async def test_mouse_and_keyboard_actions_use_device_adapters():
    mouse = FakeMouse()
    keyboard = FakeKeyboard()

    mouse_result = await MouseAction(mouse).execute(
        MouseActionConfig(operation="click", position=(10, 20), button="right", clicks=2),
        StepContext(),
    )
    key_result = await KeyboardAction(keyboard).execute(
        KeyboardActionConfig(operation="hotkey", keys=["ctrl", "s"]), StepContext()
    )

    assert mouse_result.outcome is StepOutcome.SUCCESS
    assert key_result.outcome is StepOutcome.SUCCESS
    assert mouse.calls == [
        (
            "click",
            {"position": (10, 20), "button": "right", "clicks": 2, "interval": 0.0},
        )
    ]
    assert keyboard.calls == [("hotkey", ("ctrl", "s"))]


@pytest.mark.asyncio
async def test_mouse_action_supports_result_offset_hold_release_and_drag():
    mouse = FakeMouse()
    action = MouseAction(mouse)

    await action.execute(
        MouseActionConfig(
            operation="button_down",
            position=(10, 20),
            offset=(3, -2),
            button="left",
        ),
        StepContext(),
    )
    await action.execute(
        MouseActionConfig(
            operation="drag",
            position=(30, 40),
            offset=(-5, 2),
            button="right",
            duration=0.5,
        ),
        StepContext(),
    )
    await action.execute(
        MouseActionConfig(operation="button_up", position=(50, 60), button="left"),
        StepContext(),
    )

    assert mouse.calls == [
        ("button_down", {"position": (13, 18), "button": "left"}),
        (
            "drag",
            {"position": (25, 42), "button": "right", "duration": 0.5},
        ),
        ("button_up", {"position": (50, 60), "button": "left"}),
    ]


@pytest.mark.asyncio
async def test_mouse_action_applies_configured_coordinate_jitter_once():
    mouse = FakeMouse()
    action = MouseAction(mouse, randint=lambda lower, upper: upper)

    await action.execute(
        MouseActionConfig(
            operation="click",
            position=(10, 20),
            jitter_pixels=3,
            clicks=2,
        ),
        StepContext(),
    )

    assert mouse.calls == [
        (
            "click",
            {"position": (13, 23), "button": "left", "clicks": 2, "interval": 0.0},
        )
    ]


@pytest.mark.asyncio
async def test_mouse_click_can_move_and_settle_before_clicking_same_jittered_position():
    mouse = FakeMouse()
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    action = MouseAction(
        mouse,
        randint=lambda lower, upper: upper,
        sleep=sleep,
    )

    await action.execute(
        MouseActionConfig(
            operation="click",
            position=(10, 20),
            jitter_pixels=3,
            duration=0.015,
            settle_delay=0.02,
        ),
        StepContext(),
    )

    assert mouse.calls == [
        ("move", {"position": (13, 23), "duration": 0.015}),
        (
            "click",
            {"position": (13, 23), "button": "left", "clicks": 1, "interval": 0.0},
        ),
    ]
    assert delays == [0.02]


@pytest.mark.asyncio
async def test_keyboard_action_supports_explicit_key_down_and_key_up():
    keyboard = FakeKeyboard()
    action = KeyboardAction(keyboard)

    await action.execute(
        KeyboardActionConfig(operation="key_down", key="shift"),
        StepContext(),
    )
    await action.execute(
        KeyboardActionConfig(operation="key_up", key="shift"),
        StepContext(),
    )

    assert keyboard.calls == [("key_down", "shift"), ("key_up", "shift")]


@pytest.mark.asyncio
async def test_process_and_script_actions_normalize_inputs(tmp_path):
    launches = []
    playbacks = []
    app = tmp_path / "game.exe"
    script = tmp_path / "run.json"
    app.write_bytes(b"")
    script.write_text("[]", encoding="utf-8")

    async def launch(path, arguments, run_as_admin, working_directory, hide_window):
        launches.append((path, arguments, run_as_admin, working_directory, hide_window))

    async def playback(path, speed, max_gap, jitter_ms):
        playbacks.append((path, speed, max_gap, jitter_ms))

    process_result = await LaunchProcessAction(launch).execute(
        LaunchProcessConfig(
            path=app,
            arguments=["--safe"],
            run_as_admin=True,
            working_directory=tmp_path,
            hide_window=True,
        ),
        StepContext(),
    )
    script_result = await PlaybackScriptAction(playback).execute(
        PlaybackScriptConfig(path=script, speed=2.0, max_gap=1.5, jitter_ms=25), StepContext()
    )

    assert process_result.outcome is StepOutcome.SUCCESS
    assert script_result.outcome is StepOutcome.SUCCESS
    assert launches == [(app.resolve(), ("--safe",), True, tmp_path.resolve(), True)]
    assert playbacks == [(script.resolve(), 2.0, 1.5, 25)]


@pytest.mark.asyncio
async def test_windows_process_launcher_selects_normal_or_admin_backend(tmp_path):
    calls = []

    def popen(command, *, cwd, hide_window):
        calls.append(("popen", command, cwd, hide_window))

    def shell_execute(path, arguments, working_directory, hide_window):
        calls.append(("admin", path, arguments, working_directory, hide_window))

    launcher = WindowsProcessLauncher(popen=popen, shell_execute=shell_execute)
    path = (tmp_path / "game.exe").resolve()
    working_directory = tmp_path.resolve()
    await launcher(path, ("--safe",), False, working_directory, True)
    await launcher(path, ("--admin",), True, working_directory, False)

    assert calls == [
        ("popen", [str(path), "--safe"], working_directory, True),
        ("admin", path, "--admin", working_directory, False),
    ]


def test_hidden_popen_uses_create_no_window(monkeypatch, tmp_path):
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(process_launch_module.subprocess, "Popen", popen)
    monkeypatch.setattr(process_launch_module.subprocess, "CREATE_NO_WINDOW", 0x08000000)

    process_launch_module._popen(
        ["python.exe", "helper.py"],
        cwd=tmp_path,
        hide_window=True,
    )

    assert calls == [
        (
            ["python.exe", "helper.py"],
            {"cwd": tmp_path, "creationflags": 0x08000000},
        )
    ]


@pytest.mark.asyncio
async def test_keyboard_action_exposes_keys_unicode_and_clipboard_text_modes():
    keyboard = FakeKeyboard()
    action = KeyboardAction(keyboard)

    for mode in ("keys", "unicode", "clipboard"):
        await action.execute(
            KeyboardActionConfig(operation="write", text="测试", text_mode=mode),
            StepContext(),
        )

    assert keyboard.calls == [
        ("write", "测试", 0.0, "keys"),
        ("write", "测试", 0.0, "unicode"),
        ("write", "测试", 0.0, "clipboard"),
    ]


def test_recording_store_round_trips_typed_events(tmp_path):
    path = tmp_path / "recording.json"
    events = [RecordedEvent(timestamp=0.25, kind="mouse_click", data={"x": 1, "y": 2})]

    RecordingStore.save(path, events)

    assert RecordingStore.load(path) == events


@pytest.mark.asyncio
async def test_recording_player_applies_speed_gap_and_dispatches(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="move", data={"x": 4, "y": 5}),
            RecordedEvent(timestamp=4.0, kind="click", data={"x": 4, "y": 5, "button": "left"}),
        ],
    )
    delays = []
    calls = []
    now = 0.0

    async def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += seconds

    class Backend:
        def moveTo(self, x, y):
            calls.append(("move", x, y))

        def click(self, **kwargs):
            calls.append(("click", kwargs))

    await RecordingPlayer(sleep=sleep, backend=Backend(), clock=lambda: now)(
        path, speed=2.0, max_gap=1.0
    )

    assert delays == [0.0, 1.0]
    assert calls == [
        ("move", 4, 5),
        ("click", {"x": 4, "y": 5, "button": "left"}),
    ]


@pytest.mark.asyncio
async def test_recording_player_applies_per_event_jitter_without_negative_delay(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="move", data={"x": 1, "y": 2}),
            RecordedEvent(timestamp=1.0, kind="move", data={"x": 3, "y": 4}),
        ],
    )
    delays = []
    jitters = iter([-0.05, 0.05])
    now = 0.0

    async def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += seconds

    class Backend:
        def moveTo(self, x, y):
            pass

    await RecordingPlayer(
        sleep=sleep,
        backend=Backend(),
        uniform=lambda lower, upper: next(jitters),
        clock=lambda: now,
    )(path, speed=1.0, max_gap=2.0, jitter_ms=100)

    assert delays == [0.0, 1.05]


@pytest.mark.asyncio
async def test_recording_player_treats_zero_max_gap_as_unlimited(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="move", data={"x": 1, "y": 2}),
            RecordedEvent(timestamp=4.0, kind="move", data={"x": 3, "y": 4}),
        ],
    )
    delays = []
    now = 0.0

    async def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += seconds

    class Backend:
        def moveTo(self, x, y):
            pass

    await RecordingPlayer(sleep=sleep, backend=Backend(), clock=lambda: now)(
        path, speed=1.0, max_gap=0.0
    )

    assert delays == [0.0, 4.0]


@pytest.mark.asyncio
async def test_recording_playback_freezes_between_events_while_paused(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="move", data={"x": 1, "y": 2}),
            RecordedEvent(
                timestamp=0.1,
                kind="click",
                data={"x": 1, "y": 2, "button": "left"},
            ),
            RecordedEvent(timestamp=0.2, kind="move", data={"x": 3, "y": 4}),
        ],
    )
    token = CancellationToken()
    calls = []

    class Backend:
        def moveTo(self, x, y):
            calls.append(("move", x, y))

        def click(self, **kwargs):
            calls.append(("click", kwargs))

    task = asyncio.create_task(
        RecordingPlayer(
            sleep=token.sleep,
            clock=token.active_time,
            backend=Backend(),
        )(path, speed=1.0, max_gap=1.0)
    )
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert calls == [("move", 1, 2)]
    token.pause()
    await asyncio.sleep(0.03)
    assert calls == [("move", 1, 2)]
    token.resume()
    for _ in range(200):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.001)
    assert [call[0] for call in calls] == ["move", "click"]
    await asyncio.sleep(0.03)
    assert [call[0] for call in calls] == ["move", "click"]
    await asyncio.wait_for(task, timeout=0.3)
    assert [call[0] for call in calls] == ["move", "click", "move"]


@pytest.mark.asyncio
async def test_recording_player_disables_and_restores_pyautogui_pause(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [RecordedEvent(timestamp=0.0, kind="move", data={"x": 1, "y": 2})],
    )
    pauses = []

    class Backend:
        PAUSE = 0.1

        def moveTo(self, x, y):
            pauses.append(self.PAUSE)

    backend = Backend()
    await RecordingPlayer(sleep=asyncio.sleep, backend=backend)(path, speed=1.0, max_gap=0.0)

    assert pauses == [0]
    assert backend.PAUSE == 0.1


@pytest.mark.asyncio
async def test_recording_player_releases_held_keys_when_cancelled(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="key_press", data={"key": "shift"}),
            RecordedEvent(timestamp=10.0, kind="key_release", data={"key": "shift"}),
        ],
    )
    calls = []
    sleeps = 0

    async def sleep(seconds):
        nonlocal sleeps
        del seconds
        sleeps += 1
        if sleeps == 2:
            raise RuntimeError("cancelled")

    class Backend:
        def keyDown(self, key):
            calls.append(("keyDown", key))

        def keyUp(self, key):
            calls.append(("keyUp", key))

    with pytest.raises(RuntimeError, match="cancelled"):
        await RecordingPlayer(sleep=sleep, backend=Backend())(
            path,
            speed=1.0,
            max_gap=10.0,
        )

    assert calls == [("keyDown", "shift"), ("keyUp", "shift")]


def test_recording_recorder_captures_timed_events_and_saves(tmp_path):
    callbacks = {}

    class Listener:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    listener = Listener()

    def factory(**provided):
        callbacks.update(provided)
        return listener

    times = iter([10.0, 10.1, 10.2, 10.3, 10.4])
    recorder = RecordingRecorder(listener_factory=factory, clock=lambda: next(times))
    path = tmp_path / "recording.json"

    recorder.start()
    callbacks["on_move"](4, 5)
    callbacks["on_click"](4, 5, "left", True)
    callbacks["on_press"]("A")
    events = recorder.stop(path)

    assert listener.started and listener.stopped
    assert [event.kind for event in events] == ["move", "click", "key_press"]
    assert [event.timestamp for event in events] == pytest.approx([0.1, 0.2, 0.3])
    assert RecordingStore.load(path) == events


def test_recording_recorder_saves_identical_primary_and_latest_files(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    times = iter([10.0, 10.1])
    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener(),
        clock=lambda: next(times),
    )
    archive = tmp_path / "recording_20260717_083314.json"
    latest = tmp_path / "latest.json"

    recorder.start()
    callbacks["on_move"](8, 9)
    events = recorder.stop(archive, additional_paths=(latest,))

    assert RecordingStore.load(archive) == events
    assert RecordingStore.load(latest) == events
    assert archive.read_bytes() == latest.read_bytes()


def test_recording_recorder_excludes_configured_control_key_pairs(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener()
    )
    recorder.set_ignored_keys({"F6", "F10"})
    recorder.start()
    callbacks["on_release"]("f6")
    callbacks["on_press"]("f10")
    callbacks["on_release"]("f10")
    callbacks["on_press"]("a")
    callbacks["on_release"]("a")

    events = recorder.stop(tmp_path / "recording.json")

    assert [(event.kind, event.data["key"]) for event in events] == [
        ("key_press", "a"),
        ("key_release", "a"),
    ]


def test_recording_recorder_updates_ignored_keys_during_recording(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener()
    )
    recorder.set_ignored_keys({"F6"})
    recorder.start()
    callbacks["on_press"]("f6")
    recorder.set_ignored_keys({"F10"})
    callbacks["on_press"]("f6")
    callbacks["on_press"]("f10")

    events = recorder.stop(tmp_path / "recording.json")

    assert [event.data["key"] for event in events] == ["f6"]


def test_recording_recorder_excludes_paused_input_and_time(tmp_path):
    now = 10.0
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener(),
        clock=lambda: now,
    )
    recorder.start()
    now = 11.0
    callbacks["on_press"]("a")
    recorder.pause()
    recorder.pause()
    now = 16.0
    callbacks["on_press"]("ignored")
    recorder.resume()
    recorder.resume()
    now = 17.0
    callbacks["on_press"]("b")

    events = recorder.stop(tmp_path / "recording.json")

    assert [event.data["key"] for event in events] == ["a", "b"]
    assert [event.timestamp for event in events] == pytest.approx([1.0, 2.0])


def test_recording_recorder_stop_while_paused_saves_pre_pause_events(tmp_path):
    now = 20.0
    callbacks = {}

    class Listener:
        def __init__(self):
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    listener = Listener()
    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or listener,
        clock=lambda: now,
    )
    recorder.start()
    now = 21.0
    callbacks["on_press"]("a")
    recorder.pause()
    now = 25.0
    callbacks["on_press"]("ignored")

    events = recorder.stop(tmp_path / "recording.json")

    assert listener.stopped
    assert not recorder.is_recording
    assert [event.data["key"] for event in events] == ["a"]


def test_recording_recorder_save_failure_still_stops_listener(tmp_path, monkeypatch):
    class Listener:
        def __init__(self):
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    listener = Listener()
    recorder = RecordingRecorder(listener_factory=lambda **provided: listener)
    recorder.start()

    def fail_save(path, events):
        del path, events
        raise OSError("disk full")

    monkeypatch.setattr(RecordingStore, "save", fail_save)

    with pytest.raises(OSError, match="disk full"):
        recorder.stop(tmp_path / "recording.json")

    assert listener.stopped
    assert not recorder.is_recording


@pytest.mark.asyncio
async def test_pyautogui_devices_translate_actions_to_backend_calls():
    class Backend:
        def __init__(self):
            self.calls = []

        def click(self, **kwargs):
            self.calls.append(("click", kwargs))

        def moveTo(self, *args, **kwargs):
            self.calls.append(("moveTo", args, kwargs))

        def position(self):
            return (0, 0)

        def scroll(self, units):
            self.calls.append(("scroll", units))

        def mouseDown(self, **kwargs):
            self.calls.append(("mouseDown", kwargs))

        def mouseUp(self, **kwargs):
            self.calls.append(("mouseUp", kwargs))

        def press(self, key, presses, interval):
            self.calls.append(("press", key, presses, interval))

        def hotkey(self, *keys):
            self.calls.append(("hotkey", keys))

        def keyDown(self, key):
            self.calls.append(("keyDown", key))

        def keyUp(self, key):
            self.calls.append(("keyUp", key))

        def write(self, text, interval):
            self.calls.append(("write", text, interval))

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)
    keyboard = PyAutoGuiKeyboardDevice(backend)

    await mouse.click(position=(1, 2), button="left", clicks=2, interval=0.1)
    await mouse.scroll(position=(3, 4), units=-5)
    await mouse.button_down(position=(5, 6), button="right")
    await mouse.button_up(position=(5, 6), button="right")
    await mouse.drag(position=(7, 8), button="left", duration=0.0)
    await keyboard.hotkey(("ctrl", "s"))
    await keyboard.key_down("shift")
    await keyboard.key_up("shift")

    assert backend.calls == [
        ("click", {"x": 1, "y": 2, "button": "left", "clicks": 1, "interval": 0.0}),
        ("click", {"x": 1, "y": 2, "button": "left", "clicks": 1, "interval": 0.0}),
        ("moveTo", (3, 4), {}),
        ("scroll", -5),
        ("mouseDown", {"x": 5, "y": 6, "button": "right"}),
        ("mouseUp", {"x": 5, "y": 6, "button": "right"}),
        ("mouseDown", {"button": "left"}),
        ("moveTo", (7, 8), {}),
        ("mouseUp", {"button": "left"}),
        ("hotkey", ("ctrl", "s")),
        ("keyDown", "shift"),
        ("keyUp", "shift"),
    ]


@pytest.mark.asyncio
async def test_keyboard_device_routes_text_modes_to_their_backends():
    calls = []

    class Backend:
        def write(self, text, interval):
            calls.append(("keys", text, interval))

    keyboard = PyAutoGuiKeyboardDevice(
        Backend(),
        unicode_writer=lambda text: calls.append(("unicode", text)),
        clipboard_paster=lambda text: calls.append(("clipboard", text)),
    )

    await keyboard.write("ab", 0.0, "keys")
    await keyboard.write("中文", 0.0, "unicode")
    await keyboard.write("paste", 0.0, "clipboard")

    assert calls == [
        ("keys", "a", 0.0),
        ("keys", "b", 0.0),
        ("unicode", "中"),
        ("unicode", "文"),
        ("clipboard", "paste"),
    ]


@pytest.mark.asyncio
async def test_segmented_mouse_move_stops_after_task_cancellation():
    first_move = asyncio.Event()

    class Backend:
        def __init__(self):
            self.calls = []

        def position(self):
            return (0, 0)

        def moveTo(self, x, y):
            self.calls.append((x, y))
            first_move.set()

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)
    task = asyncio.create_task(mouse.move(position=(600, 300), duration=5.0))
    await first_move.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    calls_after_cancel = len(backend.calls)
    await asyncio.sleep(0.05)

    assert len(backend.calls) == calls_after_cancel
    assert backend.calls[-1] != (600, 300)


@pytest.mark.asyncio
async def test_segmented_mouse_move_disables_backend_pause_for_each_segment():
    class Backend:
        def __init__(self):
            self.pause_arguments = []

        def position(self):
            return (0, 0)

        def moveTo(self, x, y, *, _pause=True):
            self.pause_arguments.append(_pause)

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)

    await mouse.move(position=(10, 10), duration=0.02)

    assert backend.pause_arguments
    assert set(backend.pause_arguments) == {False}


@pytest.mark.asyncio
async def test_segmented_mouse_move_uses_absolute_timing_without_accumulating_call_cost():
    now = 0.0
    delays = []

    async def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += seconds

    class Backend:
        def position(self):
            return (0, 0)

        def moveTo(self, x, y):
            nonlocal now
            now += 0.01

    mouse = PyAutoGuiMouseDevice(Backend(), sleep=sleep, clock=lambda: now)

    await mouse.move(position=(10, 10), duration=0.06)

    assert delays == pytest.approx([0.015, 0.005, 0.005, 0.005])
    assert now == pytest.approx(0.07)


@pytest.mark.asyncio
async def test_bound_mouse_timing_freezes_segments_while_paused():
    token = CancellationToken()
    calls = []

    class Backend:
        def position(self):
            return (0, 0)

        def moveTo(self, x, y, *, _pause=True):
            calls.append((x, y))

    device = PyAutoGuiMouseDevice(Backend())
    device.bind_timing(token.sleep, token.active_time)
    task = asyncio.create_task(device.move(position=(60, 0), duration=0.1))
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert calls
    token.pause()
    count = len(calls)
    await asyncio.sleep(0.03)
    assert len(calls) == count
    token.resume()
    await asyncio.wait_for(task, timeout=0.3)
    assert calls[-1] == (60, 0)


@pytest.mark.asyncio
async def test_segmented_drag_releases_button_after_cancellation():
    first_move = asyncio.Event()

    class Backend:
        def __init__(self):
            self.calls = []

        def position(self):
            return (0, 0)

        def mouseDown(self, **kwargs):
            self.calls.append(("down", kwargs))

        def mouseUp(self, **kwargs):
            self.calls.append(("up", kwargs))

        def moveTo(self, x, y):
            self.calls.append(("move", x, y))
            first_move.set()

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)
    task = asyncio.create_task(mouse.drag(position=(600, 300), button="left", duration=5.0))
    await first_move.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert backend.calls[0] == ("down", {"button": "left"})
    assert backend.calls[-1] == ("up", {"button": "left"})


@pytest.mark.asyncio
async def test_segmented_key_writes_stop_after_task_cancellation():
    first_character = asyncio.Event()

    class Backend:
        def __init__(self):
            self.calls = []

        def write(self, text, interval):
            self.calls.append((text, interval))
            first_character.set()

    backend = Backend()
    keyboard = PyAutoGuiKeyboardDevice(backend)
    task = asyncio.create_task(keyboard.write("abcdef", 5.0, "keys"))
    await first_character.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    calls_after_cancel = len(backend.calls)
    await asyncio.sleep(0.05)

    assert backend.calls == [("a", 0.0)]
    assert len(backend.calls) == calls_after_cancel


@pytest.mark.asyncio
async def test_bound_keyboard_timing_freezes_repeated_keys_while_paused():
    token = CancellationToken()
    calls = []

    class Backend:
        def press(self, key, presses, interval):
            calls.append((key, presses, interval))

    device = PyAutoGuiKeyboardDevice(Backend())
    device.bind_timing(token.sleep)
    task = asyncio.create_task(device.press("a", 3, 0.05))
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert len(calls) == 1
    token.pause()
    await asyncio.sleep(0.03)
    assert len(calls) == 1
    token.resume()
    await asyncio.wait_for(task, timeout=0.3)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_clipboard_text_mode_restores_previous_formats(monkeypatch):
    class Clipboard:
        CF_UNICODETEXT = 13

        def __init__(self):
            self.data = {13: "before", 8: b"dib"}

        def OpenClipboard(self):
            pass

        def CloseClipboard(self):
            pass

        def EmptyClipboard(self):
            self.data.clear()

        def SetClipboardData(self, format_id, data):
            self.data[format_id] = data

        def GetClipboardData(self, format_id):
            return self.data[format_id]

        def EnumClipboardFormats(self, previous):
            formats = sorted(self.data)
            if previous == 0:
                return formats[0] if formats else 0
            remaining = [format_id for format_id in formats if format_id > previous]
            return remaining[0] if remaining else 0

    clipboard = Clipboard()

    class Backend:
        def hotkey(self, *keys):
            assert keys == ("ctrl", "v")
            assert clipboard.data == {13: "during"}

    from flow_runner.infrastructure.input import keyboard as keyboard_module

    original_import = keyboard_module.importlib.import_module
    monkeypatch.setattr(
        keyboard_module.importlib,
        "import_module",
        lambda name: clipboard if name == "win32clipboard" else original_import(name),
    )

    await PyAutoGuiKeyboardDevice(Backend()).write("during", 0.0, "clipboard")

    assert clipboard.data == {13: "before", 8: b"dib"}


@pytest.mark.asyncio
async def test_pyautogui_devices_release_tracked_held_inputs():
    class Backend:
        def __init__(self):
            self.calls = []

        def mouseDown(self, **kwargs):
            self.calls.append(("mouseDown", kwargs))

        def mouseUp(self, **kwargs):
            self.calls.append(("mouseUp", kwargs))

        def keyDown(self, key):
            self.calls.append(("keyDown", key))

        def keyUp(self, key):
            self.calls.append(("keyUp", key))

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)
    keyboard = PyAutoGuiKeyboardDevice(backend)
    await mouse.button_down(position=(5, 6), button="left")
    await keyboard.key_down("shift")

    mouse.release_all()
    keyboard.release_all()

    assert backend.calls == [
        ("mouseDown", {"x": 5, "y": 6, "button": "left"}),
        ("keyDown", "shift"),
        ("mouseUp", {"button": "left"}),
        ("keyUp", "shift"),
    ]
