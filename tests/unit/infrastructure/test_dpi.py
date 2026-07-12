from flow_runner.infrastructure.windowing.dpi import enable_per_monitor_dpi_awareness


class FakeDpiApi:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def set_per_monitor_v2(self):
        self.calls.append("per_monitor_v2")
        return next(self.results)

    def set_per_monitor(self):
        self.calls.append("per_monitor")
        return next(self.results)

    def set_system_aware(self):
        self.calls.append("system")
        return next(self.results)


def test_dpi_awareness_prefers_per_monitor_v2():
    api = FakeDpiApi([True])

    result = enable_per_monitor_dpi_awareness(platform="win32", api=api)

    assert result == "per_monitor_v2"
    assert api.calls == ["per_monitor_v2"]


def test_dpi_awareness_falls_back_without_failing_startup():
    api = FakeDpiApi([False, False, True])

    result = enable_per_monitor_dpi_awareness(platform="win32", api=api)

    assert result == "system"
    assert api.calls == ["per_monitor_v2", "per_monitor", "system"]


def test_dpi_awareness_is_a_noop_off_windows():
    api = FakeDpiApi([True])

    result = enable_per_monitor_dpi_awareness(platform="linux", api=api)

    assert result == "not_windows"
    assert api.calls == []
