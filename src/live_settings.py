"""Read only verified Ableton Live's native Windows Options menu state."""
from __future__ import annotations

import ctypes
import platform
import time
from dataclasses import replace

from visual_capture import is_ableton_live_window, list_ableton_windows, select_ableton_window, windows_process_path

LABELS = {"delay_compensation": "Delay Compensation",
          "reduced_latency_when_monitoring": "Reduced Latency When Monitoring"}
MF_BYPOSITION = 0x400
MF_CHECKED = 0x8


def _user32():
    from ctypes import wintypes
    api = ctypes.WinDLL("user32", use_last_error=True)
    for name, args, result in (
        ("IsWindow", [wintypes.HWND], wintypes.BOOL),
        ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ("GetMenu", [wintypes.HWND], wintypes.HMENU),
        ("GetSubMenu", [wintypes.HMENU, ctypes.c_int], wintypes.HMENU),
        ("GetMenuItemCount", [wintypes.HMENU], ctypes.c_int),
        ("GetMenuStringW", [wintypes.HMENU, ctypes.c_uint, wintypes.LPWSTR, ctypes.c_int, ctypes.c_uint], ctypes.c_int),
        ("GetMenuState", [wintypes.HMENU, ctypes.c_uint, ctypes.c_uint], ctypes.c_uint),
    ):
        fn = getattr(api, name)
        fn.argtypes, fn.restype = args, result
    return api


def _identity(api, window):
    from ctypes import wintypes
    if window.platform != "Windows" or not window.pid or not api.IsWindow(window.id):
        raise ValueError("Selected Ableton window is no longer valid")
    pid = wintypes.DWORD()
    if not api.GetWindowThreadProcessId(window.id, ctypes.byref(pid)) or pid.value != window.pid:
        raise ValueError("Selected Ableton window process changed")
    process_path = windows_process_path(pid.value)
    if not process_path or not is_ableton_live_window(replace(window, process_path=process_path, owner="")):
        raise ValueError("Window process is not verified Ableton Live")
    return pid.value, process_path.casefold()


def _items(api, menu):
    count = api.GetMenuItemCount(menu)
    if not menu or not 0 <= count <= 128:
        raise ValueError("Native menu unavailable or exceeds item budget")
    result = []
    for index in range(count):
        text = ctypes.create_unicode_buffer(256)
        length = api.GetMenuStringW(menu, index, text, len(text), MF_BYPOSITION)
        if length >= len(text) - 1:
            raise ValueError("Native menu label exceeds budget")
        result.append((index, text.value.split("\t", 1)[0].replace("&", "").strip()))
    return result


def _read_options(api, hwnd):
    root = api.GetMenu(hwnd)
    options = [index for index, label in _items(api, root) if label.casefold() == "options"]
    if len(options) != 1:
        raise ValueError("English Options menu unavailable or ambiguous")
    menu = api.GetSubMenu(root, options[0])
    items = _items(api, menu)
    settings, labels = {}, {}
    for key, expected in LABELS.items():
        found = [(index, label) for index, label in items if label.casefold() == expected.casefold()]
        if len(found) != 1:
            raise ValueError("Native setting label unavailable or ambiguous: " + expected)
        index, label = found[0]
        state = api.GetMenuState(menu, index, MF_BYPOSITION)
        if state == 0xFFFFFFFF:
            raise ValueError("Native menu state unavailable")
        settings[key] = bool(state & MF_CHECKED)
        labels[key] = label
    return settings, labels


def read_live_settings(expected_pid=None):
    """No Live API calls or mutations; unknown settings remain explicit nulls."""
    unknown = dict.fromkeys(LABELS)
    evidence = {"source": "windows_native_options_menu", "method_version": 1, "observed_at_unix": time.time()}
    if platform.system() != "Windows":
        return {**unknown, "evidence": evidence, "reason": "Native settings probe supports Windows English menus only"}
    try:
        if expected_pid is None:
            window = select_ableton_window()
            pids = {w.pid for w in list_ableton_windows() if is_ableton_live_window(w)}
            if pids != {window.pid}:
                raise ValueError("Multiple or changing Live processes require an explicit bridge PID")
        else:
            if type(expected_pid) is not int or not 0 < expected_pid < 2 ** 32:
                raise ValueError("Expected bridge process PID must be a positive Windows process ID")
            evidence["expected_pid"] = expected_pid
            candidates = [w for w in list_ableton_windows() if w.pid == expected_pid and is_ableton_live_window(w)]
            if not candidates:
                raise ValueError("No verified Ableton window belongs to the bridge process")
            window = candidates[0]
        api = _user32()
        before = _identity(api, window)
        settings, labels = _read_options(api, window.id)
        if _identity(api, window) != before:
            raise ValueError("Ableton process identity changed during settings read")
        evidence.update(pid=window.pid, window_id=window.id, process_path=before[1], labels=labels,
                        observed_at_unix=time.time())
        return {**settings, "evidence": evidence}
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        return {**unknown, "evidence": evidence, "reason": str(exc)}
