from PySide6.QtWidgets import QVBoxLayout, QWidget

from flow_runner.domain.routing import RouteRule


class RouteEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._routes: list[RouteRule] = []
        QVBoxLayout(self)

    def set_routes(self, routes: list[RouteRule]) -> None:
        self._routes = list(routes)

    def routes(self) -> list[RouteRule]:
        return list(self._routes)
