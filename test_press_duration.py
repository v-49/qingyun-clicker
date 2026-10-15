"""Press timing, independent scheduling, shared outputs, and configuration."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from ahk_engine import AhkRunner
from main import ClickerShell
from models import ActionConfig, InputBinding
from scheduler import NativeScheduler
from wininput import binding_atoms, binding_tap

APP = QApplication.instance() or QApplication([])


class PressTimingTests(unittest.TestCase):
    def test_missing_duration_defaults_to_50_and_explicit_values_are_validated(self):
        raw = {"binding": InputBinding("keyboard", 0x43).to_dict(), "mode": "repeat", "interval_ms": 150}
        self.assertEqual(ActionConfig.from_dict(raw).press_ms, 50)
        self.assertEqual(ActionConfig(InputBinding("keyboard", 0x43), "repeat", 150).press_ms, 50)
        self.assertEqual(ActionConfig.from_dict({**raw, "press_ms": 11}).press_ms, 11)
        self.assertEqual(ActionConfig.from_dict({**raw, "press_ms": -1}).press_ms, 0)
        self.assertIsNone(ActionConfig.from_dict({**raw, "press_ms": True}))

    def test_long_press_does_not_block_other_actions(self):
        key = ActionConfig(InputBinding("keyboard", 0x43, display="C"), "repeat", 1, 80)
        mouse = ActionConfig(InputBinding("mouse", "left", display="left"), "repeat", 8, 0)
        calls, released = [], threading.Event()
        def up(binding):
            calls.append(("up", binding.display, time.perf_counter()))
            if binding.display == "C": released.set()
        with patch("scheduler.binding_down", side_effect=lambda b: calls.append(("down", b.display, time.perf_counter()))), patch("scheduler.binding_up", side_effect=up), patch("scheduler.binding_tap", side_effect=lambda b: calls.append(("tap", b.display, time.perf_counter()))):
            runner = NativeScheduler()
            runner.start([key, mouse])
            try: self.assertTrue(released.wait(1))
            finally: runner.stop()
        down = next(c[2] for c in calls if c[:2] == ("down", "C"))
        up_at = next(c[2] for c in calls if c[:2] == ("up", "C"))
        self.assertGreaterEqual(up_at - down, .075)
        self.assertGreaterEqual(sum(c[:2] == ("tap", "left") and down < c[2] < up_at for c in calls), 3)

    def test_stop_interrupts_press_and_releases_once(self):
        entered, calls = threading.Event(), []
        def down(binding): calls.append("down"); entered.set()
        with patch("scheduler.binding_down", side_effect=down), patch("scheduler.binding_up", side_effect=lambda b: calls.append("up")):
            runner = NativeScheduler()
            runner.start([ActionConfig(InputBinding("keyboard", 0x43), "repeat", 1, 99999)])
            try: self.assertTrue(entered.wait(1))
            finally:
                before = time.perf_counter(); runner.stop()
            self.assertLess(time.perf_counter() - before, .3)
        self.assertEqual(calls, ["down", "up"])

    def test_same_action_never_overlaps_when_duration_exceeds_interval(self):
        calls, done = [], threading.Event()
        def down(binding): calls.append("down")
        def up(binding):
            calls.append("up")
            if calls.count("up") >= 2: done.set()
        with patch("scheduler.binding_down", side_effect=down), patch("scheduler.binding_up", side_effect=up):
            runner = NativeScheduler()
            runner.start([ActionConfig(InputBinding("keyboard", 0x43), "repeat", 1, 30)])
            try: self.assertTrue(done.wait(1))
            finally: runner.stop()
        held = 0
        for event in calls:
            held += 1 if event == "down" else -1
            self.assertIn(held, (0, 1))
        self.assertEqual(held, 0)

    def test_shared_modifier_is_not_released_while_hold_owns_it(self):
        calls, tapped = [], threading.Event()
        def down(binding): calls.extend(("down", atom.code) for atom in binding_atoms(binding))
        def up(binding):
            calls.extend(("up", atom.code) for atom in reversed(binding_atoms(binding)))
            if binding.code == 0x41: tapped.set()
        hold = ActionConfig(InputBinding("keyboard", 0x42, 2), "hold", 150)
        tap = ActionConfig(InputBinding("keyboard", 0x41, 2), "repeat", 1, 20)
        with patch("scheduler.binding_down", side_effect=down), patch("scheduler.binding_up", side_effect=up):
            runner = NativeScheduler(); runner.start([hold, tap])
            try:
                self.assertTrue(tapped.wait(1))
                self.assertNotIn(("up", 0x11), calls)
            finally: runner.stop()
        self.assertEqual(calls.count(("down", 0x11)), 1)
        self.assertEqual(calls.count(("up", 0x11)), 1)

    def test_partial_press_failure_still_releases_outputs(self):
        errors, released = [], threading.Event()
        with patch("scheduler.binding_down", side_effect=OSError("failed")), patch("scheduler.binding_up", side_effect=lambda b: released.set()):
            runner = NativeScheduler(errors.append)
            runner.start([ActionConfig(InputBinding("keyboard", 0x43), "repeat", 1, 50)])
            try: self.assertTrue(released.wait(1))
            finally: runner.stop()
        self.assertEqual(errors, ["failed"])

    def test_immediate_tap_releases_after_partial_send_failure(self):
        binding = InputBinding("keyboard", 0x43)
        with patch("wininput.binding_down", side_effect=OSError("failed")), patch("wininput.binding_up") as up:
            with self.assertRaisesRegex(OSError, "failed"):
                binding_tap(binding)
        up.assert_called_once_with(binding)

    def test_ahk_uses_nonblocking_release_timer_and_exit_cleanup(self):
        script = AhkRunner._build_script([ActionConfig(InputBinding("keyboard", 0x43), "repeat", 8, 50)], Path("stop.signal"), None)
        self.assertIn("SetTimer Release1, -50", script)
        self.assertIn("SetTimer Action1, 51", script)
        self.assertIn("if Held1", script)
        self.assertIn("Release1()", script)
        self.assertNotIn("Sleep 50", script)


class PressInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.hotkey = patch.object(ClickerShell, "_register_global_hotkey")
        self.hotkey.start()
        self.window = ClickerShell(settings=self.settings)
        self.window.groups[0].add_action()
        self.row = self.window.groups[0].actions[0]
        self.row.binding = InputBinding("keyboard", 0x43, display="C")
        self.window.show(); APP.processEvents()

    def tearDown(self):
        self.window.close(); self.window.deleteLater(); APP.processEvents()
        self.hotkey.stop(); self.temp.cleanup()

    def test_duration_is_always_visible_and_each_row_is_independent(self):
        self.assertFalse(self.row.press_field.isHidden())
        self.assertEqual(self.row.action_config().press_ms, 50)
        self.assertFalse(hasattr(self.window, "custom_press_button"))
        self.window.groups[0].add_action()
        other = self.window.groups[0].actions[1]
        self.row.press_spin.setValue(90)
        self.assertEqual(self.row.action_config().press_ms, 90)
        self.assertEqual(other.press_spin.value(), 50)
        self.row.hold_button.click()
        self.assertFalse(self.row.press_field.isEnabled())

    def test_duration_config_roundtrip_and_old_config_defaults(self):
        self.row.press_spin.setValue(80)
        saved = self.window.configuration_dict()
        self.assertNotIn("press_ms", saved)
        self.assertNotIn("custom_press_ms", saved)
        self.window.apply_configuration(saved, replace=True)
        self.assertEqual(self.window.groups[0].actions[0].action_config().press_ms, 80)
        legacy = {"version": 1, "groups": [{"name": "old", "actions": [{"binding": InputBinding("keyboard", 0x43).to_dict(), "interval_ms": 8, "mode": "repeat"}]}]}
        self.window.apply_configuration(legacy, replace=True)
        self.assertEqual(self.window.groups[0].actions[0].action_config().press_ms, 50)

    def test_numeric_controls_lock_during_execution(self):
        self.window.set_running_ui(True)
        self.assertFalse(self.row.press_field.isEnabled())
        self.window.set_running_ui(False)
        self.assertTrue(self.row.press_field.isEnabled())


if __name__ == "__main__": unittest.main()
