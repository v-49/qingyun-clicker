"""Threaded native action scheduler with deterministic key release."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from models import ActionConfig
from wininput import binding_down, binding_tap, binding_up


class NativeScheduler:
    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._actions: tuple[ActionConfig, ...] = ()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, actions: list[ActionConfig]) -> None:
        if self.running:
            raise RuntimeError("Scheduler is already running")
        if not actions:
            raise ValueError("No enabled actions")
        self._actions = tuple(actions)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="clicker-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        if thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self) -> None:
        holds = [action for action in self._actions if action.mode == "hold"]
        repeats = [action for action in self._actions if action.mode == "repeat"]
        try:
            for action in holds:
                binding_down(action.binding)

            now = time.perf_counter()
            next_due = [now + action.interval_ms / 1000.0 for action in repeats]
            while not self._stop.is_set():
                if not repeats:
                    self._stop.wait(0.1)
                    continue

                now = time.perf_counter()
                nearest = min(next_due)
                if nearest > now:
                    self._stop.wait(min(nearest - now, 0.05))
                    continue

                for index, action in enumerate(repeats):
                    if next_due[index] > now:
                        continue
                    binding_tap(action.binding)
                    interval = action.interval_ms / 1000.0
                    next_due[index] += interval
                    if next_due[index] <= now - interval:
                        next_due[index] = now + interval
        except Exception as exc:  # release still happens in finally
            if self._on_error is not None:
                self._on_error(str(exc))
        finally:
            for action in reversed(holds):
                try:
                    binding_up(action.binding)
                except Exception:
                    pass
