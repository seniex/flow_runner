# Flow Runner Windows 双击启动器设计

日期：2026-07-15
状态：已确认，等待规格审阅

## 目标

在项目根目录提供一个可由 Windows 资源管理器直接双击的无控制台启动入口，同时保证应用始终从项目根目录解析默认 `data/project.json`，并在启动失败时给出可见、可追踪的错误信息。

## 启动入口

新增根目录 `start_flow_runner.pyw`。Windows 使用当前 `.pyw` 文件关联的 `pythonw.exe` 运行该文件，因此关联的全局 Python 必须已经安装 Flow Runner 及其运行依赖。

启动器只负责：

1. 通过 `Path(__file__).resolve().parent` 确定项目根目录。
2. 使用 `os.chdir()` 将当前工作目录切换到项目根目录。
3. 延迟导入并调用 `flow_runner.app.main()`。

启动器不复制应用组合逻辑，不创建第二个 Python 进程，也不修改 `flow_runner.app` 的命令行入口。

## 错误处理

启动器只捕获 `Exception`，不捕获正常的 `SystemExit`。

发生启动异常时：

- 创建 `data/`（如果尚不存在）。
- 将 `traceback.format_exception()` 产生的完整 traceback 以 UTF-8 写入 `data/launcher_error.log`，覆盖上一次启动错误。
- 使用 Windows `user32.MessageBoxW` 显示错误摘要和日志路径。
- 以退出码 1 结束。

如果错误日志本身无法写入，错误对话框仍显示原始异常，并附带日志写入失败原因。

## 可测试边界

启动器提供小型函数边界：

- `application_root()`：返回启动器所在项目根目录。
- `run_application()`：切换工作目录、延迟导入并返回 `flow_runner.app.main()` 的结果。
- `report_startup_error(error, root=None)`：写入错误日志并调用独立的 `_show_error_message()`。

测试通过文件路径动态导入 `.pyw`，不会进入 `if __name__ == "__main__"` 分支，也不会打开真实 GUI。

至少验证：

- 从其它工作目录调用 `run_application()` 时，应用主函数观察到的工作目录是项目根目录，返回码保持不变。
- `report_startup_error()` 在临时根目录的 `data/launcher_error.log` 写入异常类型、消息和 traceback，并向消息函数传递日志路径。

## README

在 `README.md` 的 Running 章节补充 Windows 双击方式：

- 双击项目根目录的 `start_flow_runner.pyw`。
- 该方式使用 Windows 当前关联的全局 `pythonw.exe`，必须先按全局 Python 安装方式安装依赖。
- 默认加载 `data/project.json`。
- 启动错误写入 `data/launcher_error.log` 并弹出错误对话框。

## 非目标

- 不创建 `.bat`、`.vbs`、Windows 快捷方式、安装程序或桌面图标。
- 不自动选择 `.venv` 中的 Python。
- 不启动真实 GUI 作为自动化测试。
- 不修改应用业务逻辑、项目数据或版本号。

## 验证

- 新增的启动器单元测试通过。
- 现有包版本测试通过。
- Ruff、格式检查和 `git diff --check` 通过。
- README 中的启动器文件名、全局 Python 前置条件和错误日志路径与实现一致。
