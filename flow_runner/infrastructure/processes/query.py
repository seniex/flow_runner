from typing import Protocol


class ProcessQuery(Protocol):
    def exists(self, name: str) -> bool: ...
