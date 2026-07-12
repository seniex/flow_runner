import json

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QTextEdit, QWidget

from flow_runner.infrastructure.logging.events import RuntimeEvent


class DiagnosticsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diagnosticsDialog")
        self.kind_value = QLabel("")
        self.state_value = QLabel("")
        self.task_value = QLabel("")
        self.workflow_value = QLabel("")
        self.step_value = QLabel("")
        self.outcome_value = QLabel("")
        self.frame_value = QLabel("")
        self.capture_value = QLabel("")
        self.error_value = QLabel("")
        self.details_value = QTextEdit()
        self.details_value.setReadOnly(True)
        layout = QFormLayout(self)
        layout.addRow("事件", self.kind_value)
        layout.addRow("状态", self.state_value)
        layout.addRow("任务", self.task_value)
        layout.addRow("流程", self.workflow_value)
        layout.addRow("步骤", self.step_value)
        layout.addRow("结果", self.outcome_value)
        layout.addRow("帧", self.frame_value)
        layout.addRow("截图", self.capture_value)
        layout.addRow("错误 ID", self.error_value)
        layout.addRow("详情", self.details_value)

    def update_event(self, event: RuntimeEvent) -> None:
        self.kind_value.setText(event.kind)
        self.state_value.setText(event.state.value)
        self.task_value.setText(str(event.task_id))
        self.workflow_value.setText(str(event.workflow_id or ""))
        self.step_value.setText(str(event.step_id or ""))
        self.outcome_value.setText(event.outcome.value if event.outcome is not None else "")
        self.frame_value.setText(event.frame_id or "")
        self._update_capture(event.diagnostic_capture_path)
        self.error_value.setText(str(event.error_id or ""))
        self.details_value.setPlainText(json.dumps(event.details, ensure_ascii=False, indent=2))

    def _update_capture(self, path: str | None) -> None:
        self.capture_value.clear()
        if path is None:
            self.capture_value.setVisible(False)
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.capture_value.setText(f"无法加载截图：{path}")
        else:
            self.capture_value.setPixmap(pixmap)
        self.capture_value.setVisible(True)
