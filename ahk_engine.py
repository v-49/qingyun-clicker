"""Optional AutoHotkey v2 execution backend."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from models import ActionConfig, InputAtom, InputBinding


def find_ahk(configured: str = "") -> Path | None:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    for name in ("AutoHotkey64.exe", "AutoHotkey.exe"):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    candidates.extend(
        [
            Path(r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"),
            Path(r"C:\Program Files\AutoHotkey\AutoHotkey.exe"),
        ]
    )
    return next((path for path in candidates if path.is_file()), None)


def _quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _key_token(atom: InputAtom, state: str = "") -> str:
    if atom.kind == "mouse":
        names = {"left": "LButton", "right": "RButton", "middle": "MButton", "x1": "XButton1", "x2": "XButton2"}
        name = names[str(atom.code)]
    else:
        name = f"vk{int(atom.code):02X}"
    suffix = f" {state}" if state else ""
    return "{" + name + suffix + "}"


def _modifier_tokens(modifiers: int, state: str, reverse: bool = False) -> str:
    ordered = [(0x0002, "Ctrl"), (0x0004, "Shift"), (0x0001, "Alt"), (0x0008, "LWin")]
    if reverse:
        ordered.reverse()
    return "".join("{" + name + f" {state}" + "}" for flag, name in ordered if modifiers & flag)


def _binding_atoms(binding: InputBinding) -> tuple[InputAtom, ...]:
    return (InputAtom(binding.kind, binding.code), *binding.additional)


def _tap_sequence(binding: InputBinding) -> str:
    return _down_sequence(binding) + _up_sequence(binding)


def _down_sequence(binding: InputBinding) -> str:
    return _modifier_tokens(binding.modifiers, "down") + "".join(_key_token(atom, "down") for atom in _binding_atoms(binding))


def _up_sequence(binding: InputBinding) -> str:
    return "".join(_key_token(atom, "up") for atom in reversed(_binding_atoms(binding))) + _modifier_tokens(binding.modifiers, "up", True)


def _target_binding_calls(binding: InputBinding, target: str, down: bool) -> list[str]:
    calls: list[str] = []
    if down:
        modifier_down = _modifier_tokens(binding.modifiers, "down")
        if modifier_down:
            calls.append(f"try ControlSend({_quoted(modifier_down)},, {target})")
        atoms = _binding_atoms(binding)
        state = "down"
    else:
        atoms = tuple(reversed(_binding_atoms(binding)))
        state = "up"
    mouse_names = {"left": "Left", "right": "Right", "middle": "Middle", "x1": "X1", "x2": "X2"}
    for atom in atoms:
        if atom.kind == "keyboard":
            calls.append(f"try ControlSend({_quoted(_key_token(atom, state))},, {target})")
        else:
            option = "D NA" if down else "U NA"
            calls.append(f"try ControlClick(, {target}, , \"{mouse_names[str(atom.code)]}\", 1, \"{option}\")")
    if not down:
        modifier_up = _modifier_tokens(binding.modifiers, "up", True)
        if modifier_up:
            calls.append(f"try ControlSend({_quoted(modifier_up)},, {target})")
    return calls


class AhkRunner:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self._stop_file: Path | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, executable: Path, actions: list[ActionConfig], target_hwnd: int | None = None) -> None:
        if self.running:
            raise RuntimeError("AHK engine is already running")
        if not actions:
            raise ValueError("No enabled actions")

        self._temp = tempfile.TemporaryDirectory(prefix="clicker_ahk_")
        directory = Path(self._temp.name)
        script = directory / "runner.ahk"
        self._stop_file = directory / "stop.signal"
        script.write_text(self._build_script(actions, self._stop_file, target_hwnd), encoding="utf-8-sig")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [str(executable), "/ErrorStdOut", str(script)],
            cwd=str(directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        time.sleep(0.12)
        if self._process.poll() is not None:
            stdout, stderr = self._process.communicate(timeout=1)
            self._cleanup()
            detail = (stderr or stdout or "AutoHotkey failed to start").strip()
            raise RuntimeError(detail)

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None and self._stop_file is not None:
            self._stop_file.touch(exist_ok=True)
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
        self._cleanup()

    def _cleanup(self) -> None:
        self._process = None
        self._stop_file = None
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None

    @staticmethod
    def _build_script(actions: list[ActionConfig], stop_file: Path, target_hwnd: int | None) -> str:
        lines = [
            "#Requires AutoHotkey v2.0",
            "#SingleInstance Force",
            "SendMode \"Input\"",
            "SetKeyDelay -1, -1",
            f"stopFile := {_quoted(str(stop_file))}",
        ]
        target = f'"ahk_id {target_hwnd}"' if target_hwnd else ""
        release_blocks: list[list[str]] = []

        for index, action in enumerate(actions, start=1):
            binding = action.binding
            if action.mode == "repeat":
                if target_hwnd:
                    body_lines = [*_target_binding_calls(binding, target, True), *_target_binding_calls(binding, target, False)]
                else:
                    body_lines = [f"Send({_quoted(_tap_sequence(binding))})"]
                lines.extend([f"Action{index}(*) {{", *[f"    {body}" for body in body_lines], "}", f"SetTimer Action{index}, {action.interval_ms}"])
            else:
                down = _down_sequence(binding)
                up = _up_sequence(binding)
                if target_hwnd:
                    lines.extend(_target_binding_calls(binding, target, True))
                    release_blocks.append(_target_binding_calls(binding, target, False))
                else:
                    lines.append(f"Send({_quoted(down)})")
                    release_blocks.append([f"Send({_quoted(up)})"])

        release_calls = [call for block in reversed(release_blocks) for call in block]
        lines.extend(["ReleaseHeld(*) {", *[f"    {call}" for call in release_calls], "}", "OnExit ReleaseHeld"])
        lines.extend(["while !FileExist(stopFile)", "    Sleep 20", "ExitApp"])
        return "\n".join(lines) + "\n"
