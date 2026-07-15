from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from flow_runner.ui.hotkeys import HotkeyConfig
from flow_runner.ui.widgets import FocusWheelComboBox, FocusWheelDoubleSpinBox


class SettingsDialog(QDialog):
    def __init__(self, hotkeys: HotkeyConfig, settings: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.settings = dict(settings or {})
        self.entries: dict[str, QLineEdit] = {}
        layout = QFormLayout(self)
        self.ocr_engine_combo = FocusWheelComboBox()
        self.ocr_engine_combo.addItem("Tesseract", "tesseract")
        self.ocr_engine_combo.addItem("PaddleOCR-json", "paddle")
        engine = str(self.settings.get("ocr_engine", "tesseract")).casefold()
        self.ocr_engine_combo.setCurrentIndex(max(0, self.ocr_engine_combo.findData(engine)))
        self.paddle_path_edit = QLineEdit(str(self.settings.get("paddle_exe_path", "")))
        layout.addRow("OCR 引擎", self.ocr_engine_combo)
        layout.addRow("PaddleOCR-json.exe", self.paddle_path_edit)
        self.window_capture_mode_combo = FocusWheelComboBox()
        self.window_capture_mode_combo.addItem("前台可见像素（BitBlt）", "foreground")
        self.window_capture_mode_combo.addItem(
            "后台窗口内容（Windows Graphics Capture）",
            "background",
        )
        capture_mode = str(self.settings.get("window_capture_mode", "foreground")).casefold()
        self.window_capture_mode_combo.setCurrentIndex(
            max(0, self.window_capture_mode_combo.findData(capture_mode))
        )
        self.window_capture_fallback_check = QCheckBox("后台失败时回退到前台模式")
        self.window_capture_fallback_check.setChecked(
            bool(self.settings.get("window_capture_fallback", True))
        )
        self.window_capture_timeout_spin = FocusWheelDoubleSpinBox()
        self.window_capture_timeout_spin.setRange(0.1, 60.0)
        self.window_capture_timeout_spin.setDecimals(2)
        self.window_capture_timeout_spin.setValue(
            float(self.settings.get("window_capture_timeout_seconds", 3.0))
        )
        layout.addRow("窗口截图模式", self.window_capture_mode_combo)
        layout.addRow("截图回退", self.window_capture_fallback_check)
        layout.addRow("后台截图超时（秒）", self.window_capture_timeout_spin)
        self.debug_logging_check = QCheckBox("启用调试日志（下次启动生效）")
        self.debug_logging_check.setChecked(bool(self.settings.get("debug_logging", False)))
        layout.addRow("运行日志", self.debug_logging_check)
        for action, value in hotkeys.model_dump().items():
            entry = QLineEdit(value)
            self.entries[action] = entry
            layout.addRow(
                {
                    "start": "启动热键",
                    "stop": "停止热键",
                    "pause": "暂停/继续热键",
                    "record": "录制热键",
                }.get(action, action),
                entry,
            )
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
                "window_capture_mode": str(self.window_capture_mode_combo.currentData()),
                "window_capture_fallback": self.window_capture_fallback_check.isChecked(),
                "window_capture_timeout_seconds": self.window_capture_timeout_spin.value(),
                "debug_logging": self.debug_logging_check.isChecked(),
                "hotkeys": self.hotkey_config().model_dump(),
            }
        )
        return settings
