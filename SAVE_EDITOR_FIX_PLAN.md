# 参数保存失败修复计划

记录日期：2026-07-13
工作树：`D:\3eyes\Python\codex\apps\flow_runner\.worktrees\pyside6-workflow`
分支：`refactor/pyside6-workflow`
基线提交：`7270291 fix: prepare converted clicks before input`

## 当前状态

- 完整参数编辑、一键保存、混合动作序列和 UI 中文化已经实现，但尚未提交 Git。
- 自动化检查在发现本问题前通过：`234 passed`、Ruff、格式检查、mypy、pip check 均通过。
- 用户实际测试发现：即使只删除一个鼠标动作，保存也会提示“项目保存失败：请修正当前步骤中的参数”。
- 本文档创建时只记录修复计划，不实施修复，不修改 `project.json`。
- 工作树中已有其他未提交修改，继续时必须保留，禁止重置或覆盖。
- 根目录存在未跟踪备份 `project.1783952247966102600.bak.json`，继续时先确认来源和内容，不要直接删除。

## 执行结果（2026-07-13）

- `RouteEditor` 的流程和步骤下拉框统一存储规范 UUID 字符串，构建领域模型时显式转回
  `UUID`；跨组跳转、调用流程、当前流程步骤以及流程/步骤计数引用均可从独立 JSON 实例回显。
- `ActionEditor`、`RouteEditor` 和策略内嵌动作编辑器只提交自身真正 pending 的当前表单；切换
  列表项及复制、排序前会先提交原选中项，校验失败时保留原选择和表单；未点击“添加”的新草稿
  不会被静默丢弃，而会提示先添加当前动作或路由。
- `PropertyPanel` 保留最近一次具体校验错误，`MainWindow` 不再用通用提示覆盖；缺失路由目标会显示
  `项目保存失败：路由“成功 → 跳转流程”未选择目标流程`。项目级引用校验也在清除 pending 前
  同步完成，不会再出现 Qt 槽异常或保存旧项目却提示成功。
- 新增回归测试先复现失败，再验证删除一个鼠标动作后直接 `Ctrl+S` 能落盘且路由目标不变。
- 自动化验证完成：`244 passed`，Ruff、格式检查、mypy、pip check 和 `git diff --check` 均通过。
- 修复前后 `project.json` SHA-256 均为
  `CC45C1DF884ACEF1F46690749E052CB9196AEA89AEBB9F399998821B064D1F00`；本次修复没有改动现有
  业务流程参数。
- `project.1783952247966102600.bak.json` 与 `project.json` 长度和 SHA-256 完全相同，确认是同内容
  保存备份；按计划保留，未删除。

## 已完成的复现

使用当前 `project.json` 的临时副本，执行真实 UI 路径：

```text
选择：不思议挂机 / 游戏结束 / 游戏结束
→ 删除第一个鼠标动作
→ 点击保存
```

复现结果：

```text
保存返回：False
界面通用提示：项目保存失败：请修正当前步骤中的参数
被覆盖的原始校验错误：请选择目标流程
```

原步骤有 6 个鼠标动作，删除后编辑器中正确剩余 5 个，因此动作删除本身没有失败。

## 根因

`RouteEditor` 将 `UUID` 对象直接存入 Qt `QComboBox.itemData()`，加载已有项目后又使用
`QComboBox.findData(route_uuid)` 查找目标。

从 JSON 反序列化出来的路由 UUID 与流程 UUID 虽然值相同，但不是同一个 Python 对象。
Qt 的 QVariant 比较没有可靠地按 UUID 值匹配，导致：

```text
已有路由：游戏结束 → A基本挑战2
目标 UUID：6ed52212-f6c6-555a-a00c-9598be9d49ae
下拉框中确实存在相同 UUID
findData(UUID) 返回 -1
当前目标流程变成未选择
```

一键保存会提交所有编辑器，包括用户没有修改的路由，于是删除鼠标动作时也重新构造路由，
最终因目标流程为空而失败。

## 已确认的修复范围

### 1. UUID 下拉框按值查找

在路由编辑器中增加统一 UUID 查找方法，使用规范化字符串值比较，而不是依赖 Qt 对 UUID
对象的 QVariant 比较。覆盖：

- 跳转流程目标；
- 调用流程目标；
- 当前流程目标步骤；
- 流程执行次数条件；
- 步骤执行次数条件。

建议统一在下拉框中存储 UUID 字符串，并在构建领域模型时显式转换为 `UUID`；或者保留 UUID
对象，但所有回显查找都使用逐项字符串比较。优先选择前者，减少 Qt/Python 类型边界问题。

### 2. 编辑器按自身修改状态提交

保存时不能无条件重新构造未修改的动作、路由或策略子编辑器。

- `ActionEditor`、`RouteEditor` 和策略内嵌动作编辑器分别维护明确的 pending 状态；
- 只有该编辑器确实发生修改时，才提交当前表单；
- 未修改的路由直接保留原 `RouteRule`，避免无关动作编辑破坏路由；
- 删除、复制、排序等结构操作必须标记对应编辑器为 pending。

### 3. 保留具体错误

`PropertyPanel.apply_pending()` 失败时应返回或保存具体错误文本。`MainWindow._save_project()`
不得再用“请修正当前步骤中的参数”覆盖原始错误。

期望提示示例：

```text
项目保存失败：路由“成功 → 跳转流程”未选择目标流程
```

### 4. 回归测试

至少新增以下测试：

1. 从磁盘 JSON 加载项目，使流程 UUID 与路由 UUID 为值相同但对象独立的实例。
2. 删除“游戏结束”的一个鼠标动作后直接 `Ctrl+S`。
3. 重启读取项目，确认动作数量减少且原路由目标完全不变。
4. 修改鼠标、键盘、等待、条件和策略参数时，未修改路由不会被重新构造。
5. 已有跨组跳转、调用流程、当前步骤跳转可以正确回显并保存。
6. 流程计数和步骤计数谓词可以正确回显并保存。
7. 保存失败时状态栏显示具体校验错误。
8. 完整 UI、单元和集成测试通过。

## 明确不做的修改

- 不调整“游戏结束”“A基本挑战1”“A基本挑战2”等流程的动作、坐标或时间。
- 不重新运行旧配置转换器。
- 不覆盖或重置当前未提交修改。
- 不修改三个旧脚本。
- 不删除现有项目备份，除非确认备份来源并得到用户许可或能够证明是本轮临时产物。

## 修复后的验证命令

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_step_editors.py tests\ui\test_app_smoke.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check flow_runner tests
.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
.\.venv\Scripts\python.exe -m mypy flow_runner
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

最后必须再次证明 `project.json` 中现有业务流程参数没有被本次修复修改。

## 重启电脑后的继续方式

在管理员 PowerShell 中执行：

```powershell
cd D:\3eyes\Python\codex\apps\flow_runner\.worktrees\pyside6-workflow
git status --short
Get-Content .\SAVE_EDITOR_FIX_PLAN.md
```

然后在 Codex 中发送：

```text
继续执行 SAVE_EDITOR_FIX_PLAN.md
```
