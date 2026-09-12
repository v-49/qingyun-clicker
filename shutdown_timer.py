"""Cancellable in-app countdown; no OS shutdown is queued until expiry."""

import math
import os
import subprocess
import time
from pathlib import Path


def shutdown_windows() -> None:
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "shutdown.exe"
    result = subprocess.run(
        [str(executable), "/s", "/t", "0"],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError(f"Windows 未能执行关机（错误码 {result.returncode}），请检查系统权限。")


class ShutdownCountdown:
    def __init__(self, clock=time.time, execute=shutdown_windows):
        self.clock = clock
        self.execute = execute
        self.deadline = None

    @property
    def active(self):
        return self.deadline is not None

    @property
    def remaining(self):
        return max(0, math.ceil(self.deadline - self.clock())) if self.active else 0

    def start(self, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 10080:
            raise ValueError("请输入 1 至 10080 分钟")
        self.deadline = self.clock() + minutes * 60

    def cancel(self):
        self.deadline = None

    def tick(self):
        if self.active and self.remaining == 0:
            self.cancel()  # A failed OS request must never retry automatically.
            self.execute()
