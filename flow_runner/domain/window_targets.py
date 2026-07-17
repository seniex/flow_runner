from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WindowTarget(BaseModel):
    """A mutually exclusive process-name or legacy title window selector."""

    model_config = ConfigDict(frozen=True)

    process_name: str | None = None
    fallback_process_names: list[str] = Field(default_factory=list)
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for field in ("process_name", "title"):
            raw = normalized.get(field)
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise ValueError(f"{field} must be text")
            text = raw.strip()
            if not text:
                raise ValueError(f"{field} cannot be empty")
            normalized[field] = text

        raw_fallbacks = normalized.get("fallback_process_names", [])
        if raw_fallbacks is None:
            raw_fallbacks = []
        if isinstance(raw_fallbacks, str) or not isinstance(raw_fallbacks, Iterable):
            raise ValueError("fallback_process_names must be a list of names")
        fallbacks: list[str] = []
        seen: set[str] = set()
        for raw in raw_fallbacks:
            if not isinstance(raw, str):
                raise ValueError("fallback process names must be text")
            name = raw.strip()
            if not name:
                raise ValueError("fallback process names cannot be empty")
            normalized_name = name.casefold()
            if normalized_name not in seen:
                seen.add(normalized_name)
                fallbacks.append(name)
        normalized["fallback_process_names"] = fallbacks
        return normalized

    @model_validator(mode="after")
    def validate_selector(self) -> WindowTarget:
        has_process = self.process_name is not None
        has_fallbacks = bool(self.fallback_process_names)
        has_title = self.title is not None
        if has_title and (has_process or has_fallbacks):
            raise ValueError("window target must use process names or title, not both")
        if not has_title and not has_process:
            raise ValueError("window target requires a process name or title")
        if has_process:
            assert self.process_name is not None
            primary = self.process_name.casefold()
            deduplicated = [
                name for name in self.fallback_process_names if name.casefold() != primary
            ]
            object.__setattr__(self, "fallback_process_names", deduplicated)
        return self

    @property
    def process_names(self) -> tuple[str, ...]:
        if self.process_name is None:
            return ()
        return (self.process_name, *self.fallback_process_names)

    @property
    def matching_process_names(self) -> tuple[str, ...]:
        return tuple(name.casefold() for name in self.process_names)

    @property
    def resource_key(self) -> str:
        if self.process_names:
            return "window:process:" + "|".join(self.matching_process_names)
        assert self.title is not None
        return f"window:{self.title}"
