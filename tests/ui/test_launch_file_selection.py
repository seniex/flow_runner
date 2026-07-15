from pathlib import Path

from flow_runner.ui.launch_file_selection import (
    default_comspec,
    infer_automatic_prefix,
    launch_file_selection,
    replace_automatic_prefix,
)


def test_launch_selection_maps_python_pythonw_batch_and_executable(tmp_path):
    python = tmp_path / "Python" / "python.exe"
    pythonw = python.with_name("pythonw.exe")
    python.parent.mkdir()
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    cmd = tmp_path / "Windows" / "System32" / "cmd.exe"
    cmd.parent.mkdir(parents=True)
    cmd.write_bytes(b"")

    py_path = tmp_path / "任务.py"
    pyw_path = tmp_path / "后台.pyw"
    bat_path = tmp_path / "启动.bat"
    exe_path = tmp_path / "程序.exe"
    py = launch_file_selection(py_path, python_executable=python, comspec=cmd)
    pyw = launch_file_selection(pyw_path, python_executable=python, comspec=cmd)
    bat = launch_file_selection(bat_path, python_executable=python, comspec=cmd)
    exe = launch_file_selection(exe_path, python_executable=python, comspec=cmd)

    assert (py.path, py.arguments) == (python, (str(py_path.resolve()),))
    assert (pyw.path, pyw.arguments) == (pythonw, (str(pyw_path.resolve()),))
    assert (bat.path, bat.arguments) == (cmd, ("/c", str(bat_path.resolve())))
    assert (exe.path, exe.arguments) == (exe_path.resolve(), ())
    assert {item.working_directory for item in (py, pyw, bat, exe)} == {tmp_path}


def test_launch_selection_falls_back_and_preserves_custom_arguments(tmp_path):
    python = tmp_path / "Python" / "python.exe"
    python.parent.mkdir()
    python.write_bytes(b"")
    script = tmp_path / "后台.pyw"
    selection = launch_file_selection(
        script,
        python_executable=python,
        comspec=tmp_path / "cmd.exe",
    )

    assert selection.path == python
    assert replace_automatic_prefix(
        ["old.py", "--profile", "daily"],
        ("old.py",),
        selection.arguments,
    ) == [str(script.resolve()), "--profile", "daily"]


def test_default_comspec_uses_system32_when_environment_value_is_invalid(tmp_path):
    root = tmp_path / "Windows"
    fallback = root / "System32" / "cmd.exe"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"")

    assert (
        default_comspec({"COMSPEC": str(tmp_path / "missing.exe"), "SystemRoot": str(root)})
        == fallback
    )


def test_infer_automatic_prefix_recognizes_only_generated_script_forms(tmp_path):
    python = tmp_path / "python.exe"
    cmd = tmp_path / "cmd.exe"

    assert infer_automatic_prefix(python, ["task.py", "--safe"]) == ("task.py",)
    assert infer_automatic_prefix(cmd, ["/c", "task.bat", "--safe"]) == (
        "/c",
        "task.bat",
    )
    assert infer_automatic_prefix(python, ["-m", "module"]) == ()
    assert infer_automatic_prefix(Path("program.exe"), ["task.py"]) == ()
