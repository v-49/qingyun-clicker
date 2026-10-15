"""Real Windows hooks and SendInput; controlled trigger edges, consumed output."""
from __future__ import annotations

import json
import threading
import time

from input_monitor import NativeInputMonitor
from models import ActionConfig, InputAtom, InputBinding
from recording_models import RecordedEvent, RecordedSequence
from scheduler import NativeScheduler


class Observer:
    def __init__(self):
        self.events = []
        self.condition = threading.Condition()
    def seed(self, atoms): pass
    def handle(self, atom, down, injected=False):
        if not injected or atom not in {InputAtom("keyboard", 0x87), InputAtom("keyboard", 0x43), InputAtom("mouse", "right")}:
            return False
        with self.condition:
            self.events.append(("down" if down else "up", atom.kind, atom.code, time.perf_counter()))
            self.condition.notify_all()
        return True  # Keep all test output out of other applications.
    def wait(self, predicate):
        with self.condition:
            if not self.condition.wait_for(predicate, timeout=3):
                raise AssertionError(self.events)


def main():
    errors = []
    observer = Observer()
    consumer = NativeInputMonitor(observer, errors.append)
    runner = NativeScheduler(errors.append)
    reports = []
    try:
        consumer.start()
        f24 = InputBinding("keyboard", 0x87, display="F24")
        runner.start([ActionConfig(f24, "burst", 65, 25, f24, 3)])
        router = runner._monitor.router
        edges = []
        original_emit = router.emit
        router.emit = lambda i, down: (edges.append((i, down)), original_emit(i, down))
        assert router.handle(InputAtom("keyboard", 0x87), True)
        assert router.handle(InputAtom("keyboard", 0x87), False)
        observer.wait(lambda: sum(kind == "up" for kind, _, _, _ in observer.events) == 3)
        runner.stop()
        assert [kind for kind, _, _, _ in observer.events] == ["down", "up"] * 3
        assert edges == [(0, True), (0, False)], edges
        reports.append({"case": "same-key-three-taps", "output_events": 6, "trigger_edges": len(edges)})
        with observer.condition: observer.events.clear()
        side = InputBinding("mouse", "x1")
        combo = InputBinding("keyboard", 0x43, additional=(InputAtom("mouse", "right"),))
        runner.start([ActionConfig(combo, "hold", 100, trigger=side, combo_gap_ms=25)])
        router = runner._monitor.router
        assert router.handle(InputAtom("mouse", "x1"), True)
        observer.wait(lambda: any(kind == "down" and code == "right" for kind, _, code, _ in observer.events))
        assert router.handle(InputAtom("mouse", "x1"), False)
        observer.wait(lambda: any(kind == "up" and code == 0x43 for kind, _, code, _ in observer.events))
        runner.stop()
        assert [(kind, code) for kind, _, code, _ in observer.events] == [("down", 0x43), ("down", "right"), ("up", "right"), ("up", 0x43)]
        measured = (observer.events[1][3] - observer.events[0][3]) * 1000
        assert measured >= 23, measured
        reports.append({"case": "C-then-right-hold", "requested_gap_ms": 25, "observed_gap_ms": round(measured, 2), "release_order": ["right", "C"]})
        with observer.condition: observer.events.clear()
        sequence = RecordedSequence("arbitration", (RecordedEvent(0, "key", 0x87, True),
                                                    RecordedEvent(100_000, "key", 0x87, False)), 100_000)
        runner.start([ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence),
                      ActionConfig(f24, "burst", 1, 25, side, 1)])
        observer.wait(lambda: len(observer.events) == 1)
        router = runner._monitor.router
        assert router.handle(InputAtom("mouse", "x1"), True)
        assert router.handle(InputAtom("mouse", "x1"), False)
        observer.wait(lambda: len(observer.events) == 4)
        runner.stop()
        assert [kind for kind, _, _, _ in observer.events] == ["down", "up", "down", "up"], observer.events
        assert (observer.events[2][3] - observer.events[0][3]) >= .095, observer.events
        reports.append({"case": "recording-then-waiting-binding", "output_events": 4,
                        "observed_recording_ms": round((observer.events[1][3] - observer.events[0][3]) * 1000, 2)})
        assert not errors, errors
        print(json.dumps({"ok": True, "cases": reports, "errors": errors}))
    finally:
        runner.stop()
        consumer.stop()


if __name__ == "__main__": main()
