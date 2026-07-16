from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: str = "F6"
    stop: str = "F7"
    pause: str = "F8"
    record: str = "F9"
    record_pause: str = ""

    @field_validator("start", "stop", "pause", "record", "record_pause", mode="before")
    @classmethod
    def normalize(cls, value: object) -> str:
        return str(value or "").strip().upper()

    @model_validator(mode="after")
    def validate_unique(self) -> HotkeyConfig:
        enabled = [value for value in self.model_dump().values() if value]
        if len(enabled) != len(set(enabled)):
            raise ValueError("duplicate hotkey bindings are not allowed")
        return self

    def enabled_bindings(self) -> dict[str, str]:
        return {key: action for action, key in self.model_dump().items() if key}


class Listener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


ListenerFactory = Callable[[Callable[[object], None]], Listener]


class HotkeyService:
    def __init__(
        self,
        config: HotkeyConfig,
        *,
        actions: dict[str, Callable[[], None]],
        listener_factory: ListenerFactory | None = None,
    ) -> None:
        self.bindings = config.enabled_bindings()
        self.actions = actions
        self.listener_factory = listener_factory or _pynput_listener
        self.listener: Listener | None = None
        self._active = False

    @property
    def control_keys(self) -> frozenset[str]:
        return frozenset(self.bindings)

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._start_listener()

    def stop(self) -> None:
        self._active = False
        self._stop_listener()

    def reconfigure(self, config: HotkeyConfig) -> None:
        replacement = config.enabled_bindings()
        previous = dict(self.bindings)
        if not self._active:
            self.bindings = replacement
            return
        self._stop_listener()
        self.bindings = replacement
        try:
            self._start_listener()
        except Exception:
            self.bindings = previous
            try:
                self._start_listener()
            except Exception:
                pass
            raise

    def _start_listener(self) -> None:
        if self.listener is not None or not self.bindings:
            return
        listener = self.listener_factory(self._on_press)
        listener.start()
        self.listener = listener

    def _stop_listener(self) -> None:
        listener = self.listener
        self.listener = None
        if listener is not None:
            listener.stop()

    def _on_press(self, key: object) -> None:
        action_name = self.bindings.get(_key_name(key))
        action = self.actions.get(action_name or "")
        if action is not None:
            action()


def _key_name(key: object) -> str:
    if isinstance(key, str):
        return key.strip().upper()
    name = getattr(key, "name", None)
    if name:
        return str(name).upper()
    char = getattr(key, "char", None)
    return str(char or "").upper()


def _pynput_listener(on_press: Callable[[object], None]) -> Listener:
    keyboard = importlib.import_module("pynput.keyboard")
    return cast(Listener, keyboard.Listener(on_press=on_press))
