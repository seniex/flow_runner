from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _button(text: str, tone: str = "quiet") -> QPushButton:
    button = QPushButton(text)
    button.setProperty("tone", tone)
    return button


def _combo(items: list[str], width: int = 150) -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    combo.setFixedWidth(width)
    return combo


def _field_row(*widgets: QWidget) -> QFrame:
    row = QFrame()
    row.setProperty("fieldRow", True)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(10, 5, 10, 5)
    layout.setSpacing(7)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return row


def _step_card(index: int, title: str, body: list[QWidget]) -> QFrame:
    card = QFrame()
    card.setProperty("stepCard", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10, 8, 10, 10)
    layout.setSpacing(6)
    header = QHBoxLayout()
    header.addWidget(QLabel("▼"))
    label = QLabel(f"[{index}] {title}")
    label.setProperty("cardTitle", True)
    header.addWidget(label)
    header.addStretch()
    header.addWidget(_button("删除", "danger"))
    header.addWidget(_button("↓"))
    header.addWidget(_button("↑"))
    layout.addLayout(header)
    for widget in body:
        layout.addWidget(widget)
    return card


def build_preview() -> QMainWindow:
    window = QMainWindow()
    window.setWindowTitle("Flow Runner — 深色简单界面预览")
    window.resize(1240, 880)
    root = QWidget()
    root.setObjectName("previewRoot")
    window.setCentralWidget(root)
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    top = QFrame()
    top.setObjectName("topBar")
    top_layout = QHBoxLayout(top)
    top_layout.setContentsMargins(10, 8, 10, 8)
    top_layout.addWidget(_button("▶ 启动", "start"))
    top_layout.addWidget(_button("Ⅱ 暂停", "pause"))
    top_layout.addWidget(_button("■ 停止", "stop"))
    top_layout.addSpacing(12)
    top_layout.addWidget(QLabel("从："))
    top_layout.addWidget(_combo(["1: 不思议挂机", "2: 日常任务"]))
    top_layout.addWidget(QLabel("—"))
    top_layout.addWidget(_combo(["1: 开始游戏", "2: 自动战斗", "3: 退出"], 170))
    top_layout.addWidget(QLabel("开始"))
    top_layout.addSpacing(10)
    state = QLabel("● 未运行")
    state.setObjectName("runtimeState")
    top_layout.addWidget(state)
    top_layout.addStretch()
    top_layout.addWidget(_button("⚙ 设置"))
    root_layout.addWidget(top)

    body = QSplitter(Qt.Orientation.Horizontal)
    sidebar = QFrame()
    sidebar.setObjectName("flowSidebar")
    sidebar.setMinimumWidth(230)
    sidebar.setMaximumWidth(280)
    side_layout = QVBoxLayout(sidebar)
    side_head = QHBoxLayout()
    section = QLabel("流程组")
    section.setObjectName("sectionTitle")
    side_head.addWidget(section)
    side_head.addStretch()
    side_head.addWidget(_button("+ 组", "accent"))
    side_layout.addLayout(side_head)
    flows = QListWidget()
    flows.addItems(
        [
            "[17] 转职2前等待 ×1 → 18",
            "[18] 还原war3 ×1 → 19",
            "[21] 难20逃跑 ×1 → 23",
            "[25] 还原war3 ×1 → 26",
            "[27] A基本挑战2 ×1 → 29",
            "[29] 进出塔罗牌 ×1 → 30",
            "[30] 进入实验室 ×1 → 31",
        ]
    )
    flows.setCurrentRow(5)
    side_layout.addWidget(flows, 3)
    flow_actions = QHBoxLayout()
    for text, tone in (("+ 流程", "accent"), ("删除", "danger"), ("↑", "quiet"), ("↓", "quiet")):
        flow_actions.addWidget(_button(text, tone))
    side_layout.addLayout(flow_actions)
    record_title = QLabel("录制脚本")
    record_title.setObjectName("sectionTitle")
    side_layout.addWidget(record_title)
    side_layout.addWidget(_button("● 开始录制", "stop"))
    records = QListWidget()
    records.addItems(["基本卡片.json", "最小化.json", "退出流程.json", "record_20260715.json"])
    side_layout.addWidget(records, 2)
    body.addWidget(sidebar)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(8, 8, 8, 8)
    content_layout.setSpacing(7)
    workflow_header = QFrame()
    workflow_header.setObjectName("workflowHeader")
    workflow_header_layout = QHBoxLayout(workflow_header)
    title = QLabel("[1-29] 不思议挂机 / 进出塔罗牌")
    title.setObjectName("workflowTitle")
    workflow_header_layout.addWidget(title)
    workflow_header_layout.addSpacing(20)
    workflow_header_layout.addWidget(QLabel("循环次数：1   (0=无限)"))
    workflow_header_layout.addSpacing(20)
    workflow_header_layout.addWidget(QLabel("执行前等待："))
    wait = QDoubleSpinBox()
    wait.setValue(0)
    wait.setSuffix(" 秒")
    workflow_header_layout.addWidget(wait)
    workflow_header_layout.addStretch()
    workflow_header_layout.addWidget(_button("保存流程", "success"))
    content_layout.addWidget(workflow_header)

    add_bar = QFrame()
    add_bar.setObjectName("addStepBar")
    add_layout = QHBoxLayout(add_bar)
    add_layout.addWidget(QLabel("添加步骤："))
    add_layout.addWidget(_combo(["OCR 检测", "图片检测", "键盘命令", "鼠标操作"], 190))
    add_layout.addWidget(_button("+ 添加", "accent"))
    add_layout.addStretch()
    add_layout.addWidget(_button("高级编辑"))
    content_layout.addWidget(add_bar)

    scroller = QScrollArea()
    scroller.setWidgetResizable(True)
    cards = QWidget()
    cards_layout = QVBoxLayout(cards)
    cards_layout.setContentsMargins(0, 0, 0, 0)
    cards_layout.setSpacing(8)
    key = QLineEdit("x")
    key.setFixedWidth(100)
    count = QSpinBox()
    count.setValue(1)
    cards_layout.addWidget(
        _step_card(
            1,
            "键盘命令    进入塔罗牌",
            [
                _field_row(
                    QLabel("按键顺序："),
                    _button("+ 添加按键", "accent"),
                ),
                _field_row(
                    QLabel("按键"), key, QLabel("次数"), count, QLabel("间隔"), QLineEdit("0.05 秒")
                ),
            ],
        )
    )
    keyword = QLineEdit("都不要")
    keyword.setFixedWidth(180)
    cards_layout.addWidget(
        _step_card(
            2,
            "轮询 OCR",
            [
                _field_row(
                    QLabel("检测区域："),
                    _named_label("(1700,492)-(2135,961)", "regionValue"),
                    _button("框选区域", "accent"),
                ),
                _field_row(QLabel("关键词："), keyword, QLabel("|=OR  ,=AND")),
                _field_row(QLabel("OCR 引擎：PaddleOCR"), QLabel("放大 2x")),
                _field_row(
                    QLabel("间隔(秒)"), QLineEdit("1.0"), QLabel("最多次数"), QLineEdit("10")
                ),
                _field_row(QCheckBox("检测到后执行序列点击"), _button("+ 添加点击", "accent")),
            ],
        )
    )
    cards_layout.addWidget(
        _step_card(
            3,
            "图片检测并点击",
            [
                _field_row(
                    QLabel("检测区域："),
                    _named_label("(800,400)-(1080,560)", "regionValue"),
                    _button("框选区域", "accent"),
                ),
                _field_row(
                    QLabel("模板图片：templates/button.png"),
                    _button("框选并截图", "accent"),
                    _button("选择文件"),
                ),
            ],
        )
    )
    cards_layout.addStretch()
    scroller.setWidget(cards)

    vertical = QSplitter(Qt.Orientation.Vertical)
    vertical.addWidget(scroller)
    log_container = QWidget()
    log_layout = QVBoxLayout(log_container)
    log_layout.setContentsMargins(0, 0, 0, 0)
    log_header = QFrame()
    log_header.setObjectName("logHeader")
    log_header_layout = QHBoxLayout(log_header)
    log_header_layout.addWidget(QLabel("运行日志"))
    log_header_layout.addStretch()
    log_header_layout.addWidget(_button("清空"))
    runtime_log = QTextEdit()
    runtime_log.setObjectName("runtimeLog")
    runtime_log.setReadOnly(True)
    runtime_log.setPlainText("[01:02:03] 已加载项目\n[01:02:04] 当前入口：不思议挂机 / 开始游戏")
    log_layout.addWidget(log_header)
    log_layout.addWidget(runtime_log)
    vertical.addWidget(log_container)
    vertical.setSizes([570, 180])
    content_layout.addWidget(vertical, 1)
    body.addWidget(content)
    body.setSizes([240, 1000])
    root_layout.addWidget(body, 1)
    return window


def _named_label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    root = Path(__file__).resolve().parents[1]
    qss = root / "flow_runner" / "resources" / "styles" / "dark_preview.qss"
    app.setStyleSheet(qss.read_text(encoding="utf-8"))
    window = build_preview()
    window.show()
    if len(sys.argv) > 1:
        app.processEvents()
        window.grab().save(sys.argv[1])
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
