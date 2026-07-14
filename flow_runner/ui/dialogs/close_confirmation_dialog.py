from enum import StrEnum

from PySide6.QtWidgets import QAbstractButton, QMessageBox, QWidget


class CloseDecision(StrEnum):
    CANCEL = "cancel"
    CLOSE = "close"
    SAVE_AND_CLOSE = "save_and_close"
    DISCARD_AND_CLOSE = "discard_and_close"
    STOP_AND_CLOSE = "stop_and_close"
    SAVE_STOP_AND_CLOSE = "save_stop_and_close"
    DISCARD_STOP_AND_CLOSE = "discard_stop_and_close"


class CloseConfirmationDialog(QMessageBox):
    def __init__(
        self,
        *,
        modified: bool,
        running: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.decision = CloseDecision.CANCEL
        self._button_decisions: dict[QAbstractButton, CloseDecision] = {}
        self.setIcon(QMessageBox.Icon.Warning)
        self.setWindowTitle("确认关闭")
        self.setText(_message(modified=modified, running=running))

        if modified and running:
            self._add_decision_button(
                "保存、停止并关闭",
                CloseDecision.SAVE_STOP_AND_CLOSE,
                QMessageBox.ButtonRole.AcceptRole,
            )
            self._add_decision_button(
                "不保存、停止并关闭",
                CloseDecision.DISCARD_STOP_AND_CLOSE,
                QMessageBox.ButtonRole.DestructiveRole,
            )
        elif modified:
            self._add_decision_button(
                "保存并关闭",
                CloseDecision.SAVE_AND_CLOSE,
                QMessageBox.ButtonRole.AcceptRole,
            )
            self._add_decision_button(
                "不保存并关闭",
                CloseDecision.DISCARD_AND_CLOSE,
                QMessageBox.ButtonRole.DestructiveRole,
            )
        elif running:
            self._add_decision_button(
                "停止任务并关闭",
                CloseDecision.STOP_AND_CLOSE,
                QMessageBox.ButtonRole.DestructiveRole,
            )
        else:
            self._add_decision_button(
                "关闭",
                CloseDecision.CLOSE,
                QMessageBox.ButtonRole.AcceptRole,
            )

        cancel_button = self._add_decision_button(
            "取消",
            CloseDecision.CANCEL,
            QMessageBox.ButtonRole.RejectRole,
        )
        self.setEscapeButton(cancel_button)
        self.buttonClicked.connect(self._button_clicked)

    def _add_decision_button(
        self,
        text: str,
        decision: CloseDecision,
        role: QMessageBox.ButtonRole,
    ) -> QAbstractButton:
        button = self.addButton(text, role)
        self._button_decisions[button] = decision
        return button

    def _button_clicked(self, button: QAbstractButton) -> None:
        self.decision = self._button_decisions.get(button, CloseDecision.CANCEL)


def _message(*, modified: bool, running: bool) -> str:
    if modified and running:
        return "项目包含未保存的更改，并且任务仍在运行。"
    if modified:
        return "项目包含未保存的更改。"
    if running:
        return "任务仍在运行。"
    return "确定关闭窗口吗？"
