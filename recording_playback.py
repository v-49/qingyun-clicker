"""One timing plan for the estimate, preview, and every recording playback mode.

This is not application-state detection. Only adjacent screen-movement samples
with no held input are compressed; all other recorded time remains unchanged.
"""
from dataclasses import dataclass

MOVEMENT_SPEEDS = (1.0, 2.0, 3.0, 5.0)
CONTINUOUS_MOVE_GAP_US = 100_000


@dataclass(frozen=True, slots=True)
class PlaybackTiming:
    timestamps: tuple[int, ...] | None
    duration_us: int
    saved_us: int = 0


def compile_timing(sequence):
    if sequence.movement_speed == 1 or sequence.pointer_mode != "screen":
        return PlaybackTiming(None, sequence.duration_us)
    intervals = []
    held = set()
    previous = None
    for event in sequence.events:
        if event.key:
            if event.pressed:
                held.add(event.key)
            else:
                held.discard(event.key)
            previous = None
        elif event.kind == "move":
            if held:
                previous = None
                continue
            if previous is not None:
                gap = event.t_us - previous.t_us
                if (0 < gap <= CONTINUOUS_MOVE_GAP_US
                        and (event.x, event.y) != (previous.x, previous.y)):
                    intervals.append((previous.t_us, event.t_us))
            previous = event
        elif event.kind != "relative":
            previous = None
    if not intervals:
        return PlaybackTiming(None, sequence.duration_us)

    # A monotone transformation of the whole timeline preserves event order,
    # overlapping held inputs, and every protected interval exactly.
    speed_twice = int(sequence.movement_speed * 2)
    index, completed = 0, 0
    stamps = []
    for event in sequence.events:
        while index < len(intervals) and event.t_us >= intervals[index][1]:
            start, end = intervals[index]
            completed += end - start
            index += 1
        eligible = completed
        if index < len(intervals):
            eligible += max(0, event.t_us - intervals[index][0])
        stamps.append(event.t_us - eligible + eligible * 2 // speed_twice)
    total = sum(end - start for start, end in intervals)
    saved = total - total * 2 // speed_twice
    return PlaybackTiming(tuple(stamps), sequence.duration_us - saved, saved)
