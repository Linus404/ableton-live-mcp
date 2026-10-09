import pytest

import live_settings
from visual_capture import WindowInfo


class NativeMenu:
    def __init__(self):
        self.menus = {11: ["&File", "&Options"], 22: ["Unrelated", "Reduced Latency When Monitoring", "Delay Compensation\tCtrl+D"]}
        self.states = {1: 0, 2: 8}
        self.calls = []

    def GetMenu(self, hwnd):
        self.calls.append(("GetMenu", hwnd))
        return 11

    def GetSubMenu(self, menu, index):
        assert (menu, index) == (11, 1)
        return 22

    def GetMenuItemCount(self, menu):
        return len(self.menus.get(menu, [])) if menu else -1

    def GetMenuStringW(self, menu, index, text, size, flags):
        assert flags == live_settings.MF_BYPOSITION
        text.value = self.menus[menu][index]
        return len(text.value)

    def GetMenuState(self, menu, index, flags):
        assert menu == 22 and flags == live_settings.MF_BYPOSITION
        return self.states[index]

    def IsWindow(self, hwnd):
        return True

    def GetWindowThreadProcessId(self, hwnd, pid):
        pid._obj.value = 99
        return 1


@pytest.fixture
def native(monkeypatch):
    api = NativeMenu()
    monkeypatch.setattr(live_settings.platform, "system", lambda: "Windows")
    monkeypatch.setattr(live_settings, "_user32", lambda: api)
    monkeypatch.setattr(live_settings, "select_ableton_window", lambda: WindowInfo(
        "Windows", 123, "Music", "Ableton Live", pid=99, process_path="C:/Ableton Live.exe"))
    monkeypatch.setattr(live_settings, "list_ableton_windows", lambda: [live_settings.select_ableton_window()])
    monkeypatch.setattr(live_settings, "windows_process_path", lambda pid: "C:/Ableton Live.exe")
    return api


def test_reads_dynamic_menu_positions_and_checked_bits(native):
    result = live_settings.read_live_settings()
    assert result["delay_compensation"] is True
    assert result["reduced_latency_when_monitoring"] is False
    assert result["evidence"]["pid"] == 99
    assert result["evidence"]["window_id"] == 123
    assert result["evidence"]["labels"]["delay_compensation"] == "Delay Compensation"


@pytest.mark.parametrize("mutation", [
    lambda api: api.menus[11].__setitem__(1, "Optionen"),
    lambda api: api.menus[22].append("Delay Compensation"),
    lambda api: api.states.__setitem__(2, 0xFFFFFFFF),
    lambda api: api.menus[22].clear(),
])
def test_unknown_or_ambiguous_menu_state_fails_closed(native, mutation):
    mutation(native)
    result = live_settings.read_live_settings()
    assert result["delay_compensation"] is None
    assert result["reduced_latency_when_monitoring"] is None
    assert result["reason"]


def test_rejects_reused_window_before_reading_menu(native, monkeypatch):
    monkeypatch.setattr(live_settings, "windows_process_path", lambda pid: "C:/OtherApp.exe")
    result = live_settings.read_live_settings()
    assert result["delay_compensation"] is None
    assert not native.calls


def test_revalidates_process_after_menu_read(native, monkeypatch):
    paths = iter(["C:/Ableton Live.exe", "C:/OtherApp.exe"])
    monkeypatch.setattr(live_settings, "windows_process_path", lambda pid: next(paths))
    result = live_settings.read_live_settings()
    assert native.calls == [("GetMenu", 123)]
    assert result["delay_compensation"] is None


def test_unsupported_platform_does_not_select_any_window(monkeypatch):
    monkeypatch.setattr(live_settings.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(live_settings, "select_ableton_window", lambda: pytest.fail("must not enumerate windows"))
    assert live_settings.read_live_settings()["delay_compensation"] is None


def test_expected_bridge_pid_uses_only_matching_verified_live_windows(native, monkeypatch):
    wrong = WindowInfo("Windows", 555, "Other Set", "Ableton Live", pid=88, process_path="C:/Ableton Live.exe")
    right = WindowInfo("Windows", 123, "Bridge Set", "Ableton Live", pid=99, process_path="C:/Ableton Live.exe")
    monkeypatch.setattr(live_settings, "list_ableton_windows", lambda: [wrong, right])
    monkeypatch.setattr(live_settings, "select_ableton_window", lambda: pytest.fail("must select bridge PID"))
    result = live_settings.read_live_settings(expected_pid=99)
    assert result["delay_compensation"] is True
    assert result["evidence"]["pid"] == result["evidence"]["expected_pid"] == 99
    assert native.calls == [("GetMenu", 123)]


@pytest.mark.parametrize("expected_pid", [True, 0, -1, "99", 2 ** 32])
def test_invalid_expected_pid_fails_before_window_enumeration(native, monkeypatch, expected_pid):
    monkeypatch.setattr(live_settings, "list_ableton_windows", lambda: pytest.fail("must validate PID first"))
    result = live_settings.read_live_settings(expected_pid=expected_pid)
    assert result["delay_compensation"] is None
    assert not native.calls


def test_expected_pid_cannot_target_an_unverified_process(native, monkeypatch):
    wrong = WindowInfo("Windows", 123, "Ableton Live", "OtherApp", pid=99, process_path="C:/OtherApp.exe")
    monkeypatch.setattr(live_settings, "list_ableton_windows", lambda: [wrong])
    result = live_settings.read_live_settings(expected_pid=99)
    assert result["delay_compensation"] is None
    assert not native.calls


def test_missing_bridge_pid_refuses_multiple_live_instances(native, monkeypatch):
    windows = [WindowInfo("Windows", 123, "One", "Ableton Live", pid=99, process_path="C:/Ableton Live.exe"),
               WindowInfo("Windows", 456, "Two", "Ableton Live", pid=88, process_path="C:/Ableton Live.exe")]
    monkeypatch.setattr(live_settings, "list_ableton_windows", lambda: windows)
    result = live_settings.read_live_settings()
    assert result["delay_compensation"] is None
    assert not native.calls
