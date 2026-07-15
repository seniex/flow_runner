from pathlib import Path

import pytest

from flow_runner.ui.theme_manager import ThemeManager


def test_theme_manager_applies_application_wide_qss(qapp, tmp_path):
    path = tmp_path / "theme.qss"
    path.write_text('QPushButton[role="primary"] { color: red; }', encoding="utf-8")

    ThemeManager().apply(qapp, path)

    assert '[role="primary"]' in qapp.styleSheet()


def test_theme_manager_reports_missing_file(qapp, tmp_path):
    with pytest.raises(FileNotFoundError, match="missing.qss"):
        ThemeManager().apply(qapp, tmp_path / "missing.qss")


def test_base_qss_contains_required_semantic_selectors():
    qss = Path("flow_runner/resources/styles/base.qss").read_text(encoding="utf-8")
    for selector in (
        '[role="primary"]',
        '[status="running"]',
        "#simpleWorkspace",
        "#flowTreePanel",
        "#stepListPanel",
        "#stepCard",
        "#propertyPanel",
        "#runtimeLog",
    ):
        assert selector in qss
    assert "background: #111424" in qss
    for selector in (
        "QToolButton {",
        "QToolButton:hover",
        "QToolButton:pressed",
        "QToolButton:disabled",
        "QToolButton:checked",
    ):
        assert selector in qss
