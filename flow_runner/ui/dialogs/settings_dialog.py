from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit

from flow_runner.ui.hotkeys import HotkeyConfig


class SettingsDialog(QDialog):
    def __init__(self, hotkeys: HotkeyConfig) -> None:
        super().__init__()
        self.entries: dict[str, QLineEdit] = {}
        layout = QFormLayout(self)
        for action, value in hotkeys.model_dump().items():
            entry = QLineEdit(value)
            self.entries[action] = entry
            layout.addRow(action, entry)

    def hotkey_config(self) -> HotkeyConfig:
        return HotkeyConfig(**{key: entry.text() for key, entry in self.entries.items()})
