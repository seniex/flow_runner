import pytest

from flow_runner.domain.window_targets import WindowTarget
from flow_runner.infrastructure.windowing import win32
from flow_runner.infrastructure.windowing.win32 import _PyWin32WindowBackend


class FakeGui:
    def __init__(self, *, foreground=1, minimized=(), maximized=()):
        self.foreground = foreground
        self.minimized = set(minimized)
        self.maximized = set(maximized)
        self.calls = []
        self.windows = {1: "Chrome", 2: "Chrome popup", 3: "PotPlayer", 4: "Other"}

    def EnumWindows(self, callback, extra):
        for handle in self.windows:
            callback(handle, extra)

    def IsWindowVisible(self, handle):
        return handle != 4

    def GetWindowText(self, handle):
        return self.windows[handle]

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, handle):
        return handle in self.minimized

    def IsZoomed(self, handle):
        return handle in self.maximized

    def ShowWindow(self, handle, command):
        self.calls.append(("show", handle, command))
        if command == 9:
            self.minimized.discard(handle)
        if command == 6:
            self.minimized.add(handle)

    def SetForegroundWindow(self, handle):
        self.calls.append(("foreground", handle))
        self.foreground = handle

    def SetWindowPos(self, handle, _insert_after, x, y, width, height, flags):
        self.calls.append(("geometry", handle, x, y, width, height, flags))


class FakeProcess:
    def GetWindowThreadProcessId(self, handle):
        return (100 + handle, handle)


class FakeConstants:
    SW_RESTORE = 9
    SW_MINIMIZE = 6
    SW_FORCEMINIMIZE = 11
    SWP_NOZORDER = 4


def backend(gui, names):
    return _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        process_name_for_pid=lambda pid: names[pid],
        is_maximized=gui.IsZoomed,
    )


def test_process_matching_uses_first_process_with_matches_and_casefolds_names():
    gui = FakeGui()
    target = WindowTarget(
        process_name="missing.exe",
        fallback_process_names=["CHROME.EXE", "potplayer.exe"],
    )
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    result = adapter.query(target)

    assert result["matched_handles"] == [1, 2]
    assert result["selected_process_name"] == "chrome.exe"
    assert result["attempted_process_names"] == ["missing.exe", "CHROME.EXE", "potplayer.exe"]


def test_activate_prefers_foreground_without_restoring_a_visible_window():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui(foreground=2, minimized=(1,))
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "chrome.exe"})

    adapter.activate(target)

    assert ("show", 2, 9) not in gui.calls
    assert ("foreground", 2) in gui.calls


def test_activate_restores_a_minimized_window_before_foregrounding():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui(foreground=3, minimized=(1, 2))
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    result = adapter.activate(target)

    assert ("show", 1, 9) in gui.calls
    assert result["matched_windows"][0]["minimized"] is False


def test_activate_preserves_a_visible_maximized_window():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui(foreground=3, maximized=(1,))
    adapter = backend(gui, {1: "chrome.exe", 2: "potplayer.exe", 3: "potplayer.exe"})

    result = adapter.activate(target)

    assert ("show", 1, 9) not in gui.calls
    assert result["foreground"] is True
    assert result["matched_windows"][0]["maximized"] is True


def test_minimize_and_restore_apply_to_all_matching_windows():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui()
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    minimized = adapter.minimize(target)
    restored = adapter.restore(target)

    assert [call for call in gui.calls if call[:2] == ("show", 1)] == [
        ("show", 1, 6),
        ("show", 1, 9),
    ]
    assert [call for call in gui.calls if call[:2] == ("show", 2)] == [
        ("show", 2, 6),
        ("show", 2, 9),
    ]
    assert not [call for call in gui.calls if call[0] == "foreground"]
    assert all(window["minimized"] for window in minimized["matched_windows"])
    assert all(not window["minimized"] for window in restored["matched_windows"])


def test_move_resize_uses_single_selection_without_foregrounding():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui(foreground=3)
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    adapter.move_resize(target, (10, 20, 800, 600))

    assert ("geometry", 1, 10, 20, 800, 600, 4) in gui.calls
    assert not [call for call in gui.calls if call[0] == "foreground"]


def test_missing_process_image_is_skipped_without_aborting_enumeration():
    target = WindowTarget(process_name="chrome.exe")
    gui = FakeGui()
    names = {1: RuntimeError("gone"), 2: "chrome.exe", 3: "potplayer.exe"}

    def resolve(pid):
        value = names[pid]
        if isinstance(value, Exception):
            raise value
        return value

    result = _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        process_name_for_pid=resolve,
    ).query(target)

    assert result["matched_handles"] == [2]


def test_title_target_preserves_first_visible_substring_match():
    target = WindowTarget(title="Chrome")
    gui = FakeGui(foreground=2)
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    result = adapter.query(target)

    assert result["matched_handles"] == [1]
    assert result["selected_handle"] == 1
    assert result["title"] == "Chrome"


def test_activate_retries_after_alt_tap_when_foreground_lock_blocks_first_call():
    class LockedGui(FakeGui):
        def SetForegroundWindow(self, handle):
            self.calls.append(("foreground", handle))
            if len([call for call in self.calls if call[0] == "foreground"]) >= 2:
                self.foreground = handle

    class FakeApi:
        def __init__(self):
            self.calls = []

        def keybd_event(self, key, _scan, flags, _extra):
            self.calls.append((key, flags))

    gui = LockedGui(foreground=3)
    api = FakeApi()
    adapter = _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        win32api=api,
        process_name_for_pid=lambda pid: "chrome.exe" if pid in {1, 2} else "potplayer.exe",
    )

    adapter.activate(WindowTarget(process_name="chrome.exe"))

    assert api.calls == [(0x12, 0), (0x12, 2)]
    assert [call for call in gui.calls if call[0] == "foreground"] == [
        ("foreground", 1),
        ("foreground", 1),
    ]


def test_activate_invokes_injected_foreground_unlocker_before_retry():
    class LockedGui(FakeGui):
        def SetForegroundWindow(self, handle):
            self.calls.append(("foreground", handle))
            if len([call for call in self.calls if call[0] == "foreground"]) >= 2:
                self.foreground = handle

    gui = LockedGui(foreground=3)
    unlocks = []
    adapter = _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        process_name_for_pid=lambda pid: "chrome.exe" if pid in {1, 2} else "potplayer.exe",
        foreground_unlocker=lambda: unlocks.append("unlock"),
    )

    adapter.activate(WindowTarget(process_name="chrome.exe"))

    assert unlocks == ["unlock"]


def test_restore_preserves_the_previous_foreground_window():
    class RestoreStealsForegroundGui(FakeGui):
        def ShowWindow(self, handle, command):
            super().ShowWindow(handle, command)
            if command == 9:
                self.foreground = handle

    gui = RestoreStealsForegroundGui(foreground=3, minimized=(1, 2))
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    result = adapter.restore(WindowTarget(process_name="chrome.exe"))

    assert gui.foreground == 3
    assert result["foreground"] is False
    assert ("foreground", 3) in gui.calls


def test_minimize_uses_force_minimize_when_the_normal_request_is_ignored():
    class IgnoreMinimizeGui(FakeGui):
        def ShowWindow(self, handle, command):
            self.calls.append(("show", handle, command))
            if command == 9:
                self.minimized.discard(handle)

    gui = IgnoreMinimizeGui()
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    with pytest.raises(RuntimeError, match="failed to minimize"):
        adapter.minimize(WindowTarget(process_name="chrome.exe"))

    assert ("show", 1, 6) in gui.calls
    assert ("show", 1, 11) in gui.calls


def test_activate_fails_when_the_window_never_reaches_foreground():
    class LockedGui(FakeGui):
        def SetForegroundWindow(self, handle):
            self.calls.append(("foreground", handle))

    gui = LockedGui(foreground=3)
    adapter = _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        process_name_for_pid=lambda pid: "chrome.exe" if pid in {1, 2} else "potplayer.exe",
        foreground_unlocker=lambda: None,
    )

    with pytest.raises(RuntimeError, match="failed to foreground"):
        adapter.activate(WindowTarget(process_name="chrome.exe"))


def test_restore_fails_when_a_matching_window_stays_minimized():
    class IgnoreRestoreGui(FakeGui):
        def ShowWindow(self, handle, command):
            self.calls.append(("show", handle, command))
            if command == 6:
                self.minimized.add(handle)

    gui = IgnoreRestoreGui(minimized=(1, 2))
    adapter = backend(gui, {1: "chrome.exe", 2: "chrome.exe", 3: "potplayer.exe"})

    with pytest.raises(RuntimeError, match="failed to restore"):
        adapter.restore(WindowTarget(process_name="chrome.exe"))


def test_wscript_foreground_unlock_failure_is_best_effort(monkeypatch):
    class Shell:
        def SendKeys(self, _keys):
            raise ValueError("COM unavailable")

    class Client:
        def Dispatch(self, _name):
            return Shell()

    monkeypatch.setattr(win32.importlib, "import_module", lambda _name: Client())

    win32._send_wscript_alt()


def test_maximized_state_uses_injected_native_query_when_pywin32_lacks_is_zoomed():
    gui = FakeGui(foreground=3)
    gui.IsZoomed = None
    adapter = _PyWin32WindowBackend(
        win32gui=gui,
        win32con=FakeConstants(),
        win32process=FakeProcess(),
        process_name_for_pid=lambda pid: "chrome.exe" if pid == 1 else "potplayer.exe",
        is_maximized=lambda handle: handle == 1,
    )

    result = adapter.query(WindowTarget(process_name="chrome.exe"))

    assert result["matched_windows"][0]["maximized"] is True
