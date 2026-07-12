from typing import Any, Protocol


class WindowQuery(Protocol):
    def query(self, title: str) -> dict[str, Any]: ...
