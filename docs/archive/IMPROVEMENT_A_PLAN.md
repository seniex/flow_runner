# 改进A Implementation Plan

**状态：complete**
**完成日期：2026-07-15**
**追加改进状态（2026-07-15）：布局与框选验收基本通过；三列持久化、卡片、工具栏、窗口操作、分级日志和等待倒计时修正进入最终回归。**
**最新验证：323 passed；Ruff、格式、严格 mypy、compileall、git diff --check 均通过。**
**仍需外部环境处理：多显示器、Tesseract 和全局热键验收继续按
`REAL_ENVIRONMENT_CHECKLIST.md` 的既有 BLOCKED 记录处理。深色主题和紧凑卡片已按根目录
`flowUI.png`、`BGUI.png` 参考通过 QSS/布局系统实现。**

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not spawn subagents unless the user explicitly requests delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal（complete）：** 在不改变现有自动化业务流程语义的前提下，完成编辑安全、可靠撤销与关闭、常用/高级参数简化、步骤/流程/流程组复制，以及并行块编辑。

**Architecture:** 将工作拆成三个可独立验收的批次。批次一只处理编辑安全与生命周期；批次二重组现有引导编辑器但保留完整领域模型和高级 JSON；批次三通过纯领域克隆服务重映射 UUID，并在 ViewModel/UI 层增加复制和并行块编辑。所有行为先写失败测试，再做最小实现。

**Tech Stack:** Python 3.12、PySide6、Pydantic、pytest、pytest-qt、Ruff、mypy。

---

## 0. Goal 模式执行约束

- 工作树固定为：`D:\3eyes\Python\codex\apps\flow_runner\.worktrees\release-completion`
- 分支固定为：`chore/release-completion`
- 当前工作树已有用户认可的未提交修改和多个 `project.*.bak.json`，禁止重置、覆盖或清理。
- `project.json` 是用户正在实测的业务配置。除非某个任务明确要求迁移业务配置，否则实现和自动化测试不得修改它。
- 不自动提交、合并或推送；只有用户明确要求时才执行 Git 提交操作。
- 会移动鼠标、发送键盘、切换窗口、停止真实运行任务的测试，必须提前用中文说明影响并等待用户确认。
- Qt offscreen、纯模型、临时目录和假适配器测试可以直接执行。
- 每完成一个批次，更新本文档勾选状态、运行该批次验证并向用户报告，再继续下一批次。

## 1. 已确认的当前问题

### 撤销

- `ProjectViewModel.mark_saved()` 只更新 `_saved_project`，不清空 `_undo_stack`。
- 保存后第一次撤销可以回到保存状态，但继续撤销会越过保存边界并再次产生脏状态。
- 工具栏撤销直接连接 `view_model.undo`，当前属性面板的 pending 草稿不会被撤销。
- `projectChanged` 刷新选择时可能触发旧表单自动提交，存在把撤销结果重新覆盖的风险。

### 关闭

- `MainWindow.closeEvent()` 只处理未保存提示，没有“任务正在运行”的确认。
- 真实 `Discard` 按钮路径缺少自动化覆盖；注入 `"discard"` 的测试路径能够关闭，因此必须先复现真实对话框行为再修改。
- `RunnerBridge.shutdown()` 不返回停止是否成功，关闭窗口无法可靠决定是否应继续退出。

### 滚轮误修改

- `QComboBox`、`QSpinBox`、`QDoubleSpinBox` 使用 Qt 默认滚轮行为。
- 鼠标只是在属性页滚动时，悬停控件可能改变值。

### UI 密度

- `PropertyPanel` 同时铺开引导编辑器和五块原始 JSON。
- 所有能力参数、完整策略和路由谓词默认展开。
- 当前没有“常用/高级”字段元数据。

### 复制与并行块

- 当前只有“复制动作”，没有复制步骤、流程或流程组。
- 并行块只能新增和删除，不能修改名称或成员流程。
- 当前项目 `parallel_blocks` 为空，但功能和运行时已经实现。

---

# 批次一：编辑安全、撤销与关闭

## Task 1: 建立批次一失败测试基线

**Files:**
- Modify: `tests/ui/test_main_window.py`
- Modify: `tests/ui/test_app_smoke.py`
- Modify: `tests/ui/test_step_editors.py`
- Create: `tests/ui/test_focus_guarded_inputs.py`

- [x] **Step 1: 写保存边界失败测试**

新增：

```python
def test_mark_saved_starts_a_new_undo_boundary(qtbot):
    model = ProjectViewModel(sample_project())
    group_id = model.project.groups[0].id
    model.rename_group(group_id, "已保存")
    model.mark_saved()
    model.rename_group(group_id, "保存后修改")

    model.undo()
    assert model.project.groups[0].name == "已保存"
    assert not model.dirty
    assert not model.can_undo

    model.undo()
    assert model.project.groups[0].name == "已保存"
```

- [x] **Step 2: 写 pending 表单撤销失败测试**

新增：

```python
def test_toolbar_undo_discards_current_pending_form_before_project_history(qtbot):
    window, workflow, step = selected_step_window(qtbot)
    window.property_panel.name_edit.setText("尚未应用")

    window.undo_action.trigger()

    assert window.property_panel.name_edit.text() == step.name
    assert not window.property_panel.has_pending_edits
    assert not window.isWindowModified()
```

- [x] **Step 3: 写 Discard 和运行中关闭失败测试**

覆盖以下测试：

- `test_dirty_close_discard_accepts_event_without_saving`：事件被接受，保存回调调用次数为 0。
- `test_dirty_close_cancel_keeps_pending_values`：事件被忽略，pending 文本保持不变。
- `test_running_close_cancel_keeps_runner_alive`：事件被忽略，假 Runner 的 stop/shutdown 均未调用。
- `test_running_close_stops_and_waits_before_accepting`：先调用 shutdown，返回成功后事件才被接受。
- `test_running_dirty_close_does_not_stop_when_save_fails`：保存返回失败，事件被忽略且 shutdown 未调用。
- `test_close_stays_open_when_runner_shutdown_times_out`：shutdown 返回失败，事件被忽略并显示停止失败消息。

测试使用注入式关闭决策和假 `RunnerBridge`，同时增加一个真实 `QMessageBox` 按钮结果映射测试，避免只验证字符串注入路径。

- [x] **Step 4: 写滚轮保护失败测试**

测试至少覆盖：

- `test_unfocused_spin_box_ignores_wheel_and_scrolls_parent`：数值不变，父滚动条位置改变。
- `test_focused_spin_box_accepts_wheel`：点击聚焦后数值按滚轮方向改变。
- `test_unfocused_combo_box_does_not_change_selection`：当前索引保持不变。
- `test_tuple_numeric_editor_uses_focus_guarded_wheel`：坐标元组中的每个数字框遵循相同规则。

- [x] **Step 5: 运行失败测试并记录 RED**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests\ui\test_focus_guarded_inputs.py `
  tests\ui\test_main_window.py -k "undo or close or discard" `
  tests\ui\test_app_smoke.py -k "close or shutdown"
```

预期：新增测试因保存边界、pending 撤销、运行中关闭和滚轮保护尚未实现而失败。

实际 RED（2026-07-14）：`test_focus_guarded_inputs.py` 为 3 failed / 1 passed；主窗口筛选为 9 failed / 4 passed；app smoke 关闭/停止筛选为 1 failed / 1 passed。

## Task 2: 实现聚焦后才响应滚轮的输入控件

**Files:**
- Create: `flow_runner/ui/widgets/__init__.py`
- Create: `flow_runner/ui/widgets/focus_guarded_inputs.py`
- Modify: `flow_runner/ui/editors/model_form.py`
- Modify: `flow_runner/ui/editors/policy_editor.py`
- Modify: `flow_runner/ui/editors/condition_editor.py`
- Modify: `flow_runner/ui/editors/action_editor.py`
- Modify: `flow_runner/ui/editors/route_editor.py`
- Modify: `flow_runner/ui/dialogs/guided_add_dialog.py`
- Modify: `flow_runner/ui/dialogs/settings_dialog.py`
- Test: `tests/ui/test_focus_guarded_inputs.py`

- [x] **Step 1: 创建统一控件子类**

实现接口：

```python
class FocusWheelComboBox(QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class FocusWheelSpinBox(QSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class FocusWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
```

控件保持 `StrongFocus`，所以鼠标点击和 Tab 聚焦后均可使用滚轮；失焦后滚轮继续传递给父滚动区域。

- [x] **Step 2: 替换所有配置型下拉框和数字框**

只替换用户参数控件，不替换列表、树和滚动条。动态创建的 `ModelForm` 和 `TupleFieldEditor` 必须统一使用新控件。

- [x] **Step 3: 运行滚轮专项测试**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_focus_guarded_inputs.py
```

预期：全部通过。

## Task 3: 重构保存边界和项目级撤销

**Files:**
- Modify: `flow_runner/ui/view_models/project_view_model.py`
- Modify: `flow_runner/ui/panels/property_panel.py`
- Modify: `flow_runner/ui/main_window.py`
- Test: `tests/ui/test_main_window.py`

- [x] **Step 1: 为 ViewModel 增加明确历史状态**

实现：

```python
historyChanged = Signal(bool)

@property
def can_undo(self) -> bool:
    return bool(self._undo_stack)

def mark_saved(self) -> None:
    self._saved_project = self.project
    self._undo_stack.clear()
    self.dirty = False
    self.historyChanged.emit(False)
```

`_commit()` 和 `undo()` 每次更新 `historyChanged`。保存成功后旧历史不可再访问。

- [x] **Step 2: 为 PropertyPanel 增加恢复当前模型的方法**

实现：

```python
def discard_pending(self, step: AutomationStep | None) -> None:
    if step is None:
        self.clear_step()
    else:
        self.set_step(step)
```

该方法只恢复 UI，不调用 `apply_step`，不会产生新历史记录。

- [x] **Step 3: 将工具栏撤销改为窗口协调方法**

实现 `_undo_project_change()`：

1. 若属性面板 pending，重新加载当前项目中的同 UUID 步骤并返回。
2. 否则调用 `view_model.undo()`。
3. 使用阻断信号的选择恢复方法显式刷新当前组、流程和步骤。
4. 更新保存按钮、窗口 `*` 和撤销按钮状态。

- [x] **Step 4: 修复 projectChanged 刷新路径**

`_project_changed()` 不得通过普通选择信号提交旧表单。增加 `_reload_selection_from_project()`，在 `flow_tree` 和 `step_list` 阻断信号时恢复选中项，然后直接调用 `property_panel.set_step()`。

- [x] **Step 5: 运行撤销专项测试**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_main_window.py -k "undo or saved or pending"
```

预期：撤销不能越过保存状态，pending 草稿可撤销，窗口状态同步正确。

## Task 4: 建立事务式关闭流程

**Files:**
- Create: `flow_runner/ui/dialogs/close_confirmation_dialog.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/ui/runner_bridge.py`
- Test: `tests/ui/test_main_window.py`
- Test: `tests/ui/test_app_smoke.py`

- [x] **Step 1: 定义无歧义关闭决策**

实现：

```python
class CloseDecision(StrEnum):
    CANCEL = "cancel"
    CLOSE = "close"
    SAVE_AND_CLOSE = "save_and_close"
    DISCARD_AND_CLOSE = "discard_and_close"
    STOP_AND_CLOSE = "stop_and_close"
    SAVE_STOP_AND_CLOSE = "save_stop_and_close"
    DISCARD_STOP_AND_CLOSE = "discard_stop_and_close"
```

对话框根据 `modified` 和 `running` 只显示适用按钮，按钮使用明确中文文本，不依赖系统 `Discard` 翻译。

- [x] **Step 2: 让 RunnerBridge.shutdown 返回结果**

接口改为：

```python
def shutdown(self, *, timeout_seconds: float = 5.0) -> bool:
    self.stop()
    thread = self._thread
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout_seconds)
    stopped = thread is None or not thread.is_alive()
    if not stopped:
        self._post("failed", "runner did not stop before shutdown timeout")
    self._drain_messages()
    return stopped
```

超时仍发送失败消息，但调用方可据此拒绝关闭。

- [x] **Step 3: 改写 MainWindow.closeEvent**

顺序固定为：

1. 读取 `modified` 和 `running`，获取一次关闭决策。
2. `CANCEL`：忽略事件，不能修改任何状态。
3. 需要保存：先调用 `_save_project()`；失败则忽略事件，不能停止运行。
4. 需要停止：调用 `runner_bridge.shutdown()`；失败则忽略事件并显示“任务未能停止，窗口保持打开”。
5. 需要丢弃：不调用保存，不提交 pending 表单。
6. 所有要求满足后才接受关闭事件。

- [x] **Step 4: 运行关闭专项测试**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests\ui\test_main_window.py -k "close or discard or running" `
  tests\ui\test_app_smoke.py -k "shutdown or close"
```

预期：所有状态组合通过。

## Task 5: 批次一验证与手工验收

**Files:**
- Modify: `README.md`
- Modify: `REFACTOR_STATUS.md`

- [x] **Step 1: 更新用户行为文档**

记录滚轮聚焦规则、撤销保存边界和运行中关闭确认。

- [x] **Step 2: 运行批次一回归**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests\ui
.\.venv\Scripts\python.exe -m ruff check flow_runner tests
.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
.\.venv\Scripts\python.exe -m mypy flow_runner
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

实际结果（2026-07-14）：UI 110 passed；Ruff、格式、mypy、pip check 和 git diff --check 均通过。

- [x] **Step 3: 用户手工验收**

提前说明影响后，请用户验证：

1. 在属性页滚动时参数不变，点击数字框后滚轮可修改。
2. 保存、修改、连续撤销，到保存状态后 `*` 消失且不能继续撤销。
3. 关闭时“不保存并关闭”确实退出且磁盘配置不变。
4. 运行中关闭会提示；取消后任务继续，确认后任务停止再退出。

实际结果（2026-07-14）：四项均通过。首次实测发现 Qt `WheelFocus` 会在滚轮事件前
把焦点转给悬停控件；补充焦点策略回归测试并改用 `StrongFocus` 后复验通过。批次一
最终 UI 回归为 113 passed；Ruff、格式、mypy、pip check 和 git diff --check 均通过。

---

# 批次二：常用/高级配置与模板

## Task 6: 建立编辑器显示模式和字段元数据

**Files:**
- Create: `flow_runner/ui/editor_metadata.py`
- Create: `flow_runner/ui/editor_preferences.py`
- Modify: `flow_runner/ui/editors/model_form.py`
- Test: `tests/ui/test_model_form_modes.py`

- [x] **Step 1: 写常用/高级字段失败测试**

覆盖：OCR、鼠标、键盘、程序启动、等待和窗口动作。常用模式隐藏高级字段；已有非默认高级值仍保留并计数。

- [x] **Step 2: 定义能力常用字段映射**

示例：

```python
COMMON_FIELDS = {
    "vision.ocr": frozenset({"target", "region", "keywords"}),
    "input.mouse": frozenset({"operation", "position", "button", "clicks"}),
    "input.keyboard": frozenset({"operation", "key", "keys", "text", "count"}),
    "system.wait": frozenset({"seconds"}),
    "system.launch": frozenset({"path", "arguments", "run_as_admin"}),
}
```

未列出的字段默认归入高级区域，不能从模型中删除。

- [x] **Step 3: 为 ModelForm 增加字段分区**

接口固定为：`ModelForm.__init__(model_type, *, common_fields: frozenset[str] | None = None,
show_advanced: bool = False)`、`set_advanced_visible(visible: bool) -> None` 和
`advanced_non_default_count() -> int`。

字段行必须可单独显示/隐藏，`values()` 始终读取全部字段。

- [x] **Step 4: 使用 QSettings 保存本机显示偏好**

实际结果（2026-07-14）：新增 10 项模式/元数据/偏好测试；与现有步骤编辑器合计
52 passed，Ruff、格式和严格 mypy 均通过。

只保存 `editor/show_advanced`，不得写入 `project.json`。测试使用隔离的临时 QSettings。

## Task 7: 重组 PropertyPanel，默认隐藏原始 JSON

**Files:**
- Modify: `flow_runner/ui/panels/property_panel.py`
- Modify: `flow_runner/resources/styles/base.qss`
- Test: `tests/ui/test_property_panel_modes.py`

- [x] **Step 1: 写模式切换和数据保留失败测试**

覆盖：常用模式不显示原始 JSON；高级模式显示；来回切换不丢条件、动作、策略和路由。

- [x] **Step 2: 将属性页拆成两个页签**

- `常用配置`：名称、状态、条件引导、动作引导、策略摘要、路由引导。
- `高级 JSON`：条件、动作、检测策略、动作策略、路由 JSON。

默认打开常用配置。高级 JSON 仍使用现有字段和校验路径，不改变项目格式。

- [x] **Step 3: 实现双向同步**

实际结果（2026-07-14）：新增 5 项 PropertyPanel 模式测试；完整 UI 128 passed，
Ruff、格式、严格 mypy、pip check 和 git diff --check 均通过。

进入高级 JSON 前，从引导编辑器生成已格式化 JSON；离开高级 JSON 时先验证并加载。验证失败时停留在高级页并显示具体错误，不覆盖有效引导状态。

## Task 8: 简化策略和路由显示

**Files:**
- Modify: `flow_runner/ui/editors/policy_editor.py`
- Modify: `flow_runner/ui/editors/route_editor.py`
- Modify: `flow_runner/ui/localization.py`
- Test: `tests/ui/test_step_editors.py`

- [x] **Step 1: 增加策略摘要**

示例输出：

```text
持续检测：每 1 秒一次，最多 31 次
动作失败：不重试
```

常用模式显示摘要和核心字段；高级模式显示超时秒数、重试间隔和策略钩子动作。

- [x] **Step 2: 增强路由摘要**

摘要包含结果、附加条件和可读目标名称，例如：

```text
超时 → 键盘命令
成功 且 键盘命令执行次数 > 1 → 不思议挂机B / 开始游戏
成功（否则）→ 不思议挂机 / 开始游戏
```

- [x] **Step 3: 检测无条件路由遮挡**

实际结果（2026-07-14）：新增 3 项策略/路由测试；完整 UI 131 passed，Ruff、
格式、严格 mypy、pip check 和 git diff --check 均通过。

同一结果下，如果无条件路由位于条件路由之前，在保存校验中提示并阻止保存，错误文本指出被遮挡的路由序号。

## Task 9: 增加常用步骤模板

**Files:**
- Create: `flow_runner/ui/step_templates.py`
- Create: `flow_runner/ui/dialogs/template_step_dialog.py`
- Modify: `flow_runner/ui/main_window.py`
- Test: `tests/ui/test_step_templates.py`

- [x] **Step 1: 定义首批模板**

模板生成普通 `AutomationStep`：

1. OCR 检测到文字后点击。
2. OCR 持续检测，超时后继续。
3. 固定等待后执行动作。
4. 激活窗口后发送按键。
5. 执行两轮后跳转到另一流程。
6. 成功和超时进入不同流程。

- [x] **Step 2: 新增“从模板新增步骤”入口**

模板对话框只收集核心参数；创建后自动打开普通属性编辑器，所有高级字段仍可调整。

- [x] **Step 3: 验证模板模型和 UUID 引用**

实际结果（2026-07-15）：新增 4 项模板构造、目标选择和主窗口接入测试；模板与
主窗口合计 33 passed，Ruff、格式和严格 mypy 均通过。

每个模板都执行 `Project.validate_references()`；目标流程/步骤使用下拉框选择，不允许手写 UUID。

## Task 10: 批次二验证与手工验收

- [x] **Step 1: 运行 UI 模式和模板测试**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests\ui\test_model_form_modes.py `
  tests\ui\test_property_panel_modes.py `
  tests\ui\test_step_templates.py `
  tests\ui\test_step_editors.py
```

- [x] **Step 2: 运行完整测试和静态检查**

实际结果（2026-07-15）：批次二专项 64 passed；全量 288 passed；Ruff、格式、
严格 mypy、pip check 和 git diff --check 均通过。

使用批次一的完整验证命令。

- [x] **Step 3: 用户手工验收**

验证常用模式明显缩短页面；高级参数和 JSON 来回切换不丢值；现有 `project.json` 打开、保存和重新加载后模型完全一致。

实际结果（2026-07-15）：临时项目中的常用页面、JSON 往返、保存重载和模板新增
均通过。用户明确取消“显示高级参数”跨次保留的手工验收要求；打开编辑器默认进入
“常用配置”即可。真实业务 `project.json` 未用于本批次保存测试。

---

# 批次三：复制、复用与并行块编辑

## Task 11: 创建纯领域 UUID 克隆服务

**Files:**
- Create: `flow_runner/domain/cloning.py`
- Create: `tests/unit/domain/test_cloning.py`

- [x] **Step 1: 写步骤复制失败测试**

要求：新步骤 UUID；自指 `NEXT_STEP` 和自身 `step_count` 重映射；外部引用保持不变。

- [x] **Step 2: 写流程复制失败测试**

要求：新流程和全部步骤 UUID；内部 `NEXT_STEP`、内部 `step_count`、流程自身 `workflow_count` 重映射；外部流程目标保持不变。

- [x] **Step 3: 写流程组复制失败测试**

要求：组内所有工作流/步骤生成新 UUID；组内跨流程跳转和计数引用重映射；组外引用保持不变；复制结果通过项目引用校验。

- [x] **Step 4: 实现克隆接口**

实际结果（2026-07-15）：新增 3 项步骤/流程/流程组 UUID 克隆测试；领域回归
12 passed，Ruff、格式和严格 mypy 均通过。

公开接口固定为 `clone_step(step: AutomationStep) -> AutomationStep`、
`clone_workflow(workflow: Workflow) -> Workflow` 和
`clone_group(group: FlowGroup) -> FlowGroup`。

内部使用统一 `_remap_route()` 和 `_remap_predicate()`；名称默认追加“副本”。

## Task 12: 将复制操作接入 ViewModel 和主窗口

**Files:**
- Modify: `flow_runner/ui/view_models/project_view_model.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/ui/panels/flow_tree_panel.py`
- Test: `tests/ui/test_main_window.py`

- [x] **Step 1: 增加 ViewModel 方法**

方法签名固定为：

- `copy_step(workflow_id: UUID, step_id: UUID) -> AutomationStep`
- `copy_workflow(group_id: UUID, workflow_id: UUID) -> Workflow`
- `copy_group(group_id: UUID) -> FlowGroup`

复制项插入原项之后，返回新对象用于选中。所有操作进入项目撤销历史。

- [x] **Step 2: 增加上下文相关复制入口**

- 选中步骤：`复制步骤`
- 选中流程：`复制流程`
- 选中流程组：`复制流程组`

动作禁用状态必须与当前选择同步，避免工具栏误操作。

- [x] **Step 3: 验证复制、撤销、保存和重载**

实际结果（2026-07-15）：新增 3 项 ViewModel/UI/持久化复制测试；克隆与主窗口
回归 35 passed，Ruff、格式和严格 mypy 均通过。

复制后保存到临时项目，重新加载并验证 UUID 唯一、引用正确、撤销能够完整删除复制项。

## Task 13: 支持编辑并行块

**Files:**
- Modify: `flow_runner/ui/dialogs/parallel_block_dialog.py`
- Modify: `flow_runner/ui/view_models/project_view_model.py`
- Modify: `flow_runner/ui/main_window.py`
- Test: `tests/ui/test_main_window.py`

- [x] **Step 1: 让 ParallelBlockDialog 支持编辑模式**

构造接口固定为
`ParallelBlockDialog(project: Project, block: ParallelBlock | None = None)`。

编辑时预填名称和成员流程；确认后保留原块 UUID。

- [x] **Step 2: 增加 ViewModel 更新方法**

ViewModel 方法签名固定为 `update_parallel_block(block: ParallelBlock) -> None`。

验证块存在、名称非空、至少两个不同且存在的流程。

- [x] **Step 3: 增加“编辑并行块”动作**

只有选中并行块时启用。编辑结果进入撤销历史并立即刷新左侧树。

- [x] **Step 4: 删除流程前检查并行块依赖**

实际结果（2026-07-15）：新增 4 项并行块编辑、更新、动作状态和删除依赖测试；
主窗口回归 36 passed，Ruff、格式和严格 mypy 均通过。

如果流程仍被并行块引用，阻止删除并显示涉及的并行块名称，要求用户先编辑或删除这些并行块；不得静默修改并行块成员。

## Task 14: 批次三与最终验证

**Files:**
- Modify: `README.md`
- Modify: `REFACTOR_STATUS.md`
- Modify: `IMPROVEMENT_A_PLAN.md`

- [x] **Step 1: 运行克隆和并行块专项测试**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q `
  tests\unit\domain\test_cloning.py `
  tests\ui\test_main_window.py -k "copy or parallel"
```

- [x] **Step 2: 运行完整验证**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check flow_runner tests
.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
.\.venv\Scripts\python.exe -m mypy flow_runner
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

- [x] **Step 3: 审查用户业务配置未被代码任务改写**

实际结果（2026-07-15）：复制/并行专项 7 passed；全量 298 passed；Ruff、格式、
严格 mypy、pip check 和 git diff --check 均通过。任务开始哈希为
`4FD2BE438EE149450D79B27FB6BFE2074C9C507EFB61259F40316BF8AC5526C6`；批次一用户
手工执行“保存边界”验收后主动保存为
`4F5FFF069988E6F070C99DEF7F8A1A962E2ECCA831ECDA3E009D6C4B3182732C`，此后实现和
自动化验证期间保持不变。最终手工验收中，用户再次明确授权使用常用模式保存真实配置，
最终哈希为 `5B49E2C80EA1BF7E4D90711152CBF991350678F377D853FAADB5DDD2BD4C4642`。
两次用户授权保存均由应用按既有规则执行五份备份轮换；实现和自动化过程未主动删除备份。

对比任务开始时的 `project.json` SHA-256 和最终 SHA-256。除用户在应用中主动保存的修改外，自动化实现过程不得改变该文件。保留全部用户备份。

- [x] **Step 4: 用户最终手工验收**

1. 复制“不思议挂机”中的一个测试流程，确认内部步骤路由指向副本。
2. 撤销复制并确认窗口恢复到保存状态。
3. 编辑一个临时并行块并重新加载。
4. 使用常用模式修改并保存真实配置。
5. 运行任务时关闭窗口，验证停止确认和输入释放。

实际结果（2026-07-15）：流程复制内部 UUID、撤销边界、临时并行块编辑/保存/重载、
真实配置常用模式保存/重载均由用户确认通过；运行中关闭与输入释放已在批次一手工验收
通过，无需重复。

- [x] **Step 5: 更新计划状态**

所有验收完成后，在本文档顶部追加完成日期、最终测试数量、仍需用户环境处理的项目，并将 Goal 标记为 complete。

---

## 重开会话继续方式

在新会话中发送：

```text
继续执行“改进A”：D:\3eyes\Python\codex\apps\flow_runner\.worktrees\release-completion\IMPROVEMENT_A_PLAN.md
从批次一 Task 1 开始，严格按 TDD 执行。保留当前 project.json 和所有备份；涉及真实鼠标、键盘、窗口或运行任务的测试先征得我确认。
```

Goal 模式应先执行：

```powershell
cd D:\3eyes\Python\codex\apps\flow_runner\.worktrees\release-completion
git status --short
Get-Content .\IMPROVEMENT_A_PLAN.md
```

然后从第一个未勾选任务继续，不重复已经完成的工作。
