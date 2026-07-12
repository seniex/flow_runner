import pytest

from flow_runner.capabilities.actions.keyboard import KeyboardAction, KeyboardActionConfig
from flow_runner.capabilities.actions.mouse import MouseAction, MouseActionConfig
from flow_runner.capabilities.actions.process import LaunchProcessAction, LaunchProcessConfig
from flow_runner.capabilities.actions.script import PlaybackScriptAction, PlaybackScriptConfig
from flow_runner.capabilities.actions.variables import SetVariableAction, SetVariableConfig
from flow_runner.capabilities.actions.wait import WaitAction, WaitActionConfig
from flow_runner.domain.enums import StepOutcome
from flow_runner.engine.context import StepContext
from flow_runner.infrastructure.input.keyboard import PyAutoGuiKeyboardDevice
from flow_runner.infrastructure.input.mouse import PyAutoGuiMouseDevice
from flow_runner.infrastructure.input.recording import (
    RecordedEvent,
    RecordingPlayer,
    RecordingRecorder,
    RecordingStore,
)
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

    async def write(self, text, interval):
        self.calls.append(("write", text, interval))

    async def key_down(self, key):
        self.calls.append(("key_down", key))

    async def key_up(self, key):
        self.calls.append(("key_up", key))


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

    async def launch(path, arguments, run_as_admin):
        launches.append((path, arguments, run_as_admin))

    async def playback(path, speed, max_gap):
        playbacks.append((path, speed, max_gap))

    process_result = await LaunchProcessAction(launch).execute(
        LaunchProcessConfig(path=app, arguments=["--safe"], run_as_admin=True),
        StepContext(),
    )
    script_result = await PlaybackScriptAction(playback).execute(
        PlaybackScriptConfig(path=script, speed=2.0, max_gap=1.5), StepContext()
    )

    assert process_result.outcome is StepOutcome.SUCCESS
    assert script_result.outcome is StepOutcome.SUCCESS
    assert launches == [(app.resolve(), ("--safe",), True)]
    assert playbacks == [(script.resolve(), 2.0, 1.5)]


@pytest.mark.asyncio
async def test_windows_process_launcher_selects_normal_or_admin_backend(tmp_path):
    calls = []

    def popen(command):
        calls.append(("popen", command))

    def shell_execute(path, arguments):
        calls.append(("admin", path, arguments))

    launcher = WindowsProcessLauncher(popen=popen, shell_execute=shell_execute)
    path = (tmp_path / "game.exe").resolve()
    await launcher(path, ("--safe",), False)
    await launcher(path, ("--admin",), True)

    assert calls == [
        ("popen", [str(path), "--safe"]),
        ("admin", path, "--admin"),
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

    async def sleep(seconds):
        delays.append(seconds)

    class Backend:
        def moveTo(self, x, y):
            calls.append(("move", x, y))

        def click(self, **kwargs):
            calls.append(("click", kwargs))

    await RecordingPlayer(sleep=sleep, backend=Backend())(path, speed=2.0, max_gap=1.0)

    assert delays == [0.0, 1.0]
    assert calls == [
        ("move", 4, 5),
        ("click", {"x": 4, "y": 5, "button": "left"}),
    ]


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


@pytest.mark.asyncio
async def test_pyautogui_devices_translate_actions_to_backend_calls():
    class Backend:
        def __init__(self):
            self.calls = []

        def click(self, **kwargs):
            self.calls.append(("click", kwargs))

        def moveTo(self, *args, **kwargs):
            self.calls.append(("moveTo", args, kwargs))

        def scroll(self, units):
            self.calls.append(("scroll", units))

        def mouseDown(self, **kwargs):
            self.calls.append(("mouseDown", kwargs))

        def mouseUp(self, **kwargs):
            self.calls.append(("mouseUp", kwargs))

        def dragTo(self, *args, **kwargs):
            self.calls.append(("dragTo", args, kwargs))

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
    await mouse.drag(position=(7, 8), button="left", duration=0.25)
    await keyboard.hotkey(("ctrl", "s"))
    await keyboard.key_down("shift")
    await keyboard.key_up("shift")

    assert backend.calls == [
        ("click", {"x": 1, "y": 2, "button": "left", "clicks": 2, "interval": 0.1}),
        ("moveTo", (3, 4), {}),
        ("scroll", -5),
        ("mouseDown", {"x": 5, "y": 6, "button": "right"}),
        ("mouseUp", {"x": 5, "y": 6, "button": "right"}),
        ("dragTo", (7, 8), {"duration": 0.25, "button": "left"}),
        ("hotkey", ("ctrl", "s")),
        ("keyDown", "shift"),
        ("keyUp", "shift"),
    ]


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
