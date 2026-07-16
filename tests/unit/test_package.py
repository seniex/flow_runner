def test_package_exposes_version():
    import flow_runner

    assert flow_runner.__version__ == "0.3.0"


def test_hatch_builds_the_flow_runner_package():
    import tomllib
    from pathlib import Path

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["flow_runner"]


def test_packaged_icon_resources_are_present():
    from importlib.resources import files

    icon_root = files("flow_runner").joinpath("resources", "icons")
    for name in ("app.svg", "branch-open.svg", "branch-closed.svg"):
        assert icon_root.joinpath(name).is_file()
