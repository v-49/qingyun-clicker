"""Observe native 50 ms taps; consume test F24 events before apps receive them."""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from models import DEFAULT_PRESS_MS, ActionConfig, InputBinding
from scheduler import NativeScheduler


WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
LLKHF_INJECTED = 0x10
TEST_KEY = 0x87  # F24: test-only output, suppressed by our hook.


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32 = ctypes.windll.user32
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

observed: list[tuple[int, int]] = []
errors: list[str] = []
finished = False


@HOOKPROC
def callback(code: int, wparam: int, lparam: int) -> int:
    if code == HC_ACTION and wparam in (WM_KEYDOWN, WM_KEYUP):
        event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if event.vkCode == TEST_KEY and event.flags & LLKHF_INJECTED:
            observed.append((int(wparam), int(event.time)))
            if sum(kind == WM_KEYUP for kind, _ in observed) == 3:
                QTimer.singleShot(0, finish)
            return 1
    return user32.CallNextHookEx(None, code, wparam, lparam)


app = QApplication(sys.argv)
runner = NativeScheduler(errors.append)
hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)
if not hook:
    raise OSError(ctypes.get_last_error(), "SetWindowsHookExW failed")


def inject() -> None:
    runner.start([ActionConfig(InputBinding("keyboard", TEST_KEY), "repeat", 150)])


def finish() -> None:
    global finished
    if finished:
        return
    finished = True
    runner.stop()
    user32.UnhookWindowsHookEx(hook)
    expected = [WM_KEYDOWN, WM_KEYUP] * 3
    durations = [(observed[i + 1][1] - observed[i][1]) & 0xFFFFFFFF for i in range(0, len(observed) - 1, 2)]
    ok = not errors and [kind for kind, _ in observed] == expected and all(DEFAULT_PRESS_MS - 5 <= ms <= DEFAULT_PRESS_MS + 100 for ms in durations)
    print(json.dumps({"ok": ok, "configured_ms": DEFAULT_PRESS_MS, "observed_ms": durations, "errors": errors}))
    app.exit(0 if ok else 1)


QTimer.singleShot(250, inject)
QTimer.singleShot(2500, finish)
raise SystemExit(app.exec())
