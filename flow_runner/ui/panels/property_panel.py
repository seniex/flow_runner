from uuid import UUID

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from flow_runner.domain.project import AutomationStep


class PropertyPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("propertyPanel")
        self.step_id: UUID | None = None
        self.title = QLabel("")
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addStretch()

    def set_step(self, step: AutomationStep) -> None:
        self.step_id = step.id
        self.title.setText(step.name)
