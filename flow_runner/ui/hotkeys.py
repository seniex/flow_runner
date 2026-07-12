from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: str = "F6"
    stop: str = "F7"
    pause: str = "F8"
    record: str = "F9"

    @field_validator("start", "stop", "pause", "record", mode="before")
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
