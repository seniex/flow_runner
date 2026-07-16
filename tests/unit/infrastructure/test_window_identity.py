from flow_runner.infrastructure.windowing.identity import set_windows_app_user_model_id


def test_windows_identity_sets_stable_application_id():
    calls = []

    result = set_windows_app_user_model_id(
        platform="win32", api=lambda value: calls.append(value) or 0
    )

    assert result is True
    assert calls == ["FlowRunner.Qt"]


def test_windows_identity_is_noop_off_windows():
    calls = []

    assert not set_windows_app_user_model_id(platform="linux", api=calls.append)
    assert calls == []
