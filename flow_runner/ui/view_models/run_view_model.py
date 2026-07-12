from PySide6.QtCore import QObject, Signal

from flow_runner.domain.enums import RunnerState
from flow_runner.infrastructure.logging.events import RuntimeEvent


class RunViewModel(QObject):
    stateChanged = Signal(object)
    eventReceived = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.state = RunnerState.IDLE
        self.latest_event: RuntimeEvent | None = None

    def consume(self, event: RuntimeEvent) -> None:
        previous = self.state
        self.latest_event = event
        self.state = event.state
        self.eventReceived.emit(event)
        if self.state is not previous:
            self.stateChanged.emit(self.state)
