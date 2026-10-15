"""Verify native foreground-hook delivery using an isolated hidden test window.

No physical input is retained, no synthetic input is sent to other applications.
"""
import ctypes
import json
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from recorder import NativeRecorder
from recording_models import RecordedEvent as E, restore_original
from wininput import user32

user32.NotifyWinEvent.argtypes = (wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG)
user32.NotifyWinEvent.restype = None
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Qingyun foreground hook test")
handle = int(window.winId())
errors = []
recorder = NativeRecorder(lambda: None, errors.append)
recorder._capture = lambda *args, **kwargs: False  # Do not collect physical activity.
recorder._in_app = lambda: True
finished = False


def finish():
    global finished
    try:
        assert recorder._tail.return_cut is not None, "Foreground event was not delivered"
        sequence = recorder.finish("isolated foreground test")
        assert [e.code for e in sequence.events] == [0x43, 0x43]
        assert len(restore_original(sequence).events) == 6
        assert not errors and not recorder.running and not recorder._thread.is_alive(), errors
        print(json.dumps({"ok": True, "native_foreground_hook": True, "trimmed": True,
                          "original_restorable": True, "thread_stopped": True}))
        finished = True
        app.exit(0)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "errors": errors}))
        app.exit(1)


try:
    recorder.start()
    session = recorder.session
    recorder._tail.focus(False, session, session.clock())
    for event in (E(0, "key", 0x43, True), E(0, "key", 0x43, False),
                  E(0, "key", 0xA4, True)):
        session.append(event)
    recorder._tail.observe(E(0, "key", 0x09, True), session, session.clock(), {("key", 0xA4), ("key", 0x09)})
    session.append(E(0, "key", 0x09, True))
    session.append(E(0, "key", 0x09, False))
    session.append(E(0, "key", 0xA4, False))
    user32.NotifyWinEvent(3, handle, 0, 0)
    QTimer.singleShot(250, finish)
    raise SystemExit(app.exec())
finally:
    recorder.stop()
    window.close()
