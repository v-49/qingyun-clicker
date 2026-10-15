"""Input names shared by the editor and execution diagnostics."""
from models import InputAtom, InputBinding

VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space",
    0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2D: "Insert", 0x2E: "Delete",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt", 0x5B: "Win",
    0xA0: "左 Shift", 0xA1: "右 Shift", 0xA2: "左 Ctrl", 0xA3: "右 Ctrl",
    0xA4: "左 Alt", 0xA5: "右 Alt", 0x5C: "右 Win",
}
MOUSE_NAMES = {"left": "鼠标左键", "right": "鼠标右键", "middle": "鼠标中键", "x1": "鼠标侧键1", "x2": "鼠标侧键2"}


def atom_name(kind: str, code: int | str) -> str:
    if kind == "mouse":
        return MOUSE_NAMES[str(code)]
    vk = int(code)
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return VK_NAMES.get(vk, f"VK {vk:02X}")


def binding_name(kind: str, code: int | str, modifiers: int = 0,
                 additional: tuple[InputAtom, ...] = ()) -> str:
    prefixes = [name for flag, name in ((2, "Ctrl"), (4, "Shift"), (1, "Alt"), (8, "Win")) if modifiers & flag]
    return "+".join([*prefixes, atom_name(kind, code), *(atom_name(a.kind, a.code) for a in additional)])


def binding_display(binding: InputBinding) -> str:
    return binding.display or binding_name(binding.kind, binding.code, binding.modifiers, binding.additional)
