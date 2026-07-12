import json

from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QTextEdit

from flow_runner.infrastructure.logging.events import RuntimeEvent


class DiagnosticsDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.state_value = QLabel("")
        self.frame_value = QLabel("")
        self.details_value = QTextEdit()
        self.details_value.setReadOnly(True)
        layout = QFormLayout(self)
        layout.addRow("状态", self.state_value)
        layout.addRow("帧", self.frame_value)
        layout.addRow("详情", self.details_value)

    def update_event(self, event: RuntimeEvent) -> None:
        self.state_value.setText(event.state.value)
        self.frame_value.setText(event.frame_id or "")
        self.details_value.setPlainText(json.dumps(event.details, ensure_ascii=False, indent=2))
