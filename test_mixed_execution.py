"""Mixing automatic, recorded and physical actions without resource races."""
import os
import ctypes
from ctypes import wintypes
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog
from main import ActionEditor, ClickerShell
from models import ActionConfig, InputAtom, InputBinding
from recording_models import RecordedEvent as E, RecordedSequence as S
from scheduler import NativeScheduler, find_overlaps, validate_actions
from wininput import binding_atoms, desktop_bounds

APP = QApplication.instance() or QApplication([])
C = InputBinding("keyboard", 67, display="C")
SIDE = InputBinding("mouse", "x1")


def sequence(code=67, duration=120_000):
    return S("录制 1", (E(0, "key", code, True), E(duration, "key", code, False)), duration,
             screen_bounds=desktop_bounds())


class Monitor:
    def __init__(self, router, on_error): self.router = router
    def start(self): pass
    def stop(self): pass


class MixedRun:
    def __init__(self, actions):
        self.actions, self.events, self.errors = actions, [], []
        self.condition = threading.Condition()
        self.stack = ExitStack()

    def emit(self, source, pressed, code):
        with self.condition:
            self.events.append((source, pressed, code, time.perf_counter()))
            self.condition.notify_all()

    def ordinary(self, binding, pressed):
        atoms = binding_atoms(binding)
        for atom in atoms if pressed else reversed(atoms):
            self.emit(binding.display or "manual", pressed, atom.code)

    def __enter__(self):
        self.stack.enter_context(patch("scheduler.recorded_input", side_effect=lambda e, m: self.emit("record", e.pressed, e.code if e.key else e.x)))
        self.stack.enter_context(patch("scheduler.binding_down", side_effect=lambda b: self.ordinary(b, True)))
        self.stack.enter_context(patch("scheduler.binding_up", side_effect=lambda b: self.ordinary(b, False)))
        self.stack.enter_context(patch("scheduler.binding_tap", side_effect=lambda b: (self.ordinary(b, True), self.ordinary(b, False))))
        self.runner = NativeScheduler(self.errors.append, monitor_factory=Monitor)
        self.runner.start(self.actions)
        return self

    def __exit__(self, *args):
        try: self.runner.stop()
        finally: self.stack.close()
        if not args[0] and self.errors:
            raise AssertionError(self.errors)

    def edge(self, down, trigger=SIDE):
        return self.runner._monitor.router.handle(InputAtom(trigger.kind, trigger.code), down)

    def count(self, source, pressed=True):
        return sum(s == source and p == pressed for s, p, _, _ in self.events)

    def wait(self, predicate):
        with self.condition:
            if not self.condition.wait_for(predicate, timeout=2):
                raise AssertionError((self.events, self.errors))


class MixedPolicyTests(unittest.TestCase):
    def test_shared_taps_and_pointer_sequences_are_soft_conflicts(self):
        actions = [ActionConfig(None, "repeat", 1, sequence=sequence()), ActionConfig(C, "repeat", 1)]
        validate_actions(actions)
        self.assertEqual(find_overlaps(actions)[0].resource, "C")
        routes = [ActionConfig(None, "burst", 0, sequence=S(str(x), (E(0, "move", x=x),), 10,
                                                       screen_bounds=desktop_bounds())) for x in (10, 20)]
        validate_actions(routes)
        self.assertEqual(find_overlaps(routes)[0].resource, "鼠标位置")

    def test_shared_modifiers_and_two_holds_can_overlay(self):
        chords = [ActionConfig(InputBinding("keyboard", code, 2), "repeat", 10) for code in (65, 66)]
        self.assertEqual(find_overlaps(chords), [])
        self.assertEqual(find_overlaps([ActionConfig(C, "hold", 10), ActionConfig(C, "hold", 10, trigger=SIDE)]), [])

    def test_permanent_hold_and_duplicate_trigger_name_specific_rows(self):
        with self.assertRaisesRegex(ValueError, "第2行与第5行：C长按冲突"):
            validate_actions([ActionConfig(C, "hold", 10), ActionConfig(None, "burst", 0, sequence=sequence())],
                             labels=["第2行", "第5行"])
        with self.assertRaisesRegex(ValueError, "第3行与第7行：触发键重复.*鼠标侧键1"):
            validate_actions([ActionConfig(C, "hold", 10, trigger=SIDE),
                              ActionConfig(InputBinding("keyboard", 65), "hold", 10, trigger=SIDE)],
                             labels=["第3行", "第7行"])

    def test_recorded_click_owns_position_but_relative_click_does_not_move(self):
        click = S("点击", (E(0, "button", "left", True), E(10, "button", "left", False)), 10,
                  screen_bounds=desktop_bounds())
        manual = ActionConfig(InputBinding("mouse", "right"), "repeat", 10)
        self.assertTrue(find_overlaps([ActionConfig(None, "burst", 0, sequence=click), manual])[0].pointer)
        from dataclasses import replace
        self.assertEqual(find_overlaps([ActionConfig(None, "burst", 0, sequence=replace(click, pointer_mode="relative")), manual]), [])

    def test_inactive_movement_source_does_not_claim_pointer(self):
        unused = S("原始位移", (E(0, "relative", x=3),), 10, pointer_mode="screen")
        other = ActionConfig(InputBinding("mouse", "left"), "hold", 10)
        self.assertEqual(find_overlaps([ActionConfig(None, "burst", 0, sequence=unused), other]), [])


class MixedSchedulingTests(unittest.TestCase):
    def test_record_interval_and_binding_are_independent(self):
        actions = [ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence(duration=200_000)),
                   ActionConfig(InputBinding("keyboard", 65, display="auto"), "repeat", 10, 0),
                   ActionConfig(InputBinding("keyboard", 66, display="bound"), "burst", 10, 5, SIDE, 1)]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record") == 1 and run.count("auto") >= 2)
            self.assertEqual(run.count("bound"), 0)
            run.edge(True); run.edge(False)
            run.wait(lambda: run.count("bound", False) == 1)
            self.assertEqual(run.count("record", False), 0)

    def test_same_key_bound_request_wins_next_recording_turn(self):
        actions = [ActionConfig(None, "repeat", 0, sequence=sequence()),
                   ActionConfig(InputBinding("keyboard", 67, display="bound"), "burst", 1, 10, SIDE, 1)]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record") == 1)
            run.edge(True); run.edge(False)
            run.wait(lambda: run.count("record") == 2)
            self.assertEqual([(s, p) for s, p, _, _ in run.events[:5]],
                             [("record", True), ("record", False), ("bound", True), ("bound", False), ("record", True)])

    def test_two_automatic_taps_take_turns_and_both_progress(self):
        actions = [ActionConfig(InputBinding("keyboard", 67, display=name), "repeat", 1, 10) for name in ("one", "two")]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("one", False) >= 3 and run.count("two", False) >= 3)
        pending = None
        for source, pressed, _, _ in run.events:
            if pressed:
                self.assertIsNone(pending)
                pending = source
            else:
                self.assertEqual(pending, source)
                pending = None
        self.assertIsNone(pending)

    def test_pointer_paths_take_whole_turns_while_keyboard_runs(self):
        actions = [ActionConfig(None, "burst", 0, repeat_count=1,
                                sequence=S(str(x), (E(0, "move", x=x), E(80_000, "move", x=x+1)), 80_000,
                                           screen_bounds=desktop_bounds())) for x in (10, 20)]
        actions.append(ActionConfig(InputBinding("keyboard", 65, display="auto"), "repeat", 10, 0))
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record", False) == 4)
            self.assertGreater(run.count("auto"), 3)
            self.assertEqual([code for s, _, code, _ in run.events if s == "record"], [10, 11, 20, 21])
            after_recordings = run.count("auto")
            run.wait(lambda: run.count("auto") > after_recordings)
            self.assertTrue(run.runner.running)

    def test_queued_hold_is_cancelled_if_physical_key_released(self):
        actions = [ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence()),
                   ActionConfig(InputBinding("keyboard", 67, display="bound"), "hold", 1, trigger=SIDE)]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record") == 1)
            run.edge(True); run.edge(False)
            run.wait(lambda: run.count("record", False) == 1)
            self.assertEqual(run.count("bound"), 0)

    def test_following_hold_blocks_auto_until_release_then_resumes(self):
        actions = [ActionConfig(InputBinding("keyboard", 67, display="auto"), "repeat", 10, 5),
                   ActionConfig(InputBinding("keyboard", 67, display="bound"), "hold", 10, trigger=SIDE)]
        with MixedRun(actions) as run:
            run.edge(True)
            run.wait(lambda: run.count("bound") == 1)
            count = run.count("auto")
            time.sleep(.035)
            self.assertEqual(run.count("auto"), count)
            run.edge(False)
            run.wait(lambda: run.count("auto") > count)
            self.assertEqual(run.count("bound", False), 1)

    def test_total_stop_discards_waiting_burst_and_releases_current_recording(self):
        actions = [ActionConfig(None, "repeat", 0, sequence=sequence(duration=1_000_000)),
                   ActionConfig(InputBinding("keyboard", 67, display="bound"), "burst", 1, 10, SIDE, 3)]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record") == 1)
            run.edge(True); run.edge(False)
            run.runner.stop()
            self.assertEqual(run.count("bound"), 0)
            self.assertEqual(run.count("record", False), 1)

    def test_waiting_single_press_does_not_accumulate_an_unbounded_queue(self):
        actions = [ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence()),
                   ActionConfig(InputBinding("keyboard", 67, display="bound"), "burst", 1, 5, SIDE, 1)]
        with MixedRun(actions) as run:
            run.wait(lambda: run.count("record") == 1)
            for _ in range(4):
                run.edge(True); run.edge(False)
            run.wait(lambda: run.count("bound", False) == 1)
            time.sleep(.025)
            self.assertEqual(run.count("bound"), 1)


class MixedUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registration = patch.object(ClickerShell, "_register_global_hotkey")
        self.registration.start()
        self.window = ClickerShell(QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat))
        self.group = self.window.active_group

    def tearDown(self):
        self.window.close(); self.window.deleteLater(); APP.processEvents()
        self.registration.stop(); self.temp.cleanup()

    def add(self, config):
        self.group.add_action()
        row = self.group.actions[-1]
        row.apply_action_config(config)
        return row

    def test_soft_overlap_editor_saves_and_explains_order_in_existing_slot(self):
        self.add(ActionConfig(C, "repeat", 150))
        row = self.add(ActionConfig(C, "repeat", 150))
        editor = ActionEditor(row)
        editor.set_trigger(SIDE)
        editor.mode.setCurrentIndex(editor.mode.findData("single"))
        before = editor.size()
        self.assertIn("与第1行共用C，按先后执行", editor.preview.text())
        editor.accept()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(editor.size(), before)
        self.assertIsNone(row.trigger)  # The parent submits only on accepted result.

    def test_binding_a_recording_disables_automatic_mode_and_unbinding_restores_it(self):
        row = self.add(ActionConfig(None, "repeat", 300, sequence=sequence()))
        row.apply_action_config(ActionConfig(None, "burst", 300, trigger=SIDE, repeat_count=1, sequence=row.sequence))
        self.assertFalse(row.repeat_button.isEnabled())
        self.assertTrue(row.state_button.isEnabled())
        editor = ActionEditor(row)
        editor.clear_trigger(); editor.accept()
        row.apply_action_config(editor.config)
        self.assertEqual(row.execution_mode, "repeat")
        self.assertIsNone(row.trigger)
        self.assertTrue(row.repeat_button.isEnabled())

    def test_start_collects_only_enabled_rows_of_selected_group(self):
        first = self.add(ActionConfig(C, "repeat", 10))
        disabled = self.add(ActionConfig(C, "hold", 10))
        disabled.state_button.setChecked(False)
        other_group = self.window.create_group("B", activate=False)
        other_group.add_action()
        other_group.actions[0].apply_action_config(ActionConfig(C, "hold", 10))
        with patch.object(self.window.native_scheduler, "start") as start:
            self.window.start_execution()
            self.assertEqual(start.call_args.args[0], [first.action_config()])
            self.assertTrue(self.window._running)
        self.window.stop_execution()

    def test_conflict_row_numbers_include_disabled_and_unconfigured_rows(self):
        self.group.add_action()
        self.add(ActionConfig(C, "hold", 10))
        row = self.add(ActionConfig(C, "repeat", 10))
        editor = ActionEditor(row)
        editor.set_trigger(SIDE)
        editor.mode.setCurrentIndex(editor.mode.findData("single"))
        editor.accept()
        self.assertIn("第2行与第3行：C长按冲突", editor.preview.text())
        self.assertNotEqual(editor.result(), QDialog.DialogCode.Accepted)
        editor.reject()

    def test_delayed_stop_hotkey_never_starts_a_new_execution(self):
        message = wintypes.MSG()
        message.message, message.wParam, message.time = self.window.WM_HOTKEY, self.window.HOTKEY_ID, 99
        self.window._last_control_stop_tick = 100
        with patch.object(self.window, "start_execution") as start:
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            APP.processEvents()
            start.assert_not_called()
            message.time = 101
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            APP.processEvents()
            start.assert_called_once()

    def test_hotkey_timestamp_handles_windows_tick_wrap(self):
        message = wintypes.MSG()
        message.message, message.wParam, message.time = self.window.WM_HOTKEY, self.window.HOTKEY_ID, 2
        self.window._last_control_stop_tick = 0xFFFFFFFE
        with patch.object(self.window, "start_execution") as start:
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            APP.processEvents()
            start.assert_called_once()


if __name__ == "__main__": unittest.main()
