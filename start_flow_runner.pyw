from __future__ import annotations

import ctypes
import os
import traceback
from pathlib import Path


def application_root() -> Path:
    return Path(__file__).resolve().parent


def run_application() -> int:
    os.chdir(application_root())
    from flow_runner.app import main

    return main()


def report_startup_error(error: Exception, root: Path | None = None) -> None:
    base = root or application_root()
    log_path = base / "data" / "launcher_error.log"
    log_failure: OSError | None = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            encoding="utf-8",
        )
    except OSError as write_error:
        log_failure = write_error

    message = f"{type(error).__name__}: {error}\n\n"
    if log_failure is None:
        message += f"详细信息已写入：\n{log_path}"
    else:
        message += f"无法写入错误日志：{log_failure}"
    _show_error_message(message)


def _show_error_message(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "Flow Runner 启动失败", 0x10)


if __name__ == "__main__":
    try:
        raise SystemExit(run_application())
    except Exception as error:
        report_startup_error(error)
        raise SystemExit(1) from error
