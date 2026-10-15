"""Observe real recorded SendInput output and consume it before other apps receive it."""
import ctypes
import json
import sys
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from input_monitor import HOOKPROC, KeyboardHookData, MouseHookData
from models import ActionConfig
from recorder import NativeRecorder
from recording_models import RecordedEvent as E, RecordedSequence as S
from scheduler import NativeScheduler
from wininput import INJECTION_TAG, desktop_bounds, user32

app = QApplication(sys.argv)
observed, errors, hooks = [], [], []
runner = NativeScheduler(errors.append)
recorder = NativeRecorder(lambda: None, errors.append)
finished = False


@HOOKPROC
def keyboard(code, message, pointer):
    if code == 0:
        data = ctypes.cast(pointer, ctypes.POINTER(KeyboardHookData)).contents
        if data.dwExtraInfo == INJECTION_TAG:
            observed.append(("key", int(message), int(data.vkCode), int(data.scanCode), int(data.time)))
            return 1
    return user32.CallNextHookEx(None, code, message, pointer)


@HOOKPROC
def mouse(code, message, pointer):
    if code == 0:
        data = ctypes.cast(pointer, ctypes.POINTER(MouseHookData)).contents
        if data.dwExtraInfo == INJECTION_TAG:
            observed.append(("mouse", int(message), int(data.mouseData), int(data.pt.x), int(data.pt.y)))
            return 1
    return user32.CallNextHookEx(None, code, message, pointer)


def inject():
    bounds = desktop_bounds()
    sequence = S("OS integration", (
        E(0, "key", 0x87, True, scan=int(user32.MapVirtualKeyW(0x87, 0))),
        E(50_000, "key", 0x87, False, scan=int(user32.MapVirtualKeyW(0x87, 0))),
        E(70_000, "move", x=bounds[0] + 40, y=bounds[1] + 40),
        E(90_000, "button", "right", True, bounds[0] + 40, bounds[1] + 40),
        E(140_000, "button", "right", False, bounds[0] + 40, bounds[1] + 40),
        E(170_000, "wheel", delta=-120, x=bounds[0] + 40, y=bounds[1] + 40),
        E(200_000, "wheel", delta=120, horizontal=True, x=bounds[0] + 40, y=bounds[1] + 40),
    ), 250_000, screen_bounds=bounds)
    runner.start([ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence)])


def finish():
    global finished
    if finished:
        return
    finished = True
    runner.stop()
    recorder.stop()
    for hook in reversed(hooks):
        user32.UnhookWindowsHookEx(hook)
    keys = [entry for entry in observed if entry[0] == "key"]
    mice = [entry[1] for entry in observed if entry[0] == "mouse"]
    ok = (not errors and [e[1] for e in keys] == [0x100, 0x101]
          and 45 <= ((keys[1][4] - keys[0][4]) & 0xFFFFFFFF) <= 150
          and all(message in mice for message in (0x200, 0x204, 0x205, 0x20A, 0x20E))
          and not any(e.kind == "key" and e.code == 0x87 for e in recorder.session.events))
    result = {"ok": ok, "keys": keys, "mouse_messages": mice, "errors": errors,
              "recorder_stopped": not recorder.running, "injected_F24_excluded": True}
    print(json.dumps(result))
    app.exit(0 if ok else 1)


try:
    for kind, callback in ((13, keyboard), (14, mouse)):
        hook = user32.SetWindowsHookExW(kind, callback, None, 0)
        if not hook:
            raise ctypes.WinError(ctypes.get_last_error())
        hooks.append(hook)
    recorder.start()
    QTimer.singleShot(200, inject)
    QTimer.singleShot(800, finish)
    raise SystemExit(app.exec())
finally:
    runner.stop()
    recorder.stop()
    if not finished:
        for hook in reversed(hooks):
            user32.UnhookWindowsHookEx(hook)
