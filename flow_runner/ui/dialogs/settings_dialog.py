from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from flow_runner.ui.hotkeys import HotkeyConfig


class SettingsDialog(QDialog):
    def __init__(self, hotkeys: HotkeyConfig, settings: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.settings = dict(settings or {})
        self.entries: dict[str, QLineEdit] = {}
        layout = QFormLayout(self)
        self.ocr_engine_combo = QComboBox()
        self.ocr_engine_combo.addItem("Tesseract", "tesseract")
        self.ocr_engine_combo.addItem("PaddleOCR-json", "paddle")
        engine = str(self.settings.get("ocr_engine", "tesseract")).casefold()
        self.ocr_engine_combo.setCurrentIndex(max(0, self.ocr_engine_combo.findData(engine)))
        self.paddle_path_edit = QLineEdit(str(self.settings.get("paddle_exe_path", "")))
        layout.addRow("OCR 引擎", self.ocr_engine_combo)
        layout.addRow("PaddleOCR-json.exe", self.paddle_path_edit)
        for action, value in hotkeys.model_dump().items():
            entry = QLineEdit(value)
            self.entries[action] = entry
            layout.addRow(action, entry)
        self.error_label = QLabel("")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow("", self.error_label)
        layout.addRow(self.buttons)

    def accept(self) -> None:
        try:
            self.hotkey_config()
            if (
                self.ocr_engine_combo.currentData() == "paddle"
                and not self.paddle_path_edit.text().strip()
            ):
                raise ValueError("PaddleOCR-json 模式需要配置 exe 路径")
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        super().accept()

    def hotkey_config(self) -> HotkeyConfig:
        return HotkeyConfig(**{key: entry.text() for key, entry in self.entries.items()})

    def project_settings(self) -> dict[str, Any]:
        settings = dict(self.settings)
        settings.update(
            {
                "ocr_engine": str(self.ocr_engine_combo.currentData()),
                "paddle_exe_path": self.paddle_path_edit.text().strip(),
                "hotkeys": self.hotkey_config().model_dump(),
            }
        )
        return settings
