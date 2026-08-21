"""Windows input injection, hotkey constants, and visible-window discovery."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

from models import InputAtom, InputBinding


if os.name != "nt":
    raise RuntimeError("This product currently supports Windows only.")


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B

ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsWindow.restype = wintypes.BOOL


EXTENDED_KEYS = {
    0x21, 0x22, 0x23, 0x24,  # PgUp, PgDn, End, Home
    0x25, 0x26, 0x27, 0x28,  # arrows
    0x2D, 0x2E,              # Insert, Delete
    0x5B, 0x5C,              # Windows keys
    0x6F,                    # Numpad divide
    0x90,                    # NumLock
}

MODIFIER_VKS = (
    (MOD_CONTROL, VK_CONTROL),
    (MOD_SHIFT, VK_SHIFT),
    (MOD_ALT, VK_MENU),
    (MOD_WIN, VK_LWIN),
)


def _send(items: list[INPUT]) -> None:
    if not items:
        return
    array_type = INPUT * len(items)
    sent = user32.SendInput(len(items), array_type(*items), ctypes.sizeof(INPUT))
    if sent != len(items):
        error = ctypes.get_last_error()
        raise OSError(error, "SendInput failed")


def _keyboard_input(vk: int, is_up: bool) -> INPUT:
    scan = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
    flags = KEYEVENTF_KEYUP if is_up else 0
    if scan:
        flags |= KEYEVENTF_SCANCODE
        if vk in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0))
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, 0))


def _mouse_input(button: str, is_up: bool) -> INPUT:
    flags_by_button = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
        "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
        "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
    }
    down, up, data = flags_by_button[button]
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data, up if is_up else down, 0, 0))


def _atom_input(atom: InputAtom, is_up: bool) -> INPUT:
    if atom.kind == "keyboard":
        return _keyboard_input(int(atom.code), is_up)
    return _mouse_input(str(atom.code), is_up)


def _binding_atoms(binding: InputBinding) -> tuple[InputAtom, ...]:
    return (InputAtom(binding.kind, binding.code), *binding.additional)


def binding_down(binding: InputBinding) -> None:
    items: list[INPUT] = []
    for flag, vk in MODIFIER_VKS:
        if binding.modifiers & flag:
            items.append(_keyboard_input(vk, False))
    items.extend(_atom_input(atom, False) for atom in _binding_atoms(binding))
    _send(items)


def binding_up(binding: InputBinding) -> None:
    items: list[INPUT] = []
    items.extend(_atom_input(atom, True) for atom in reversed(_binding_atoms(binding)))
    for flag, vk in reversed(MODIFIER_VKS):
        if binding.modifiers & flag:
            items.append(_keyboard_input(vk, True))
    _send(items)


def binding_tap(binding: InputBinding) -> None:
    binding_down(binding)
    binding_up(binding)


def register_hotkey(hwnd: int, hotkey_id: int, binding: InputBinding) -> None:
    if binding.kind != "keyboard" or binding.additional:
        raise ValueError("Global hotkeys must be one keyboard key plus optional modifiers")
    modifiers = binding.modifiers | MOD_NOREPEAT
    if not user32.RegisterHotKey(hwnd, hotkey_id, modifiers, int(binding.code)):
        error = ctypes.get_last_error()
        raise OSError(error, f"Global hotkey {binding.display} is unavailable")


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    user32.UnregisterHotKey(hwnd, hotkey_id)


def is_window(hwnd: int | None) -> bool:
    return bool(hwnd and user32.IsWindow(hwnd))


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int


def visible_windows(exclude_hwnd: int = 0) -> list[WindowInfo]:
    windows: list[WindowInfo] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if hwnd == exclude_hwnd or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append(WindowInfo(int(hwnd), title, int(pid.value)))
        return True

    user32.EnumWindows(callback, 0)
    return sorted(windows, key=lambda item: item.title.casefold())
