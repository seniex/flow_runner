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
from flow_runner.infrastructure.input.recording import RecordedEvent, RecordingStore


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


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    async def press(self, key, count, interval):
        self.calls.append(("press", key, count, interval))

    async def hotkey(self, keys):
        self.calls.append(("hotkey", keys))

    async def write(self, text, interval):
        self.calls.append(("write", text, interval))


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


def test_recording_store_round_trips_typed_events(tmp_path):
    path = tmp_path / "recording.json"
    events = [RecordedEvent(timestamp=0.25, kind="mouse_click", data={"x": 1, "y": 2})]

    RecordingStore.save(path, events)

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

        def press(self, key, presses, interval):
            self.calls.append(("press", key, presses, interval))

        def hotkey(self, *keys):
            self.calls.append(("hotkey", keys))

        def write(self, text, interval):
            self.calls.append(("write", text, interval))

    backend = Backend()
    mouse = PyAutoGuiMouseDevice(backend)
    keyboard = PyAutoGuiKeyboardDevice(backend)

    await mouse.click(position=(1, 2), button="left", clicks=2, interval=0.1)
    await mouse.scroll(position=(3, 4), units=-5)
    await keyboard.hotkey(("ctrl", "s"))

    assert backend.calls == [
        ("click", {"x": 1, "y": 2, "button": "left", "clicks": 2, "interval": 0.1}),
        ("moveTo", (3, 4), {}),
        ("scroll", -5),
        ("hotkey", ("ctrl", "s")),
    ]
