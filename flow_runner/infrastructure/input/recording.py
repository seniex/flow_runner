from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class RecordedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float = Field(ge=0)
    kind: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class RecordingStore:
    _adapter = TypeAdapter(list[RecordedEvent])

    @classmethod
    def save(cls, path: Path, events: list[RecordedEvent]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cls._adapter.dump_json(events, indent=2).decode(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> list[RecordedEvent]:
        return cls._adapter.validate_json(path.read_text(encoding="utf-8"))
