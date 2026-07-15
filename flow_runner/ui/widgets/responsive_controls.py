from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from flow_runner.ui.layouts import CompactFlowLayout


class ResponsiveControlGroup(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setProperty("controlGroup", True)
        self.title = QLabel(title)
        self.title.setObjectName("responsiveControlGroupTitle")
        self.body = QWidget()
        self.body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.flow = CompactFlowLayout(self.body, spacing=6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.body)

    def add_action(self, action: QAction) -> QToolButton:
        button = QToolButton(self.body)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        self.flow.addWidget(button)
        return button

    def add_field(self, label: str, editor: QWidget, name: str) -> QWidget:
        return self.flow.addField(label, editor, name)


class ResponsiveControlArea(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setObjectName("responsiveControlArea")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)

    def add_group(self, title: str) -> ResponsiveControlGroup:
        group = ResponsiveControlGroup(title, self)
        self._layout.addWidget(group)
        return group


class ColumnContainer(QWidget):
    def __init__(
        self,
        content: QWidget,
        controls: ResponsiveControlArea,
        *,
        object_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.content = content
        self.controls = controls
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(content, 1)
        layout.addWidget(controls)
