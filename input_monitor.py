"""Physical trigger routing and Windows hooks on a dedicated message thread."""
from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

from models import ActionConfig, InputAtom
from wininput import MODIFIER_VKS, kernel32, user32


ALIASES = {0xA0: 0x10, 0xA1: 0x10, 0xA2: 0x11, 0xA3: 0x11, 0xA4: 0x12, 0xA5: 0x12, 0x5C: 0x5B}
MODIFIER_FLAGS = {vk: flag for flag, vk in MODIFIER_VKS}


def canonical(atom: InputAtom) -> InputAtom:
    return InputAtom(atom.kind, ALIASES.get(atom.code, atom.code)) if atom.kind == "keyboard" else atom


class TriggerRouter:
    """Return whether to suppress an original event; emit only physical edges."""
    def __init__(self, actions: list[ActionConfig], emit: Callable[[int, bool], None], stop_binding=None, on_stop=None) -> None:
        self.rules = [(i, action.trigger, action.pass_original) for i, action in enumerate(actions) if action.trigger]
        self.emit = emit
        self.down: set[InputAtom] = set()
        self.suppressed: set[InputAtom] = set()
        self.active: set[int] = set()
        self.stop_binding, self.on_stop = stop_binding, on_stop

    def seed(self, atoms: set[InputAtom]) -> None:
        self.down = set(atoms)

    def handle(self, atom: InputAtom, pressed: bool, injected: bool = False) -> bool:
        if injected:
            return False
        repeated = pressed and atom in self.down
        blocked = atom in self.suppressed
        if pressed:
            self.down.add(atom)
        else:
            self.down.discard(atom)
            self.suppressed.discard(atom)
        held = {canonical(key) for key in self.down}
        flags = sum(flag for vk, flag in MODIFIER_FLAGS.items() if InputAtom("keyboard", vk) in held)
        if self.stop_binding and pressed and not repeated:
            stop = self.stop_binding
            if canonical(atom) == canonical(InputAtom(stop.kind, stop.code)) and flags == stop.modifiers:
                self.suppressed.add(atom)
                if self.on_stop:
                    self.on_stop()
                return True
        for index, trigger, passthrough in self.rules:
            primary = canonical(InputAtom(trigger.kind, trigger.code))
            own_flag = MODIFIER_FLAGS.get(primary.code, 0) if primary.kind == "keyboard" else 0
            matches = primary in held and flags & ~own_flag == trigger.modifiers & ~own_flag
            if index in self.active and not matches:
                self.active.remove(index)
                self.emit(index, False)
            elif index not in self.active and matches and pressed and not repeated and canonical(atom) == primary:
                self.active.add(index)
                self.emit(index, True)
                if not passthrough:
                    self.suppressed.add(atom)
                    blocked = True
        return blocked


class KeyboardHookData(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.WPARAM)]


class MouseHookData(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", wintypes.WPARAM)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class NativeInputMonitor:
    def __init__(self, router: TriggerRouter, on_error: Callable[[str], None]) -> None:
        self.router, self.on_error = router, on_error
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread_id = 0
        self._error: BaseException | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="physical-input-hooks", daemon=True)
        self._thread.start()
        if not self._ready.wait(3):
            self.stop()
            raise RuntimeError("全局键鼠监听启动超时")
        if self._error:
            self.stop()
            raise RuntimeError(f"全局键鼠监听启动失败：{self._error}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

    def _run(self) -> None:
        hooks = []

        def dispatch(atom: InputAtom, pressed: bool, injected: bool) -> bool:
            if self._stop.is_set():
                return False
            try:
                return self.router.handle(atom, pressed, injected)
            except Exception as exc:
                self._stop.set()
                self.on_error(str(exc))
                return False

        @HOOKPROC
        def keyboard(code, message, pointer):
            if code == 0 and message in (0x0100, 0x0101, 0x0104, 0x0105):
                event = ctypes.cast(pointer, ctypes.POINTER(KeyboardHookData)).contents
                if dispatch(InputAtom("keyboard", int(event.vkCode)), message in (0x0100, 0x0104), bool(event.flags & 0x10)):
                    return 1
            return user32.CallNextHookEx(None, code, message, pointer)

        @HOOKPROC
        def mouse(code, message, pointer):
            if code == 0:
                event = ctypes.cast(pointer, ctypes.POINTER(MouseHookData)).contents
                buttons = {0x0201: ("left", True), 0x0202: ("left", False), 0x0204: ("right", True), 0x0205: ("right", False), 0x0207: ("middle", True), 0x0208: ("middle", False)}
                button = buttons.get(message)
                if message in (0x020B, 0x020C):
                    button = ("x1" if event.mouseData >> 16 == 1 else "x2", message == 0x020B)
                if button and dispatch(InputAtom("mouse", button[0]), button[1], bool(event.flags & 1)):
                    return 1
            return user32.CallNextHookEx(None, code, message, pointer)

        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            # Side-specific modifiers avoid mistaking one Shift release for both.
            mouse_keys = {1: "left", 2: "right", 4: "middle", 5: "x1", 6: "x2"}
            held = set()
            for vk in range(1, 255):
                if vk in (0x10, 0x11, 0x12):
                    continue
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    held.add(InputAtom("mouse", mouse_keys[vk]) if vk in mouse_keys else InputAtom("keyboard", vk))
            self.router.seed(held)
            for kind, callback in ((13, keyboard), (14, mouse)):
                hook = user32.SetWindowsHookExW(kind, callback, None, 0)
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                hooks.append(hook)
            self._ready.set()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as exc:
            self._error = exc
            if self._ready.is_set():
                self.on_error(str(exc))
        finally:
            for hook in reversed(hooks):
                user32.UnhookWindowsHookEx(hook)
            self._ready.set()
            self._thread_id = 0
