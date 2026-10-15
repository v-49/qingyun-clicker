"""Conservative, reversible removal of the final return to the recorder window."""
from dataclasses import dataclass, replace

from recording_models import preserve_original

ALT_KEYS = frozenset((0x12, 0xA4, 0xA5))
SHIFT_KEYS = frozenset((0x10, 0xA0, 0xA1))


@dataclass(frozen=True)
class TailCut:
    event_count: int
    at_ns: int


class RecordingTail:
    def __init__(self):
        self.in_app = None
        self.return_cut = None
        self._switch = None
        self._switch_until = 0
        self._switch_held = False

    def focus(self, in_app, session, now):
        if self.in_app == in_app:
            return
        previous = self.in_app
        self.in_app = in_app
        if in_app and previous is False:
            candidate = self._switch if self._switch_held or now <= self._switch_until else None
            self.return_cut = candidate or TailCut(len(session.events), now)
        elif not in_app:
            # Leaving our window resumes the recording, including previous switches.
            self.return_cut = None
            self._switch = None
            self._switch_until = 0
            self._switch_held = False

    def observe(self, event, session, now, physical):
        if self.in_app is not False:
            return
        alt_held = any(("key", key) in physical for key in ALT_KEYS)
        if self._switch is not None and not self._switch_held and now > self._switch_until:
            self._switch = None
        if event.kind == "key" and event.code == 0x09 and event.pressed and alt_held:
            if self._switch is None:
                # Include only adjacent, recently pressed Alt/Shift modifiers.
                # A long-held gameplay modifier or intervening mouse action stays.
                index, at = len(session.events), now
                for position in range(index - 1, -1, -1):
                    preceding = session.events[position]
                    stamp = session.started + preceding.t_us * 1000
                    if (preceding.kind != "key" or not preceding.pressed
                            or preceding.code not in ALT_KEYS | SHIFT_KEYS
                            or now - stamp > 1_000_000_000):
                        break
                    index, at = position, stamp
                self._switch = TailCut(index, at)
            self._switch_until = now + 2_000_000_000
            self._switch_held = True
        elif self._switch is not None:
            self._switch_held = alt_held
            switching_key = event.kind == "key" and event.code in ALT_KEYS | SHIFT_KEYS | {0x09}
            if switching_key:
                self._switch_until = now + 2_000_000_000
            elif not alt_held or event.kind not in ("move", "relative"):
                # Actual external input after switching invalidates the candidate.
                self._switch = None
                self._switch_until = 0
                self._switch_held = False


def trim_recording_tail(sequence, cut, started_ns):
    """Keep the exact event prefix, balance holds, and retain the untrimmed baseline."""
    if sequence is None or cut is None:
        return sequence
    if not 0 <= cut.event_count <= len(sequence.events):
        raise ValueError("录制剪切位置错误")
    prefix = sequence.events[:cut.event_count]
    if not prefix:
        return None
    duration = max(prefix[-1].t_us, min(sequence.duration_us, max(0, (cut.at_ns - started_ns) // 1000)))
    held, pointer = {}, None
    for event in prefix:
        if event.kind in ("move", "button", "wheel"):
            pointer = (event.x, event.y)
        if event.key:
            if event.pressed:
                held.setdefault(event.key, event)
            else:
                held.pop(event.key, None)
    releases = []
    for event in reversed(tuple(held.values())):
        coordinates = dict(zip(("x", "y"), pointer)) if event.kind == "button" and pointer else {}
        releases.append(replace(event, t_us=duration, pressed=False, **coordinates))
    events = prefix + tuple(releases)
    if events == sequence.events and duration == sequence.duration_us:
        return sequence
    return replace(preserve_original(sequence), events=events, duration_us=duration).validate()
