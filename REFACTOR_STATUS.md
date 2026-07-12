# Flow Runner PySide6 重构状态

更新日期：2026-07-13  
分支：`refactor/pyside6-workflow`

## 当前结论

计划内的领域模型、运行时、桌面能力适配、三栏 PySide6 编辑器、QSS 契约、并行监控、诊断、配置持久化和打包结构已经实现，并通过确定性自动化验证。

项目尚不能宣告最终验收完成：真实 Windows 验收已覆盖双模式窗口捕获、视觉检测、窗口动作、录制回放和核心调度，但首次窗口尺寸、输入取消、输入法文本写入和程序工作目录暴露出需要修复的问题；全局热键、管理员启动、DPI、多显示器和 Tesseract 仍受实机条件或用户确认限制。

## 已实现范围

- 通用 `AutomationStep`：可选条件树、匹配后动作、检测/动作策略和结果路由。
- ONCE/UNTIL，以及 SUCCESS、NOT_MATCHED、TIMEOUT、FAILURE、CANCELLED 的确定语义。
- 命名 AND/OR/NOT 条件树；仅叶子和唯一命中 OR 暴露 `$result.primary`。
- OCR、图片、像素、区域变化、时间、计数、变量、窗口和进程条件。
- 鼠标、键盘、等待、变量、程序启动、录制回放和窗口动作。
- 鼠标坐标偏移、按下/释放/拖拽与键盘按下/释放；运行终止和回放取消时兜底释放已保持输入。
- 跨组 UUID 路由、调用/返回、变量与流程/步骤计数条件路由。
- 路由谓词可直接比较 `$result.primary.*` 或 `$result.children["别名"].*`，并保持复合条件的歧义保护。
- A1→A2→A3 循环后转 B1，B3 再转 C1 的自动化覆盖。
- 全局感知快照/检测缓存、场景代次、独占动作和陈旧坐标锁内重检。
- Per-Monitor V2 DPI 感知、完整虚拟桌面/Win32 窗口捕获和负坐标原点换算。
- 前台 BitBlt 与后台 Windows Graphics Capture 双模式；支持项目默认、目标覆盖、显式回退诊断及共享窗口锁/场景代次。
- 显式并行块，共享任务变量和资源，隔离流程变量和调用栈。
- 资源竞争的开始、完成和取消诊断；取消多资源等待不会泄漏锁。
- 三栏编辑器、检测/执行/控制添加入口、条件树/动作/策略/路由引导编辑。
- 流程可在组内排序或跨组移动，稳定 UUID 路由不会因分类调整而改变。
- 区域、坐标和文件路径使用专用表单控件；动作坐标可直接保存 `$result...` 运行时绑定。
- 已有动作、路由和策略层每轮前/未命中后动作可在引导编辑器中加载、修改和重新排序。
- 新增控制步骤可从项目感知的下拉框选择当前流程步骤或跨组流程，不必手写 UUID。
- OCR、图片等检测能力切换前会列出将舍弃的专属字段并允许取消，公共字段继续保留。
- 保存、备份、撤销、脏关闭确认、项目设置、F6–F9 热键和输入录制。
- 启动/暂停/继续/停止、单步运行、条件预览和结构化诊断截图通道。
- PaddleOCR-json v1.4.x 进程生命周期和 stdin/stdout JSON 协议。
- 应用级 QSS；Python UI 文件没有局部视觉样式。

## 自动化证据

2026-07-13 在 Windows、Python 3.12、Qt offscreen 环境执行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q
# 205 passed

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

- wheel 构建成功：`flow_runner_qt-0.1.0-py3-none-any.whl`，100 个条目，包含 `base.qss`、`capture_targets.py` 和 `windows_graphics.py`；SHA-256 为 `831281CD056BC2D0C3D492A33CFE6FB9AADAD8BAA3254278D3096469BC935D22`。
- `import flow_runner; import flow_runner.engine.runner` 输出 `ok`，未创建日志或项目文件。
- 新包和测试中没有 `flow_runner_p1/p2/p3` 导入。
- 新模型中没有 `ocr_click`、`ocr_loop`、`ocr_poll` 或图片对应固定类型。
- 三个旧脚本与主工作区副本逐行内容一致，仅工作树换行格式不同。
- PaddleOCR-json 客户端已识别生成的“开始游戏”图片；随后对用户提供的实际桌面/游戏截图识别 148 项，样本“无响应”边界为 `[794, 560, 837, 582]`、置信度为 `0.999757`，并正常终止子进程。

## 尚需真实环境验收

按 `REAL_ENVIRONMENT_CHECKLIST.md` 继续执行并记录或修复：

- 100%/125%/150% DPI 与多显示器坐标；
- Tesseract 及语言包；
- 首次主窗口高度超过桌面，属性面板需要可滚动布局；
- 长鼠标/键盘动作取消后底层 `pyautogui` 仍会继续执行；
- 中文输入法激活时文本写入结果不稳定，需要明确按键输入与文本注入模式；
- 程序启动需要补充可配置工作目录；管理员启动仍需单独确认 UAC；
- 全局热键需要在旧 BgOcrClick 程序退出或确认隔离后实测；

已读取的目标机环境：Windows 10 `10.0.19045`、单显示器 `2560×1440`，虚拟桌面原点 `(0, 0)`；新进程 DPI 初始化返回 `per_monitor_v2`。多显示器与三档 DPI 实测因当前硬件/设置不可用而记录为 `BLOCKED`。Tesseract 与 `pytesseract` 未安装，相关验收同样为 `BLOCKED`。

只读真实游戏环境检查已通过：前台 `懒人修仙传2` 窗口截图非空且原点/尺寸正确；真实桌面模板匹配、像素容差内外判断、游戏窗口连续帧区域变化，以及真实窗口/进程条件均产生预期结果。

真实桌面动作检查已完成一轮：临时窗口激活/最小化/恢复/移动缩放通过；鼠标各操作和键盘按下/释放会产生真实事件，录制回放及取消时释放 Ctrl 通过。实测也证明当前取消长鼠标移动只取消 asyncio 任务，底层线程仍继续移动；中文输入法下 `write` 无法保证目标文本。专项调度测试 61 项通过，覆盖跨组循环、调用返回、并行共享、资源冲突、陈旧坐标重检、暂停恢复和停止退出。

后台 Windows Graphics Capture 已在同一游戏窗口实测：Chrome 完全遮挡游戏时，后台帧与遮挡前游戏帧平均像素差为 `0.037`，与屏幕可见遮挡内容的平均像素差为 `40.87`；测试结束后游戏窗口恢复前台。

配置恢复与原子保存已在一次性真实文件目录复验：连续保存只保留 5 份备份；损坏主 JSON 后最新备份可加载；模拟 `os.replace` 失败时原文件字节保持不变且 `.tmp` 已清理。

## 明确延期项

- 不生成旧配置到新配置的转换结果；用户将在重构稳定后单独要求。
- 不进行最终视觉设计；等待用户提供 `DESIGN.md` 后只通过 QSS/资源系统应用。
