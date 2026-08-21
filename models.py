"""Serializable product models shared by the UI and execution engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ActionMode = Literal["repeat", "hold"]
BindingKind = Literal["keyboard", "mouse"]


@dataclass(frozen=True, slots=True)
class InputAtom:
    kind: BindingKind
    code: int | str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "code": self.code}

    @classmethod
    def from_dict(cls, raw: object) -> "InputAtom | None":
        if not isinstance(raw, dict):
            return None
        kind = raw.get("kind")
        code = raw.get("code")
        if kind == "keyboard" and isinstance(code, int):
            return cls(kind, code)
        if kind == "mouse" and code in ("left", "right", "middle", "x1", "x2"):
            return cls(kind, code)
        return None


@dataclass(frozen=True, slots=True)
class InputBinding:
    kind: BindingKind
    code: int | str
    modifiers: int = 0
    display: str = ""
    additional: tuple[InputAtom, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": self.code,
            "modifiers": self.modifiers,
            "display": self.display,
            "additional": [atom.to_dict() for atom in self.additional],
        }

    @classmethod
    def from_dict(cls, raw: object) -> "InputBinding | None":
        if not isinstance(raw, dict):
            return None
        kind = raw.get("kind")
        code = raw.get("code")
        modifiers = raw.get("modifiers", 0)
        display = raw.get("display", "")
        additional_raw = raw.get("additional", [])
        if kind not in ("keyboard", "mouse"):
            return None
        if kind == "keyboard" and not isinstance(code, int):
            return None
        if kind == "mouse" and code not in ("left", "right", "middle", "x1", "x2"):
            return None
        if not isinstance(modifiers, int) or not isinstance(display, str) or not isinstance(additional_raw, list):
            return None
        additional: list[InputAtom] = []
        for item in additional_raw:
            atom = InputAtom.from_dict(item)
            if atom is None:
                return None
            additional.append(atom)
        return cls(kind=kind, code=code, modifiers=modifiers, display=display, additional=tuple(additional))


@dataclass(frozen=True, slots=True)
class ActionConfig:
    binding: InputBinding
    mode: ActionMode
    interval_ms: int

    @classmethod
    def from_dict(cls, raw: object) -> "ActionConfig | None":
        if not isinstance(raw, dict):
            return None
        binding = InputBinding.from_dict(raw.get("binding"))
        mode = raw.get("mode")
        interval = raw.get("interval_ms")
        if binding is None or mode not in ("repeat", "hold") or not isinstance(interval, int):
            return None
        return cls(binding=binding, mode=mode, interval_ms=max(1, min(99999, interval)))
