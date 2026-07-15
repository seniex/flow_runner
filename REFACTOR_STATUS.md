# Flow Runner Qt Current Status

更新日期：2026-07-15
分支：`feature-region-picker-dark-ui`

## Current architecture

Flow Runner 使用 Qt/PySide6 组合层、Pydantic 领域模型、Qt 无关执行引擎和可替换的桌面基础设施适配器。活动业务配置与运行数据统一位于 `data/`；显式传入其它 `project_path` 时，辅助目录位于该项目文件旁。

`ProjectDisplayIndex` 统一提供流程组、流程和步骤的独立展示编号；`ApplicationPaths` 统一提供项目、备份、模板、录制和日志路径。展示编号不写入领域模型，原始名称、UUID、路由和执行顺序保持不变。

## Completed functionality

- 通用条件树、动作序列、策略、跨流程路由、调用/返回和显式并行块。
- OCR、图片、像素、区域变化、时间、计数、变量、窗口和进程条件。
- 鼠标、键盘、等待、变量、程序启动、录制回放和窗口动作，并支持取消和资源协调。
- 三栏深色 Qt 工作区、引导编辑器、高级 JSON、步骤模板、复制/排序、撤销、保存和关闭确认。
- 用户已验收 UI 项目 1–4、等待动作倒计时，以及启动、停止、暂停/继续、录制/停止录制全局热键。
- normal/debug 运行日志、取消时真实条件检测次数，以及流程组/流程/步骤各自独立的 `01.`、`02.` 展示编号。
- 活动配置、五份备份、模板、录制、日志和旧转换输入已通过 staging 迁移到 `data/`；旧根目录运行数据和三个废弃单文件实现已清理。
- 已完成计划和转换报告归档到 `docs/archive/`，UI 参考图归档到 `docs/assets/ui-references/`。

## Latest automated verification

2026-07-15 使用全局 Python 3.12 和 Qt offscreen：

- Plan B 最终全量：`337 passed`；专项集合：`162 passed`。
- Ruff lint 通过；`155 files already formatted`。
- mypy：`Success: no issues found in 116 source files`。
- `compileall`、`pip check`、`git diff --check` 通过。
- Plan B 专项验证覆盖取消计数、显示编号、UI、路径组合、独立备份、区域截图和 staging 迁移。

## Real-environment acceptance

- UI 验收项目 1–4：用户已确认通过。
- 等待动作倒计时：用户已确认暂停冻结、继续恢复和停止取消行为通过。
- 全局热键：PASS（2026-07-15，用户实测）：启动、停止、暂停/继续、录制/停止录制均成功；未观察到重复触发。
- 其它已经执行的真实 Windows、窗口捕获、输入、OCR、DPI、录制回放和程序启动证据保留在 `REAL_ENVIRONMENT_CHECKLIST.md`。

## Deferred acceptance

- 多显示器：`DEFERRED`。用户于 2026-07-15 明确延期；恢复条件是提供第二块物理或虚拟显示器。
- Tesseract：`DEFERRED`。用户于 2026-07-15 明确延期；恢复条件是用户决定安装程序、语言包和 Python 依赖。

这两项不是 Plan B 完成阻塞项，也未被记录为通过。

## Active runtime data layout

```text
data/
├─ project.json
├─ backups/
├─ templates/
│  └─ legacy/
├─ recordings/
│  └─ legacy/
├─ logs/
└─ legacy/
   ├─ config/
   └─ scripts/
```

## Remaining Plan B checks

无。用户已于 2026-07-15 确认六项 Plan B GUI 手工检查全部通过。多显示器和 Tesseract 保持 `DEFERRED`，未执行也未记录为通过。
