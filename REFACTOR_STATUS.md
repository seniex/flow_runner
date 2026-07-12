# Flow Runner PySide6 重构状态

更新日期：2026-07-13  
分支：`refactor/pyside6-workflow`

## 当前结论

计划内的领域模型、运行时、桌面能力适配、三栏 PySide6 编辑器、QSS 契约、并行监控、诊断、配置持久化和打包结构已经实现，并通过确定性自动化验证。

项目尚不能宣告最终验收完成：`REAL_ENVIRONMENT_CHECKLIST.md` 中除 PaddleOCR-json 客户端冒烟外的真实 Windows、显示器和游戏环境项目仍需要用户协助执行并填写证据。

## 已实现范围

- 通用 `AutomationStep`：可选条件树、匹配后动作、检测/动作策略和结果路由。
- ONCE/UNTIL，以及 SUCCESS、NOT_MATCHED、TIMEOUT、FAILURE、CANCELLED 的确定语义。
- 命名 AND/OR/NOT 条件树；仅叶子和唯一命中 OR 暴露 `$result.primary`。
- OCR、图片、像素、区域变化、时间、计数、变量、窗口和进程条件。
- 鼠标、键盘、等待、变量、程序启动、录制回放和窗口动作。
- 跨组 UUID 路由、调用/返回、变量与流程/步骤计数条件路由。
- A1→A2→A3 循环后转 B1，B3 再转 C1 的自动化覆盖。
- 全局感知快照/检测缓存、场景代次、独占动作和陈旧坐标锁内重检。
- Per-Monitor V2 DPI 感知、完整虚拟桌面/Win32 窗口捕获和负坐标原点换算。
- 显式并行块，共享任务变量和资源，隔离流程变量和调用栈。
- 资源竞争的开始、完成和取消诊断；取消多资源等待不会泄漏锁。
- 三栏编辑器、检测/执行/控制添加入口、条件树/动作/策略/路由引导编辑。
- 区域、坐标和文件路径使用专用表单控件；动作坐标可直接保存 `$result...` 运行时绑定。
- 已有动作、路由和策略层每轮前/未命中后动作可在引导编辑器中加载、修改和重新排序。
- 新增控制步骤可从项目感知的下拉框选择当前流程步骤或跨组流程，不必手写 UUID。
- 保存、备份、撤销、脏关闭确认、项目设置、F6–F9 热键和输入录制。
- 启动/暂停/继续/停止、单步运行、条件预览和结构化诊断截图通道。
- PaddleOCR-json v1.4.x 进程生命周期和 stdin/stdout JSON 协议。
- 应用级 QSS；Python UI 文件没有局部视觉样式。

## 自动化证据

2026-07-13 在 Windows、Python 3.12、Qt offscreen 环境执行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q
# 181 passed

.\.venv\Scripts\python.exe -m ruff check flow_runner tests
# All checks passed

.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
# 115 files already formatted

.\.venv\Scripts\python.exe -m mypy flow_runner
# Success: no issues found in 93 source files

.\.venv\Scripts\python.exe -m pip check
# No broken requirements found
```

其他边界验证：

- wheel 构建成功：`flow_runner_qt-0.1.0-py3-none-any.whl`，98 个条目，包含 `base.qss`；SHA-256 为 `B7E8A09217D3A319B9B7312A9E7A91F0F8658E0ACF42AFB69A1ADCA3EC60493B`。
- `import flow_runner; import flow_runner.engine.runner` 输出 `ok`，未创建日志或项目文件。
- 新包和测试中没有 `flow_runner_p1/p2/p3` 导入。
- 新模型中没有 `ocr_click`、`ocr_loop`、`ocr_poll` 或图片对应固定类型。
- 三个旧脚本与主工作区副本逐行内容一致，仅工作树换行格式不同。
- PaddleOCR-json 客户端已识别生成的“开始游戏”图片；随后对用户提供的实际桌面/游戏截图识别 148 项，样本“无响应”边界为 `[794, 560, 837, 582]`、置信度为 `0.999757`，并正常终止子进程。

## 尚需真实环境验收

按 `REAL_ENVIRONMENT_CHECKLIST.md` 继续执行并记录（单显示器桌面捕获和 PaddleOCR-json 已通过）：

- 100%/125%/150% DPI 与多显示器坐标；
- 真实游戏窗口、全屏截图和模板匹配；
- Tesseract 及语言包；
- 实际鼠标、键盘、热键、录制回放和停止中断；
- 窗口激活/移动/缩放和管理员程序启动；
- 并发监控、资源竞争、暂停恢复和关闭清理；
- 配置损坏恢复和异常保存。

已读取的目标机环境：Windows 10 `10.0.19045`、单显示器 `2560×1440`，虚拟桌面原点 `(0, 0)`；新进程 DPI 初始化返回 `per_monitor_v2`。多显示器与三档 DPI 实测因当前硬件/设置不可用而记录为 `BLOCKED`。Tesseract 与 `pytesseract` 未安装，相关验收同样为 `BLOCKED`。

配置恢复与原子保存已在一次性真实文件目录复验：连续保存只保留 5 份备份；损坏主 JSON 后最新备份可加载；模拟 `os.replace` 失败时原文件字节保持不变且 `.tmp` 已清理。

## 明确延期项

- 不生成旧配置到新配置的转换结果；用户将在重构稳定后单独要求。
- 不进行最终视觉设计；等待用户提供 `DESIGN.md` 后只通过 QSS/资源系统应用。
