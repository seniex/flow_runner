from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLayoutItem, QWidget


class CompactFlowLayout(QLayout):
    """Pack labelled editors left-to-right and wrap only when space runs out."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        spacing: int = 8,
        wrap: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []
        self._labels: dict[QWidget, QLabel] = {}
        self._containers: dict[QWidget, QWidget] = {}
        self.wrap = wrap

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt API
        self._items.append(item)

    def addField(self, label_text: str, editor: QWidget, name: str = "") -> QWidget:  # noqa: N802
        container = QWidget()
        container.setProperty("compactField", True)
        if name:
            container.setObjectName(f"compactField_{name}")
        label = QLabel(label_text)
        label.setObjectName("compactFieldLabel")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(label)
        row.addWidget(editor)
        self._labels[editor] = label
        self._containers[editor] = container
        self.addWidget(container)
        return container

    def labelForField(self, editor: QWidget) -> QLabel | None:  # noqa: N802 - QFormLayout API
        return self._labels.get(editor)

    def containerForField(self, editor: QWidget) -> QWidget | None:  # noqa: N802
        return self._containers.get(editor)

    def setFieldVisible(self, editor: QWidget, visible: bool) -> None:  # noqa: N802
        editor.setVisible(visible)
        container = self.containerForField(editor)
        if container is not None:
            container.setVisible(visible)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt API
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt API
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt API
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt API
        size = QSize()
        for item in self._items:
            if not _item_hidden(item):
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            if _item_hidden(item):
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if self.wrap and x > effective.x() and next_x - spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


def _item_hidden(item: QLayoutItem) -> bool:
    widget = item.widget()
    return widget is not None and widget.isHidden()
