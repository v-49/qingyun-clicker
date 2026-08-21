"""Controlled smoke test: observe one injected A in a Windows low-level hook."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from models import InputBinding
from wininput import binding_tap


WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
LLKHF_INJECTED = 0x10


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


@HOOKPROC
def callback(code: int, wparam: int, lparam: int) -> int:
    if code == HC_ACTION and wparam == WM_KEYDOWN:
        event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        observed.append((int(event.vkCode), int(event.flags)))
    return user32.CallNextHookEx(None, code, wparam, lparam)


app = QApplication(sys.argv)
hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)
if not hook:
    raise OSError(ctypes.get_last_error(), "SetWindowsHookExW failed")


def inject() -> None:
    binding_tap(InputBinding("keyboard", 0x41, 0, "A"))


def finish() -> None:
    user32.UnhookWindowsHookEx(hook)
    matched = any(vk == 0x41 and flags & LLKHF_INJECTED for vk, flags in observed)
    print(f"OBSERVED={observed!r}")
    print("SENDINPUT_OK=1" if matched else "SENDINPUT_OK=0")
    app.quit()


QTimer.singleShot(250, inject)
QTimer.singleShot(750, finish)
raise SystemExit(app.exec())
