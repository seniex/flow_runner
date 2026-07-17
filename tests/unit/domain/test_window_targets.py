import pytest
from pydantic import ValidationError

from flow_runner.domain.window_targets import WindowTarget


def test_process_target_normalizes_ordered_names_and_deduplicates_fallbacks():
    target = WindowTarget(
        process_name=" Chrome.EXE ",
        fallback_process_names=["PotPlayerMini64.exe", "chrome.exe", "potplayer.exe"],
    )

    assert target.process_names == (
        "Chrome.EXE",
        "PotPlayerMini64.exe",
        "potplayer.exe",
    )
    assert target.matching_process_names == (
        "chrome.exe",
        "potplayermini64.exe",
        "potplayer.exe",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"process_name": "", "title": "Game"},
        {"process_name": "chrome.exe", "title": "Game"},
        {"process_name": "chrome.exe", "fallback_process_names": [""]},
    ],
)
def test_target_requires_exactly_one_non_empty_selector(payload):
    with pytest.raises(ValidationError):
        WindowTarget.model_validate(payload)


def test_title_target_keeps_legacy_selector_and_resource_key():
    target = WindowTarget(title="懒人修仙传2")

    assert target.process_names == ()
    assert target.resource_key == "window:懒人修仙传2"


def test_process_target_resource_key_uses_normalized_ordered_names():
    target = WindowTarget(
        process_name="Chrome.EXE",
        fallback_process_names=["PotPlayerMini64.exe"],
    )

    assert target.resource_key == "window:process:chrome.exe|potplayermini64.exe"
