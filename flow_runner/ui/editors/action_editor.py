from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec


class ActionEditor(QWidget):
    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__()
        self.capability_combo = QComboBox()
        for metadata in registry.action_metadata():
            self.capability_combo.addItem(metadata.name, metadata.name)
        self._actions: list[ActionSpec] = []
        layout = QVBoxLayout(self)
        layout.addWidget(self.capability_combo)

    def set_actions(self, actions: list[ActionSpec]) -> None:
        self._actions = list(actions)

    def action_specs(self) -> list[ActionSpec]:
        return list(self._actions)
