from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType


def _launcher() -> ModuleType:
    path = Path("start_flow_runner.pyw").resolve()
    loader = SourceFileLoader("start_flow_runner", str(path))
    spec = spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not create launcher module spec")
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_launcher_runs_application_from_project_root(monkeypatch, tmp_path):
    launcher = _launcher()
    observed: list[Path] = []
    expected_root = Path("start_flow_runner.pyw").resolve().parent

    def fake_main() -> int:
        observed.append(Path.cwd())
        return 17

    monkeypatch.setattr("flow_runner.app.main", fake_main)
    monkeypatch.chdir(tmp_path)

    result = launcher.run_application()

    assert result == 17
    assert observed == [expected_root]


def test_launcher_reports_traceback_to_data_log(monkeypatch, tmp_path):
    launcher = _launcher()
    messages: list[str] = []
    monkeypatch.setattr(launcher, "_show_error_message", messages.append)

    try:
        raise RuntimeError("launcher boom")
    except RuntimeError as error:
        launcher.report_startup_error(error, tmp_path)

    log_path = tmp_path / "data" / "launcher_error.log"
    content = log_path.read_text(encoding="utf-8")
    assert "RuntimeError: launcher boom" in content
    assert "Traceback" in content
    assert str(log_path) in messages[0]


def test_launcher_still_shows_error_when_log_cannot_be_written(monkeypatch, tmp_path):
    launcher = _launcher()
    messages: list[str] = []
    monkeypatch.setattr(launcher, "_show_error_message", messages.append)
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("occupied", encoding="utf-8")

    launcher.report_startup_error(RuntimeError("launcher boom"), invalid_root)

    assert "RuntimeError: launcher boom" in messages[0]
    assert "无法写入错误日志" in messages[0]
