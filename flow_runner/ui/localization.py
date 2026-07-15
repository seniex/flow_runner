from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from flow_runner.domain.actions import ActionSpec

CAPABILITY_LABELS = {
    "vision.ocr": "OCR 文字检测",
    "vision.image": "图片模板检测",
    "vision.pixel": "像素颜色检测",
    "vision.region_change": "区域变化检测",
    "system.window": "窗口状态检测",
    "system.process": "进程状态检测",
    "variables.compare": "变量比较",
    "runtime.count": "执行次数检测",
    "time.check": "时间条件",
    "input.mouse": "鼠标操作",
    "input.keyboard": "键盘操作",
    "system.wait": "等待",
    "system.launch": "启动程序",
    "recording.playback": "播放录制脚本",
    "variables.set": "设置变量",
    "system.window_action": "窗口操作",
}


FIELD_LABELS = {
    "target": "检测目标",
    "region": "检测区域",
    "keywords": "匹配文字",
    "language": "识别语言",
    "preprocessing": "图像预处理",
    "scale": "识别缩放",
    "template_path": "模板图片",
    "threshold": "匹配阈值",
    "position": "坐标",
    "color": "颜色（RGB）",
    "tolerance": "颜色容差",
    "channel_tolerance": "通道容差",
    "title": "窗口标题",
    "require_foreground": "必须位于前台",
    "name": "名称",
    "scope": "变量范围",
    "operator": "比较方式",
    "expected": "期望值",
    "counter": "计数类型",
    "target_id": "目标 ID",
    "mode": "模式",
    "started_at": "起始时间",
    "seconds": "等待时间（秒）",
    "start": "开始时间",
    "end": "结束时间",
    "operation": "操作类型",
    "offset": "坐标偏移",
    "button": "鼠标按键",
    "clicks": "点击次数",
    "interval": "动作间隔（秒）",
    "duration": "移动时长（秒）",
    "scroll_units": "滚轮量",
    "jitter_pixels": "随机偏移（像素）",
    "settle_delay": "点击前稳定等待（秒）",
    "key": "按键",
    "keys": "组合键列表",
    "text": "输入文字",
    "text_mode": "文字输入模式",
    "count": "执行次数",
    "path": "文件路径",
    "arguments": "启动参数列表",
    "run_as_admin": "以管理员身份运行",
    "working_directory": "工作目录",
    "hide_window": "隐藏程序窗口",
    "speed": "播放速度",
    "max_gap": "最大事件间隔（秒）",
    "jitter_ms": "时间随机偏移（毫秒）",
    "value": "变量值",
    "geometry": "窗口位置和尺寸",
}

RESULT_FIELD_LABELS = {
    "position": "坐标",
    "bounds": "边界区域",
    "text": "识别文字",
    "confidence": "置信度",
}


CHOICE_LABELS = {
    "and": "并且（AND）",
    "or": "或者（OR）",
    "not": "取反（NOT）",
    "click": "点击",
    "move": "移动",
    "scroll": "滚轮",
    "button_down": "按住鼠标键",
    "button_up": "释放鼠标键",
    "drag": "拖动",
    "left": "左键",
    "right": "右键",
    "middle": "中键",
    "press": "按下并释放",
    "hotkey": "组合键",
    "write": "输入文字",
    "key_down": "按住按键",
    "key_up": "释放按键",
    "keys": "模拟按键",
    "unicode": "Unicode 输入",
    "clipboard": "剪贴板粘贴",
    "task": "当前任务",
    "workflow": "当前流程",
    "persistent": "持久变量",
    "activate": "激活窗口",
    "minimize": "最小化窗口",
    "restore": "还原窗口",
    "move_resize": "移动并调整大小",
    "elapsed": "经过指定时间",
    "local_range": "本地时间范围",
    "step": "步骤执行次数",
    "match": "匹配",
    "no_match": "未匹配",
    "error": "错误",
    "success": "成功",
    "not_matched": "单次未匹配",
    "timeout": "超时",
    "failure": "失败",
    "cancelled": "已取消",
    "next_step": "跳到本流程中的指定步骤",
    "jump_workflow": "跳转流程",
    "call_workflow": "调用流程",
    "return": "返回调用方",
    "end": "结束任务",
    "task_variable": "任务变量",
    "workflow_variable": "流程变量",
    "workflow_count": "流程执行次数",
    "step_count": "步骤执行次数",
    "binding": "当前检测结果",
    "eq": "等于",
    "ne": "不等于",
    "lt": "小于",
    "le": "小于等于",
    "gt": "大于",
    "ge": "大于等于",
    "contains": "包含",
    "matches": "正则匹配",
    "idle": "空闲",
    "running": "运行中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "runner.state": "运行状态",
    "step.started": "步骤开始",
    "step.finished": "步骤完成",
    "route.selected": "已选择路由",
    "condition.preview": "条件预览",
    "resource.wait.started": "等待资源",
    "resource.wait.finished": "资源可用",
    "resource.wait.cancelled": "资源等待已取消",
}

COMPARISON_SYMBOLS = {
    "eq": "=",
    "ne": "!=",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
    "contains": "包含",
    "matches": "正则匹配",
}


def capability_label(name: str) -> str:
    return CAPABILITY_LABELS.get(name, name)


def field_label(name: str) -> str:
    return FIELD_LABELS.get(name, name)


def result_field_label(name: str) -> str:
    return RESULT_FIELD_LABELS.get(name, name)


def choice_label(value: Any) -> str:
    raw = value.value if isinstance(value, Enum) else value
    return CHOICE_LABELS.get(str(raw), str(raw))


def comparison_symbol(value: Any) -> str:
    raw = value.value if isinstance(value, Enum) else value
    return COMPARISON_SYMBOLS.get(str(raw), choice_label(raw))


def action_summary(
    action: ActionSpec,
    *,
    binding_labels: Mapping[str, str] | None = None,
) -> str:
    config = action.config
    if action.capability == "input.mouse":
        operation = choice_label(config.get("operation", ""))
        position = _format_position(config.get("position"), binding_labels)
        button = choice_label(config.get("button", "left"))
        clicks = config.get("clicks", 1)
        detail = (
            f"{button}{operation} {position}" if operation == "点击" else f"{operation} {position}"
        )
        if operation == "点击" and clicks != 1:
            detail += f" ×{clicks}"
        return f"鼠标：{detail}".strip()
    if action.capability == "input.keyboard":
        operation = choice_label(config.get("operation", ""))
        key = config.get("key") or "+".join(config.get("keys", [])) or config.get("text", "")
        return f"键盘：{operation} {key}".strip()
    if action.capability == "system.wait":
        return f"等待：{config.get('seconds', 0)} 秒"
    if action.capability == "recording.playback":
        name = Path(str(config.get("path", ""))).name
        return f"播放录制：{name}" if name else capability_label(action.capability)
    if action.capability == "system.launch":
        name = _launch_target_name(config)
        return f"启动程序：{name}" if name else capability_label(action.capability)
    if action.capability == "system.window_action":
        return (
            f"窗口：{choice_label(config.get('operation', ''))} {config.get('title', '')}".strip()
        )
    if action.capability == "variables.set":
        return f"设置变量：{config.get('name', '')}"
    return capability_label(action.capability)


def _launch_target_name(config: dict[str, Any]) -> str:
    raw_path = str(config.get("path", "")).strip()
    arguments = config.get("arguments", [])
    values = [str(value) for value in arguments] if isinstance(arguments, list) else []
    executable = Path(raw_path)
    executable_name = executable.name.casefold()
    if executable_name in {"python.exe", "pythonw.exe", "python", "pythonw"} and values:
        return Path(values[0]).name
    if executable_name in {"cmd.exe", "cmd"} and len(values) >= 2 and values[0].casefold() == "/c":
        return Path(values[1]).name
    return executable.name


def _format_position(value: Any, binding_labels: Mapping[str, str] | None = None) -> str:
    if isinstance(value, str):
        return binding_labels.get(value, value) if binding_labels is not None else value
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"({value[0]}, {value[1]})"
    return ""
