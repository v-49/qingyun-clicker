"""A recording is an ordered, balanced input timeline, owned by one action row."""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

MAX_EVENTS = 200_000
MAX_TIME_US = 86_400_000_000
BUTTONS = ("left", "right", "middle", "x1", "x2")


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    t_us: int
    kind: str
    code: int | str = 0
    pressed: bool = False
    x: int = 0
    y: int = 0
    scan: int = 0
    extended: bool = False
    delta: int = 0
    horizontal: bool = False
    origin: str = "recorded"

    @property
    def key(self):
        return (self.kind, self.code) if self.kind in ("key", "button") else None

    def to_dict(self):
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("录制事件格式错误")
        event = cls(**{key: raw[key] for key in cls.__dataclass_fields__ if key in raw})
        for value in (event.t_us, event.x, event.y, event.scan, event.delta):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("录制时间和位置必须为整数")
        if not 0 <= event.t_us <= MAX_TIME_US or not 0 <= event.scan <= 65535:
            raise ValueError("录制时间或扫描码超出范围")
        if max(abs(event.x), abs(event.y), abs(event.delta)) > 2_147_483_647:
            raise ValueError("录制位置超出范围")
        if any(not isinstance(value, bool) for value in (event.pressed, event.extended, event.horizontal)):
            raise ValueError("录制事件状态错误")
        if event.origin not in ("recorded", "inserted"):
            raise ValueError("录制事件来源错误")
        if event.kind == "key":
            if not isinstance(event.code, int) or isinstance(event.code, bool) or not 1 <= event.code <= 254:
                raise ValueError("录制按键错误")
        elif event.kind == "button":
            if event.code not in BUTTONS:
                raise ValueError("录制鼠标按钮错误")
        elif event.kind not in ("move", "relative", "wheel"):
            raise ValueError("未知录制事件")
        return event


@dataclass(frozen=True, slots=True)
class RecordedSequence:
    name: str
    events: tuple[RecordedEvent, ...]
    duration_us: int
    pointer_mode: str = "screen"
    screen_bounds: tuple[int, int, int, int] = (0, 0, 1920, 1080)
    original_events: tuple[RecordedEvent, ...] | None = None
    original_duration_us: int | None = None

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise ValueError("请填写录制名称")
        if self.pointer_mode not in ("screen", "relative"):
            raise ValueError("鼠标回放方式错误")
        if not isinstance(self.duration_us, int) or isinstance(self.duration_us, bool) or not 0 <= self.duration_us <= MAX_TIME_US:
            raise ValueError("录制时长超出范围")
        if len(self.screen_bounds) != 4 or any(not isinstance(v, int) or isinstance(v, bool) or abs(v) > 1_000_000 for v in self.screen_bounds) or min(self.screen_bounds[2:]) <= 0:
            raise ValueError("录制屏幕范围错误")
        if not self.events or len(self.events) > MAX_EVENTS:
            raise ValueError("录制为空或事件过多")
        held = set()
        previous = -1
        for event in self.events:
            RecordedEvent.from_dict(event.to_dict())
            if not previous <= event.t_us <= self.duration_us:
                raise ValueError("录制事件时间顺序错误")
            previous = event.t_us
            if event.key:
                if event.pressed:
                    held.add(event.key)
                elif event.key not in held:
                    raise ValueError("录制包含未按下就松开的按键")
                else:
                    held.remove(event.key)
        if held:
            raise ValueError("录制缺少按键松开事件")
        if self.original_events is not None:
            RecordedSequence("原始录制", self.original_events, self.original_duration_us,
                             self.pointer_mode, self.screen_bounds).validate()
        elif self.original_duration_us is not None:
            raise ValueError("录制还原数据缺少原始步骤")
        return self

    def to_dict(self):
        result = {"name": self.name, "events": [event.to_dict() for event in self.events], "duration_us": self.duration_us,
                  "pointer_mode": self.pointer_mode, "screen_bounds": list(self.screen_bounds)}
        if self.original_events is not None:
            result["original"] = {"events": [event.to_dict() for event in self.original_events],
                                  "duration_us": self.original_duration_us}
        return result

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("events"), list) or len(raw["events"]) > MAX_EVENTS:
            raise ValueError("录制格式错误")
        original = raw.get("original")
        original_events, original_duration = None, None
        if original is not None:
            if not isinstance(original, dict) or not isinstance(original.get("events"), list) or len(original["events"]) > MAX_EVENTS:
                raise ValueError("录制还原数据格式错误")
            original_events = tuple(RecordedEvent.from_dict(e) for e in original["events"])
            original_duration = original.get("duration_us")
        return cls(raw.get("name", "录制"), tuple(RecordedEvent.from_dict(e) for e in raw["events"]),
                   raw.get("duration_us"), raw.get("pointer_mode", "screen"), tuple(raw.get("screen_bounds", ())),
                   original_events, original_duration).validate()

    @property
    def can_restore(self):
        return self.original_events is not None and (self.events != self.original_events or self.duration_us != self.original_duration_us)


def preserve_original(sequence):
    if sequence.original_events is not None:
        return sequence
    return replace(sequence, original_events=sequence.events, original_duration_us=sequence.duration_us)


def restore_original(sequence):
    if sequence.original_events is None:
        return sequence
    return replace(sequence, events=sequence.original_events, duration_us=sequence.original_duration_us).validate()


class RecordingSession:
    """Collect physical input only; closing adds releases to the data, never the OS."""
    def __init__(self, bounds, clock=time.perf_counter_ns):
        self.clock = clock
        self.started = clock()
        self.bounds = tuple(bounds)
        self.events = []
        self.held = {}
        self.ignored = set()

    def ignore(self, key):
        self.ignored.add(key)

    def append(self, event: RecordedEvent, *, injected=False):
        if injected:
            return
        key = event.key
        if key in self.ignored:
            if not event.pressed:
                self.ignored.discard(key)
            return
        if key and not event.pressed and key not in self.held:
            return
        if len(self.events) >= MAX_EVENTS - 512:
            raise RuntimeError("录制已达到 20 万事件，请分段录制")
        elapsed = max(0, (self.clock() - self.started) // 1000)
        if elapsed > MAX_TIME_US:
            raise RuntimeError("录制已达到 24 小时，请分段录制")
        stamp = elapsed
        event = replace(event, t_us=max(stamp, self.events[-1].t_us if self.events else 0))
        self.events.append(event)
        if key:
            if event.pressed:
                self.held.setdefault(key, event)
            else:
                self.held.pop(key)

    def finish(self, name="录制 1", *, ended_ns=None):
        end = self.clock() if ended_ns is None else ended_ns
        duration = min(MAX_TIME_US, max(0, (end - self.started) // 1000, self.events[-1].t_us if self.events else 0))
        events = list(self.events)
        events.extend(replace(event, t_us=duration, pressed=False) for event in reversed(tuple(self.held.values())))
        if not events:
            return None
        return RecordedSequence(name, tuple(events), duration, "screen", self.bounds).validate()


def paired_span(events, index):
    """Find one complete key/button press, including keyboard auto-repeat downs."""
    selected = events[index]
    if not selected.key:
        return [index]
    start = index
    while start > 0:
        preceding = next((i for i in range(start - 1, -1, -1) if events[i].key == selected.key), None)
        if preceding is None or not events[preceding].pressed:
            break
        start = preceding
    result = []
    for i in range(start, len(events)):
        if events[i].key == selected.key:
            result.append(i)
            if not events[i].pressed:
                break
    return result


def remove_events(sequence, indexes):
    sequence = preserve_original(sequence)
    removed = set(indexes)
    for index in indexes:
        removed.update(paired_span(sequence.events, index))
    return replace(sequence, events=tuple(e for i, e in enumerate(sequence.events) if i not in removed))


def insert_press(sequence, atoms, t_us, press_ms=50, count=1, interval_ms=150):
    """Insert finite taps, shifting the remaining timeline to preserve its timing."""
    sequence = preserve_original(sequence)
    duration = (max(press_ms, interval_ms) * (count - 1) + press_ms) * 1000
    inserted = []
    for cycle in range(count):
        start = t_us + cycle * max(press_ms, interval_ms) * 1000
        for atom in atoms:
            inserted.append(RecordedEvent(start, "key" if atom.kind == "keyboard" else "button", atom.code, True, origin="inserted"))
        for atom in reversed(atoms):
            inserted.append(RecordedEvent(start + press_ms * 1000, "key" if atom.kind == "keyboard" else "button", atom.code, False, origin="inserted"))
    shifted = [replace(e, t_us=e.t_us + duration) if e.t_us >= t_us else e for e in sequence.events]
    # Inserting the same held key would change its release semantics.
    held = set()
    for e in sequence.events:
        if e.t_us >= t_us:
            break
        if e.key:
            if e.pressed:
                held.add(e.key)
            else:
                held.discard(e.key)
    if any(("key" if a.kind == "keyboard" else "button", a.code) in held for a in atoms):
        raise ValueError("插入位置的同一按键尚未松开，请换一个时间位置")
    # At the insertion boundary the inserted press must precede shifted originals.
    point = next((e for e in reversed(sequence.events) if e.t_us <= t_us and e.kind in ("move", "button", "wheel")), None)
    if point is None:
        point = next((e for e in sequence.events if e.kind in ("move", "button", "wheel")), None)
    if any(e.kind == "button" for e in inserted) and point is None and sequence.pointer_mode == "screen":
        raise ValueError("录制没有鼠标位置，请先选择相对移动，或录制一个鼠标操作")
    if point:
        inserted = [replace(e, x=point.x, y=point.y) if e.kind == "button" else e for e in inserted]
    events = tuple(sorted(inserted + shifted, key=lambda e: e.t_us))
    return replace(sequence, events=events, duration_us=max(sequence.duration_us + duration, t_us + duration)).validate()
