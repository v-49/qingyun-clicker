"""Windows physical-input recording, including background raw mouse movement."""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from input_monitor import HOOKPROC, KeyboardHookData, MouseHookData, canonical, MODIFIER_FLAGS
from models import InputAtom
from recording_models import RecordedEvent, RecordingSession
from recording_tail import RecordingTail, trim_recording_tail
from wininput import kernel32, user32, desktop_bounds

RECORDING_START_DELAY_SECONDS = 3

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class RAWDEVICE(ctypes.Structure):
    _fields_ = [("usagePage", wintypes.USHORT), ("usage", wintypes.USHORT), ("flags", wintypes.DWORD), ("target", wintypes.HWND)]


class RAWHEADER(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("size", wintypes.DWORD), ("device", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("flags", wintypes.USHORT), ("buttons", wintypes.ULONG), ("rawButtons", wintypes.ULONG),
                ("x", wintypes.LONG), ("y", wintypes.LONG), ("extra", wintypes.ULONG)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetWinEventHook.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
user32.UnhookWinEvent.restype = wintypes.BOOL
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASS),)
user32.RegisterClassW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.RegisterRawInputDevices.argtypes = (ctypes.POINTER(RAWDEVICE), wintypes.UINT, wintypes.UINT)
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = (wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT)
user32.GetRawInputData.restype = wintypes.UINT
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.restype = ctypes.c_ssize_t
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class NativeRecorder:
    STOP_VK = 0x78  # F9, independent of the playback hotkey.

    def __init__(self, on_stop, on_error, *, stop_binding=None, exclude_pid=None, start_delay_seconds=0):
        self.on_stop, self.on_error = on_stop, on_error
        self.stop_binding = stop_binding
        self.exclude_pid = os.getpid() if exclude_pid is None else exclude_pid
        self.session = RecordingSession(desktop_bounds())
        self._delay_ns = int(max(0, start_delay_seconds) * 1_000_000_000)
        self.session.started += self._delay_ns
        self._armed = self._delay_ns == 0
        self._ended_ns = None
        self._stop_in_app = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._thread_id = 0
        self._error = None
        self._physical = set()
        self._finished = False
        self._tail = RecordingTail()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def capture_start_seconds(self):
        return self.session.started / 1_000_000_000

    def start(self):
        self._thread = threading.Thread(target=self._run, name="fullscreen-recorder", daemon=True)
        self._thread.start()
        if not self._ready.wait(3):
            self.stop()
            raise RuntimeError("全屏录制启动超时")
        if self._error:
            self.stop()
            raise RuntimeError(f"全屏录制启动失败：{self._error}")

    def stop(self):
        if self._ended_ns is None:
            self._ended_ns = self.session.clock()
            self._stop_in_app = self._in_app()
        self._stop.set()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
            if self._thread.is_alive():
                raise RuntimeError("录制线程尚未停止")

    def finish(self, name):
        self.stop()
        sequence = self.session.finish(name, ended_ns=self._ended_ns)
        if sequence is not None:
            # Final focus check also handles a stop click before its WinEvent arrives.
            self._tail.focus(self._stop_in_app, self.session, self._ended_ns)
        return trim_recording_tail(sequence, self._tail.return_cut, self.session.started)

    def _in_app(self):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value == self.exclude_pid

    def _in_app_at(self, event):
        if event.kind not in ("button", "move", "wheel", "relative"):
            return False
        point = wintypes.POINT(event.x, event.y)
        if event.kind == "relative" and not user32.GetCursorPos(ctypes.byref(point)):
            return False
        window = user32.WindowFromPoint(point)
        pid = wintypes.DWORD()
        if window:
            user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return pid.value == self.exclude_pid

    def _request_stop(self):
        if not self._finished:
            self._finished = True
            self._ended_ns = self.session.clock()
            self._stop_in_app = self._in_app()
            self._stop.set()
            self.on_stop()
            user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0)

    def _capture(self, event, injected=False):
        if injected or self._stop.is_set():
            return False
        now = self.session.clock()
        if not self._armed and now >= self.session.started:
            # Inputs still held across the countdown are not fresh presses.
            self.session.ignored = set(self._physical)
            self._armed = True
        key = event.key
        if key:
            if event.pressed:
                self._physical.add(key)
            else:
                self._physical.discard(key)
            if event.kind == "key" and event.pressed:
                held = {canonical(InputAtom("keyboard", code)) for kind, code in self._physical if kind == "key"}
                flags = sum(flag for vk, flag in MODIFIER_FLAGS.items() if InputAtom("keyboard", vk) in held)
                own = canonical(InputAtom("keyboard", event.code))
                stop = self.stop_binding
                if event.code == self.STOP_VK or stop and own == canonical(InputAtom(stop.kind, stop.code)) and flags == stop.modifiers:
                    self._request_stop()
                    return True
        if now < self.session.started:
            return False
        in_app = self._in_app()
        if not in_app or event.kind == "key" and event.code == 0x09 and event.pressed:
            self._tail.observe(event, self.session, now, self._physical)
        self._tail.focus(in_app, self.session, now)
        if in_app or self._in_app_at(event):
            if key and event.pressed:
                self.session.ignore(key)
            elif key:
                self.session.append(event)  # Includes releases for presses begun outside.
            return False
        self.session.append(event)
        return False

    def _run(self):
        hooks, hwnd, registered, foreground_hook = [], None, False, None
        class_name = f"QingyunRecorder_{os.getpid()}_{id(self)}"
        instance = kernel32.GetModuleHandleW(None)

        def capture(event, injected=False):
            try:
                return self._capture(event, injected)
            except Exception as exc:
                self._error = exc
                self.on_error(str(exc))
                self._request_stop()
                return False

        @WINEVENTPROC
        def foreground_changed(hook, event, window, object_id, child_id, thread, stamp):
            if self._stop.is_set():
                return
            try:
                now = self.session.clock()
                if window and now >= self.session.started:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    self._tail.focus(pid.value == self.exclude_pid, self.session, now)
            except Exception as exc:
                self._error = exc
                self.on_error(str(exc))
                self._request_stop()

        @HOOKPROC
        def keyboard(code, message, pointer):
            if code == 0 and message in (0x100, 0x101, 0x104, 0x105):
                data = ctypes.cast(pointer, ctypes.POINTER(KeyboardHookData)).contents
                if capture(RecordedEvent(0, "key", int(data.vkCode), message in (0x100, 0x104),
                                         scan=int(data.scanCode), extended=bool(data.flags & 1)), bool(data.flags & 0x10)):
                    return 1
            return user32.CallNextHookEx(None, code, message, pointer)

        @HOOKPROC
        def mouse(code, message, pointer):
            if code == 0:
                data = ctypes.cast(pointer, ctypes.POINTER(MouseHookData)).contents
                buttons = {0x201: ("left", True), 0x202: ("left", False), 0x204: ("right", True),
                           0x205: ("right", False), 0x207: ("middle", True), 0x208: ("middle", False)}
                button = buttons.get(message)
                if message in (0x20B, 0x20C):
                    button = ("x1" if data.mouseData >> 16 == 1 else "x2", message == 0x20B)
                event = None
                if button:
                    event = RecordedEvent(0, "button", button[0], button[1], int(data.pt.x), int(data.pt.y))
                elif message == 0x200:
                    event = RecordedEvent(0, "move", x=int(data.pt.x), y=int(data.pt.y))
                elif message in (0x20A, 0x20E):
                    event = RecordedEvent(0, "wheel", x=int(data.pt.x), y=int(data.pt.y),
                                          delta=ctypes.c_short(data.mouseData >> 16).value, horizontal=message == 0x20E)
                if event and capture(event, bool(data.flags & 1)):
                    return 1
            return user32.CallNextHookEx(None, code, message, pointer)

        @WNDPROC
        def window_proc(window, message, wparam, lparam):
            if message == 0xFF and not self._stop.is_set() and not self._in_app():
                try:
                    size = wintypes.UINT()
                    header_size = ctypes.sizeof(RAWHEADER)
                    result = user32.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), header_size)
                    if result == 0xFFFFFFFF or size.value < header_size + ctypes.sizeof(RAWMOUSE):
                        return user32.DefWindowProcW(window, message, wparam, lparam)
                    buffer = ctypes.create_string_buffer(size.value)
                    result = user32.GetRawInputData(lparam, 0x10000003, buffer, ctypes.byref(size), header_size)
                    if result != 0xFFFFFFFF:
                        header = RAWHEADER.from_buffer(buffer)
                        if header.type == 0:
                            data = RAWMOUSE.from_buffer(buffer, header_size)
                            # Physical devices have a handle; software injection does not.
                            if header.device and not data.flags & 1 and (data.x or data.y):
                                capture(RecordedEvent(0, "relative", x=int(data.x), y=int(data.y)))
                except Exception as exc:
                    self._error = exc
                    self.on_error(str(exc))
                    self._request_stop()
            return user32.DefWindowProcW(window, message, wparam, lparam)

        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            mice = {1: "left", 2: "right", 4: "middle", 5: "x1", 6: "x2"}
            for vk in range(1, 255):
                if vk not in (0x10, 0x11, 0x12) and user32.GetAsyncKeyState(vk) & 0x8000:
                    key = ("button", mice[vk]) if vk in mice else ("key", vk)
                    self._physical.add(key)
                    self.session.ignore(key)
            wc = WNDCLASS(lpfnWndProc=window_proc, hInstance=instance, lpszClassName=class_name)
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            hwnd = user32.CreateWindowExW(0, class_name, "", 0, 0, 0, 0, 0, wintypes.HWND(-3), None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            device = RAWDEVICE(1, 2, 0x100, hwnd)  # RIDEV_INPUTSINK, leaves normal game input intact.
            if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWDEVICE)):
                raise ctypes.WinError(ctypes.get_last_error())
            for kind, callback in ((13, keyboard), (14, mouse)):
                hook = user32.SetWindowsHookExW(kind, callback, None, 0)
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                hooks.append(hook)
            foreground_hook = user32.SetWinEventHook(3, 3, None, foreground_changed, 0, 0, 0)
            if not foreground_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self.session.started = self.session.clock() + self._delay_ns
            self._ready.set()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if not result:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                user32.DispatchMessageW(ctypes.byref(msg))
        except BaseException as exc:
            self._error = exc
            if self._ready.is_set():
                self.on_error(str(exc))
                self._request_stop()
        finally:
            if foreground_hook:
                user32.UnhookWinEvent(foreground_hook)
            for hook in reversed(hooks):
                user32.UnhookWindowsHookEx(hook)
            if hwnd:
                removal = RAWDEVICE(1, 2, 1, None)
                user32.RegisterRawInputDevices(ctypes.byref(removal), 1, ctypes.sizeof(RAWDEVICE))
                user32.DestroyWindow(hwnd)
            if registered:
                user32.UnregisterClassW(class_name, instance)
            self._thread_id = 0
            self._ready.set()
