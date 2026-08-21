"""Controlled smoke test for RegisterHotKey -> Qt nativeEvent."""

from __future__ import annotations

import sys
import ctypes

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from main import ClickerShell
from models import InputBinding
from wininput import binding_tap


app = QApplication(sys.argv)
window = ClickerShell()
triggered: list[bool] = []
print(f"HOTKEY_BINDING={window.global_hotkey.display}")


def mark() -> None:
    triggered.append(True)


window.toggle_execution = mark  # type: ignore[method-assign]
window.show()


def inject() -> None:
    print(f"HOTKEY_REGISTERED={int(window._registered_hotkey)}")
    print(f"HOTKEY_HWND={window._hotkey_hwnd} IS_WINDOW={ctypes.windll.user32.IsWindow(window._hotkey_hwnd)} CURRENT={int(window.winId())}")
    print(f"HOTKEY_TOOLTIP={window.hotkey_button.toolTip()}")
    binding_tap(window.global_hotkey)


QTimer.singleShot(600, inject)


def finish() -> None:
    window._unregister_global_hotkey()
    print("HOTKEY_OK=1" if triggered else "HOTKEY_OK=0")
    app.quit()


QTimer.singleShot(1600, finish)
raise SystemExit(app.exec())
