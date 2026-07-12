from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from flow_runner.domain.enums import ConditionMode


class PolicyEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("检查一次", ConditionMode.ONCE)
        self.mode_combo.addItem("等待满足", ConditionMode.UNTIL)
        layout = QFormLayout(self)
        layout.addRow("检测模式", self.mode_combo)

    def set_mode(self, mode: ConditionMode) -> None:
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(index)

    def mode(self) -> ConditionMode:
        return ConditionMode(self.mode_combo.currentData())
