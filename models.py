"""Serializable product models shared by the UI and execution engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from recording_models import RecordedSequence


ActionMode = Literal["repeat", "hold", "burst"]
BindingKind = Literal["keyboard", "mouse"]
DEFAULT_PRESS_MS = 50


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
        if kind == "keyboard" and isinstance(code, int) and not isinstance(code, bool) and 1 <= code <= 254:
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
        if kind == "keyboard" and (not isinstance(code, int) or isinstance(code, bool) or not 1 <= code <= 254):
            return None
        if kind == "mouse" and code not in ("left", "right", "middle", "x1", "x2"):
            return None
        if not isinstance(modifiers, int) or isinstance(modifiers, bool) or not 0 <= modifiers <= 15 or not isinstance(display, str) or not isinstance(additional_raw, list) or len(additional_raw) > 31:
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
    binding: InputBinding | None
    mode: ActionMode
    interval_ms: int
    press_ms: int = DEFAULT_PRESS_MS
    trigger: InputBinding | None = None
    repeat_count: int = 3
    combo_gap_ms: int = 0
    pass_original: bool = False
    sequence: RecordedSequence | None = None

    @classmethod
    def from_dict(cls, raw: object) -> "ActionConfig | None":
        if not isinstance(raw, dict):
            return None
        binding = InputBinding.from_dict(raw.get("binding"))
        try:
            sequence = RecordedSequence.from_dict(raw["sequence"]) if raw.get("sequence") is not None else None
        except (ValueError, TypeError, KeyError):
            return None
        mode = raw.get("mode")
        interval = raw.get("interval_ms")
        press_ms = raw.get("press_ms", DEFAULT_PRESS_MS)
        trigger_raw = raw.get("trigger")
        trigger = InputBinding.from_dict(trigger_raw) if trigger_raw is not None else None
        count = raw.get("repeat_count", 3)
        gap = raw.get("combo_gap_ms", 0)
        passthrough = raw.get("pass_original", False)
        if (binding is None) == (sequence is None) or mode not in ("repeat", "hold", "burst") or not isinstance(interval, int) or isinstance(interval, bool):
            return None
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (press_ms, count, gap)) or not isinstance(passthrough, bool):
            return None
        if trigger_raw is not None and (trigger is None or trigger.additional):
            return None
        if mode == "burst" and trigger is None and sequence is None:
            return None
        return cls(binding, mode, max(0 if sequence else 1, min(99999, interval)), max(0, min(99999, press_ms)), trigger, max(1, min(999, count)), max(0, min(99999, gap)), passthrough, sequence)
