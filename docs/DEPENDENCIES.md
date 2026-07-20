# 项目依赖说明

本项目的 Python 包元数据和版本范围以 [`pyproject.toml`](../pyproject.toml) 为准。下面的
requirements 文件是方便直接使用 pip 的镜像：

- `requirements.txt`：运行项目所需的运行时依赖。
- `requirements-dev.txt`：运行时依赖，加上测试和代码质量工具。

修改依赖版本时，应同步修改 `pyproject.toml` 和对应的 requirements 文件。requirements
文件不包含大型 OCR 可执行程序，也不包含 Windows 系统组件。

## 安装

### 仅安装运行时依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 安装开发和测试依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

如果还需要安装项目本身和 `flow-runner` 控制台入口，推荐使用项目 extra：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

## 运行时依赖

| 依赖 | 使用位置和用途 | 平台 |
| --- | --- | --- |
| `PySide6` | Qt 桌面界面、主窗口、编辑器、对话框、布局、信号槽、快捷键、`QSettings`，以及 Qt 测试控件。 | 全部 |
| `pydantic` | 定义和校验项目、工作流、步骤、条件、动作、策略、路由和录制事件模型，并进行 JSON 序列化。 | 全部 |
| `Pillow` | 桌面/窗口截图、图像裁剪、模板和 OCR 输入、区域选择，以及图像与 Qt 预览之间的转换。 | 全部 |
| `opencv-python` | 图片模板条件的读取、颜色转换和模板匹配，例如 `cv2.matchTemplate`。 | 全部 |
| `numpy` | 像素矩阵和区域变化检测，以及 Windows Graphics Capture 帧缓冲区转换。 | 全部 |
| `pyautogui` | 执行鼠标点击、移动、滚轮、拖拽、键盘按键、热键、文本输入和录制回放。 | 全部；真实输入主要面向 Windows |
| `pynput` | 监听全局控制热键，并记录鼠标和键盘事件。 | 全部；全局桌面监听主要面向 Windows |
| `pywin32` | 枚举和定位 Win32 窗口、读取窗口几何、前台切换、最小化/恢复、移动调整大小、DPI 和 Win32 捕获。 | Windows |
| `windows-capture` | 使用 Windows Graphics Capture 捕获被其他窗口遮挡的目标窗口，作为后台窗口捕获后端。 | Windows |

## OCR 外部组件

OCR 引擎按项目 JSON 的 `settings.ocr_engine` 选择。这些组件不在基础 requirements 文件中，
因为它们不是所有用户都需要，而且其中部分不是 Python 包。

### Tesseract

Tesseract 模式需要：

1. Python 包 `pytesseract`：`python -m pip install pytesseract`。
2. 本机安装 Tesseract 可执行程序。
3. 安装 OCR 条件所需的语言数据，例如 `chi_sim`。

应用在 [`flow_runner/infrastructure/ocr/tesseract.py`](../flow_runner/infrastructure/ocr/tesseract.py)
中动态导入 `pytesseract`。Tesseract 的可执行程序和语言包由用户或部署环境管理。

### PaddleOCR-json

PaddleOCR-json 以独立的 `PaddleOCR-json.exe` 运行，应用通过 stdin/stdout JSON 协议调用。
请在项目设置中选择 PaddleOCR，并配置 `paddle_exe_path`。README 中的示例使用 PaddleOCR-json
v1.4.x；对应的第三方目录包含大型二进制文件，因此不会随 Python 依赖安装。

## 开发工具

`requirements-dev.txt` 中额外包含：

| 依赖 | 用途 |
| --- | --- |
| `pytest` | 单元、集成和 UI 测试框架。 |
| `pytest-asyncio` | 支持 `async def` 测试和 `@pytest.mark.asyncio`。 |
| `pytest-cov` | 生成测试覆盖率报告。 |
| `pytest-qt` | 提供 `qtbot`、Qt 信号等待和控件生命周期管理。 |
| `ruff` | Python lint、导入排序和格式检查。 |
| `mypy` | 严格静态类型检查。 |

构建项目还会使用 `pyproject.toml` 的构建后端 `hatchling`；通过 `pip install -e .` 或构建
项目时 pip 会自动处理它，不需要手动加入运行时 requirements。

## 常用检查

```powershell
python -m pip check
python -m pytest
python -m ruff check .
python -m mypy flow_runner
```

在无显示器环境运行 Qt 测试时，Windows PowerShell 可以先设置：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
```
