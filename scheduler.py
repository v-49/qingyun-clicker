"""Native automatic actions, physical bindings, and interruptible ordered output."""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from input_monitor import MODIFIER_FLAGS, NativeInputMonitor, TriggerRouter, canonical
from input_names import atom_name, binding_display
from models import ActionConfig, InputAtom, InputBinding
from wininput import MODIFIER_VKS, binding_atoms, binding_down, binding_tap, binding_up, recorded_input, desktop_bounds
from recording_models import RecordedEvent


def output_atoms(action):
    if action.sequence:
        return tuple(dict.fromkeys(InputAtom("keyboard" if e.kind == "key" else "mouse", e.code)
                                   for e in action.sequence.events if e.key))
    if action.binding is None:
        raise ValueError("动作缺少输出")
    return binding_atoms(action.binding)


@dataclass(frozen=True)
class ActionOverlap:
    first: int
    second: int
    atoms: tuple[InputAtom, ...]
    pointer: bool = False

    @property
    def resource(self) -> str:
        names = [atom_name(a.kind, a.code) for a in self.atoms]
        if self.pointer:
            names.append("鼠标位置")
        return "、".join(names)

    @property
    def summary_resource(self) -> str:
        names = self.resource.split("、")
        return names[0] + ("等" if len(names) > 1 else "")


def pointer_use(action: ActionConfig) -> str:
    if action.sequence:
        sequence = action.sequence
        moves = ("move", "button", "wheel") if sequence.pointer_mode == "screen" else ("relative",)
        if any(e.kind in moves for e in sequence.events):
            return "write"
        return "read" if any(e.kind in ("button", "wheel") for e in sequence.events) else "none"
    return "read" if any(a.kind == "mouse" for a in output_atoms(action)) else "none"


def find_overlaps(actions: list[ActionConfig]) -> list[ActionOverlap]:
    """Overlapping rows take turns; ordinary shared modifier holds can coexist."""
    atoms = [{canonical(a) for a in output_atoms(action)} for action in actions]
    modifiers = [{InputAtom("keyboard", vk) for flag, vk in MODIFIER_VKS
                  if action.binding and action.binding.modifiers & flag} for action in actions]
    pointers = [pointer_use(action) for action in actions]
    overlaps = []
    for i, action in enumerate(actions):
        for j in range(i + 1, len(actions)):
            other = actions[j]
            shared = (atoms[i] & atoms[j]) - (modifiers[i] & modifiers[j])
            if action.mode == other.mode == "hold" and not action.sequence and not other.sequence:
                shared = set()
            pointer = "write" in (pointers[i], pointers[j]) and "none" not in (pointers[i], pointers[j])
            if shared or pointer:
                overlaps.append(ActionOverlap(i, j, tuple(sorted(shared, key=lambda a: (a.kind, str(a.code)))), pointer))
    return overlaps


def validate_actions(actions: list[ActionConfig], reserved: InputBinding | None = None, *,
                     labels: list[str] | None = None, allow_overlap: bool = True) -> None:
    seen = {}
    name = lambda i: labels[i] if labels else f"第{i + 1}行"
    reserved_atom = canonical(InputAtom(reserved.kind, reserved.code)) if reserved else None
    for i, action in enumerate(actions):
        if action.sequence:
            action.sequence.validate()
        if reserved_atom and reserved_atom in {canonical(atom) for atom in output_atoms(action)}:
            raise ValueError(f"{name(i)}的输出占用总启停键“{binding_display(reserved)}”。请更改总快捷键或输出。")
        if action.mode == "burst" and action.trigger is None and action.sequence is None:
            raise ValueError(f"{name(i)}：短连发需要设置触发键。")
        if action.trigger:
            trigger = action.trigger
            if trigger.additional:
                raise ValueError("触发键使用单键或鼠标按钮，可附加 Ctrl、Shift、Alt、Win")
            primary = canonical(InputAtom(trigger.kind, trigger.code))
            if primary == reserved_atom:
                raise ValueError(f"{name(i)}的触发键占用总启停键“{binding_display(reserved)}”。请更换触发键。")
            own_flag = MODIFIER_FLAGS.get(primary.code, 0) if primary.kind == "keyboard" else 0
            signature = (primary, trigger.modifiers & ~own_flag)
            if signature in seen:
                raise ValueError(f"{name(seen[signature])}与{name(i)}：触发键重复“{binding_display(trigger)}”。\n请更换触发键或合并输出。")
            seen[signature] = i
    for overlap in find_overlaps(actions):
        pair = (actions[overlap.first], actions[overlap.second])
        if any(a.trigger is None and a.sequence is None and a.mode == "hold" for a in pair):
            raise ValueError(f"{name(overlap.first)}与{name(overlap.second)}：{overlap.summary_resource}长按冲突。\n自动按住不释放；请改成间隔或停用一行。")
        if not allow_overlap:
            raise ValueError(f"{name(overlap.first)}与{name(overlap.second)}共用{overlap.resource}。顺序协调请使用原生输入。")


@dataclass
class _State:
    config: ActionConfig
    atoms: tuple[InputAtom, ...]
    active: bool = False
    due: float = float("inf")
    pending_at: float | None = None
    next_atom: int = 0
    held: list[InputAtom] = field(default_factory=list)
    release_at: float | None = None
    remaining: int | None = None
    cursor: int = 0
    sequence_started: float | None = None
    sequence_due: float | None = None
    sequence_timestamps: tuple[int, ...] | None = None
    sequence_duration_us: int = 0
    held_events: dict[InputAtom, RecordedEvent] = field(default_factory=dict)
    executing: bool = False


class NativeScheduler:
    def __init__(self, on_error: Callable[[str], None] | None = None, *, monitor_factory=NativeInputMonitor, on_stopped: Callable[[], None] | None = None) -> None:
        self._on_error, self._monitor_factory = on_error, monitor_factory
        self._on_stopped = on_stopped
        self._user_stop = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._monitor = None
        self._events: deque[tuple[int, bool]] = deque()
        self._hook_error: str | None = None
        self._actions: tuple[ActionConfig, ...] = ()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, actions: list[ActionConfig], *, stop_binding: InputBinding | None = None) -> None:
        if self.running:
            raise RuntimeError("Scheduler is already running")
        if not actions:
            raise ValueError("No enabled actions")
        validate_actions(actions, stop_binding)
        for action in actions:
            if action.sequence and action.sequence.pointer_mode == "screen" and any(e.kind in ("move", "button", "wheel") for e in action.sequence.events) and action.sequence.screen_bounds != desktop_bounds():
                raise ValueError("屏幕布局与录制时不同，请恢复原分辨率，或在录制编辑中选择相对移动")
        self._actions = tuple(actions)
        self._events.clear()
        self._hook_error = None
        self._user_stop = False
        self._stop.clear()
        self._wake.clear()
        if stop_binding or any(action.trigger for action in actions):
            self._monitor = self._monitor_factory(TriggerRouter(actions, self._trigger, stop_binding, self._request_stop), self._input_error)
            try:
                self._monitor.start()
            except Exception:
                self._monitor.stop()
                self._monitor = None
                raise
        self._thread = threading.Thread(target=self._run, name="clicker-scheduler", daemon=True)
        self._thread.start()

    def _trigger(self, index: int, down: bool) -> None:
        if not self._stop.is_set():
            self._events.append((index, down))
            self._wake.set()

    def _input_error(self, message: str) -> None:
        self._hook_error = message
        self._stop.set()
        self._wake.set()

    def _request_stop(self) -> None:
        self._user_stop = True
        self._stop.set()
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.5)
            if thread.is_alive():
                raise RuntimeError("输入执行线程尚未停止")
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._thread = None

    def _run(self) -> None:
        states = [_State(config, output_atoms(config)) for config in self._actions]
        conflicts = {i: set() for i in range(len(states))}
        for overlap in find_overlaps(list(self._actions)):
            conflicts[overlap.first].add(overlap.second)
            conflicts[overlap.second].add(overlap.first)
        owners: dict[InputAtom, int] = {}
        completed = False

        def acquire(state: _State, atoms: tuple[InputAtom, ...]) -> None:
            fresh = [atom for atom in atoms if not owners.get(atom)]
            for atom in atoms:
                owners[atom] = owners.get(atom, 0) + 1
                state.held.append(atom)
            if tuple(fresh) == state.atoms:
                binding_down(state.config.binding)
            else:
                for atom in fresh:
                    binding_down(InputBinding(atom.kind, atom.code))

        def release(state: _State) -> None:
            if state.config.sequence:
                for atom in reversed(tuple(state.held)):
                    if owners.get(atom, 0) <= 1:
                        event = state.held_events[atom]
                        # Cleanup releases do not move the cursor back to an old click.
                        recorded_input(replace(event, pressed=False), "relative")
                        owners.pop(atom, None)
                    else:
                        owners[atom] -= 1
                    state.held.remove(atom)
                    state.held_events.pop(atom, None)
                return
            freed = []
            for atom in state.held:
                count = owners.get(atom, 0)
                if count <= 1:
                    owners.pop(atom, None)
                    freed.append(atom)
                else:
                    owners[atom] = count - 1
            # Retain only unreleased atoms for safe retry after a key-up failure.
            state.held[:] = freed
            if tuple(freed) == state.atoms:
                binding_up(state.config.binding)
                state.held.clear()
            else:
                for atom in reversed(freed):
                    binding_up(InputBinding(atom.kind, atom.code))
                    state.held.remove(atom)

        def finish_tap(state: _State) -> None:
            state.release_at = None
            state.executing = False
            if state.config.mode == "burst" and state.remaining == 0:
                state.active = False
                state.due = float("inf")
            else:
                state.due = max(state.due, time.perf_counter() + .001)

        def complete_press(state: _State) -> None:
            state.pending_at = None
            if state.config.mode != "hold":
                if state.config.press_ms:
                    state.release_at = time.perf_counter() + state.config.press_ms / 1000
                else:
                    release(state)
                    finish_tap(state)

        def begin(state: _State, now: float) -> None:
            config = state.config
            state.executing = True
            if state.remaining is not None:
                state.remaining -= 1
            if config.sequence:
                timing = config.sequence.playback_timing
                state.sequence_timestamps = timing.timestamps
                state.sequence_duration_us = timing.duration_us
                state.cursor = 0
                state.sequence_started = now
                first = state.sequence_timestamps[0] if state.sequence_timestamps is not None else config.sequence.events[0].t_us
                state.sequence_due = now + first / 1_000_000
                state.due = float("inf")
                return
            cycle = max(config.interval_ms, config.press_ms + config.combo_gap_ms * (len(state.atoms) - 1) + 1) / 1000
            state.due = now + cycle if config.mode != "hold" else float("inf")
            if config.mode != "hold" and config.press_ms == 0 and config.combo_gap_ms == 0 and not any(owners.get(atom) for atom in state.atoms):
                binding_tap(config.binding)
                finish_tap(state)
            elif config.combo_gap_ms == 0 or len(state.atoms) == 1:
                acquire(state, state.atoms)
                complete_press(state)
            else:
                acquire(state, state.atoms[:1])
                state.next_atom = 1
                state.pending_at = time.perf_counter() + config.combo_gap_ms / 1000

        def cancel(state: _State) -> None:
            state.active = False
            state.due = float("inf")
            state.pending_at = state.release_at = None
            state.sequence_started = state.sequence_due = None
            if state.held:
                release(state)
            state.executing = False

        def advance_sequence(state: _State, now: float) -> None:
            sequence = state.config.sequence
            if not sequence or state.sequence_started is None:
                return
            processed = 0
            while state.cursor < len(sequence.events) and not self._stop.is_set() and processed < 512:
                event = sequence.events[state.cursor]
                stamp = state.sequence_timestamps[state.cursor] if state.sequence_timestamps is not None else event.t_us
                deadline = state.sequence_started + stamp / 1_000_000
                if deadline > now:
                    state.sequence_due = deadline
                    return
                if event.key:
                    atom = InputAtom("keyboard" if event.kind == "key" else "mouse", event.code)
                    if event.pressed:
                        if atom not in state.held_events:
                            state.held.append(atom)
                            state.held_events[atom] = event
                            owners[atom] = owners.get(atom, 0) + 1
                        recorded_input(event, sequence.pointer_mode)
                    else:
                        recorded_input(event, sequence.pointer_mode)
                        owners.pop(atom, None)
                        state.held.remove(atom)
                        state.held_events.pop(atom, None)
                else:
                    recorded_input(event, sequence.pointer_mode)
                state.cursor += 1
                processed += 1
            if state.cursor < len(sequence.events):
                stamp = state.sequence_timestamps[state.cursor] if state.sequence_timestamps is not None else sequence.events[state.cursor].t_us
                state.sequence_due = state.sequence_started + stamp / 1_000_000
                return
            end = state.sequence_started + state.sequence_duration_us / 1_000_000
            if now < end:
                state.sequence_due = end
                return
            release(state)
            state.sequence_started = state.sequence_due = None
            state.executing = False
            if state.config.mode == "burst" and state.remaining == 0:
                state.active = False
                state.due = float("inf")
            else:
                state.due = time.perf_counter() + max(1, state.config.interval_ms) / 1000

        try:
            now = time.perf_counter()
            for state in states:
                if self._stop.is_set():
                    break
                if state.config.trigger is None:
                    state.active = True
                    state.remaining = state.config.repeat_count if state.config.mode == "burst" else None
                    state.due = now if state.config.sequence or state.config.mode == "hold" else now + state.config.interval_ms / 1000
            while not self._stop.is_set():
                self._wake.clear()
                while self._events and not self._stop.is_set():
                    index, down = self._events.popleft()
                    state = states[index]
                    if down and not state.active:
                        state.active = True
                        state.remaining = state.config.repeat_count if state.config.mode == "burst" else None
                        state.due = time.perf_counter()
                    elif not down and state.config.mode != "burst":
                        cancel(state)
                now = time.perf_counter()
                for state in states:
                    if self._stop.is_set():
                        break
                    if state.config.sequence:
                        if state.sequence_due is not None and state.sequence_due <= now:
                            advance_sequence(state, now)
                        continue
                    if state.pending_at is not None and state.pending_at <= now:
                        acquire(state, state.atoms[state.next_atom:state.next_atom + 1])
                        state.next_atom += 1
                        if state.next_atom == len(state.atoms):
                            complete_press(state)
                        else:
                            state.pending_at = time.perf_counter() + state.config.combo_gap_ms / 1000
                    if state.release_at is not None and state.release_at <= now:
                        release(state)
                        finish_tap(state)
                # Take a whole tap/combination or recording in one turn. Never
                # interleave the internals of two actions that share resources.
                ready = [i for i, state in enumerate(states) if state.active and not state.executing and state.due <= now]
                ready.sort(key=lambda i: (states[i].config.trigger is None, states[i].due, i))
                for i in ready:
                    if self._stop.is_set():
                        break
                    if any(states[j].executing for j in conflicts[i]):
                        continue
                    # A physical request wins the next free turn. Do not let a
                    # new automatic round steal a resource it is waiting for.
                    if states[i].config.trigger is None and any(
                        states[j].config.trigger is not None and states[j].active
                        and not states[j].executing and states[j].due <= now
                        for j in conflicts[i]
                    ):
                        continue
                    begin(states[i], time.perf_counter())
                deadlines = []
                for state in states:
                    if state.config.sequence:
                        if state.sequence_due is not None:
                            deadlines.append(state.sequence_due)
                        elif state.active and state.due > now:
                            deadlines.append(state.due)
                        continue
                    deadlines.extend(value for value in (state.pending_at, state.release_at) if value is not None)
                    if state.active and not state.executing and state.due > now:
                        deadlines.append(state.due)
                if not any(state.active or state.config.trigger for state in states):
                    completed = True
                    break
                delay = max(0, min(deadlines) - time.perf_counter()) if deadlines else .05
                if not self._stop.is_set():
                    self._wake.wait(min(delay, .05))
            if self._hook_error:
                raise RuntimeError(self._hook_error)
        except Exception as exc:
            if self._on_error:
                self._on_error(str(exc))
        finally:
            for state in reversed(states):
                if state.held:
                    try:
                        release(state)
                    except Exception:
                        pass
            if self._monitor:
                self._monitor.stop()
            if (self._user_stop or completed) and self._on_stopped:
                self._on_stopped()
