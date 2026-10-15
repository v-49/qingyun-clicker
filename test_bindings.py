"""Physical edges, finite bursts, ordered holds, cancellation and saved bindings."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from ahk_engine import AhkRunner
from input_monitor import TriggerRouter
from main import ActionEditor, ClickerShell
from models import ActionConfig, InputAtom, InputBinding
from scheduler import NativeScheduler, validate_actions
from wininput import binding_atoms

APP = QApplication.instance() or QApplication([])
X = InputBinding("keyboard", 0x58, display="X")
C = InputBinding("keyboard", 0x43, display="C")
SIDE = InputBinding("mouse", "x1", display="侧键1")
COMBO = InputBinding("keyboard", 0x43, display="C+右键", additional=(InputAtom("mouse", "right"),))


class FakeMonitor:
    def __init__(self, router, on_error):
        self.router, self.on_error, self.stopped = router, on_error, False
    def start(self): pass
    def stop(self): self.stopped = True


class Harness:
    def __init__(self, actions, stop_binding=None):
        self.events, self.errors = [], []
        self.condition = threading.Condition()
        self.patches = []
        def record(kind, binding):
            atoms = binding_atoms(binding)
            with self.condition:
                self.events.extend((kind, atom, time.perf_counter()) for atom in (reversed(atoms) if kind == "up" else atoms))
                self.condition.notify_all()
        for name, function in (("binding_down", lambda b: record("down", b)), ("binding_up", lambda b: record("up", b)), ("binding_tap", lambda b: (record("down", b), record("up", b)))):
            p = patch("scheduler." + name, side_effect=function)
            p.start(); self.patches.append(p)
        self.runner = NativeScheduler(self.errors.append, monitor_factory=FakeMonitor)
        self.runner.start(actions, stop_binding=stop_binding)
        self.monitor = self.runner._monitor
    def edge(self, binding, down, injected=False):
        return self.monitor.router.handle(InputAtom(binding.kind, binding.code), down, injected)
    def count(self, kind, code):
        return sum(event == kind and atom.code == code for event, atom, _ in self.events)
    def wait(self, condition):
        with self.condition:
            if not self.condition.wait_for(condition, timeout=1.5):
                raise AssertionError((self.events, self.errors))
    def close(self):
        try: self.runner.stop()
        finally:
            for p in reversed(self.patches): p.stop()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class RouterTests(unittest.TestCase):
    def test_injected_output_cannot_trigger_or_release_physical_binding(self):
        edges = []
        router = TriggerRouter([ActionConfig(X, "burst", 80, trigger=X)], lambda i, down: edges.append((i, down)))
        atom = InputAtom("keyboard", 0x58)
        self.assertFalse(router.handle(atom, True, True))
        self.assertTrue(router.handle(atom, True))
        self.assertTrue(router.handle(atom, True))
        self.assertFalse(router.handle(atom, False, True))
        self.assertEqual(edges, [(0, True)])
        self.assertTrue(router.handle(atom, False))
        self.assertEqual(edges, [(0, True), (0, False)])

    def test_modifier_chords_match_exactly_and_suppressed_up_stays_paired(self):
        edges = []
        ctrl_x = InputBinding("keyboard", 0x58, 2)
        router = TriggerRouter([ActionConfig(C, "hold", 100, trigger=X), ActionConfig(InputBinding("keyboard", 0x42), "hold", 100, trigger=ctrl_x)], lambda i, down: edges.append((i, down)))
        router.handle(InputAtom("keyboard", 0xA2), True)
        self.assertTrue(router.handle(InputAtom("keyboard", 0x58), True))
        router.handle(InputAtom("keyboard", 0xA3), True)
        router.handle(InputAtom("keyboard", 0xA2), False)
        self.assertEqual(edges, [(1, True)])
        router.handle(InputAtom("keyboard", 0xA3), False)
        self.assertEqual(edges, [(1, True), (1, False)])
        self.assertTrue(router.handle(InputAtom("keyboard", 0x58), False))

    def test_passthrough_and_preheld_key_do_not_create_extra_press(self):
        edges = []
        router = TriggerRouter([ActionConfig(C, "hold", 100, trigger=X, pass_original=True)], lambda i, down: edges.append(down))
        atom = InputAtom("keyboard", 0x58)
        router.seed({atom})
        self.assertFalse(router.handle(atom, True))
        self.assertFalse(router.handle(atom, False))
        self.assertEqual(edges, [])
        self.assertFalse(router.handle(atom, True))
        self.assertFalse(router.handle(atom, False))
        self.assertEqual(edges, [True, False])


class BindingExecutionTests(unittest.TestCase):
    def test_physical_stop_key_works_while_output_ctrl_is_held(self):
        stopped = threading.Event()
        ctrl_b = InputBinding("keyboard", 0x42, 2)
        f8 = InputBinding("keyboard", 0x77)
        with Harness([ActionConfig(ctrl_b, "hold", 100)], stop_binding=f8) as h:
            h.runner._on_stopped = stopped.set
            h.wait(lambda: h.count("down", 0x42) == 1)
            h.monitor.router.handle(InputAtom("keyboard", 0xA2), True, injected=True)
            self.assertTrue(h.edge(f8, True))
            self.assertTrue(stopped.wait(1.5))
            self.assertEqual(h.count("up", 0x11), 1)
            self.assertEqual(h.count("up", 0x42), 1)
            self.assertTrue(h.monitor.stopped)

    def test_hook_failure_stops_output_and_releases_hold(self):
        with Harness([ActionConfig(C, "hold", 100, trigger=X)]) as h:
            h.edge(X, True)
            h.wait(lambda: h.count("down", 0x43) == 1)
            h.monitor.on_error("hook failed")
            h.wait(lambda: h.count("up", 0x43) == 1)
        self.assertEqual(h.errors, ["hook failed"])
        self.assertTrue(h.monitor.stopped)

    def test_failed_key_up_retry_keeps_shared_modifier_accounting(self):
        import scheduler
        held = ActionConfig(InputBinding("keyboard", 0x42, 2), "hold", 100)
        repeat = ActionConfig(InputBinding("keyboard", 0x41, 2), "repeat", 50, 5)
        with Harness([held, repeat]) as h:
            original_up = scheduler.binding_up
            failures = []
            def up(binding):
                if binding.code == 0x41 and not failures:
                    failures.append(True)
                    raise OSError("key-up failed")
                original_up(binding)
            with patch("scheduler.binding_up", side_effect=up):
                h.wait(lambda: h.count("up", 0x11) == 1)
        self.assertEqual(h.errors, ["key-up failed"])
        self.assertEqual(h.count("down", 0x11), 1)
        self.assertEqual(h.count("up", 0x11), 1)
        self.assertEqual(h.count("up", 0x41), 1)

    def test_monitor_start_failure_never_starts_execution(self):
        class BrokenMonitor(FakeMonitor):
            def start(self): raise OSError("hook unavailable")
        with patch("scheduler.binding_down") as down:
            runner = NativeScheduler(monitor_factory=BrokenMonitor)
            with self.assertRaisesRegex(OSError, "hook unavailable"):
                runner.start([ActionConfig(C, "hold", 100, trigger=X)])
            self.assertFalse(runner.running)
            self.assertIsNone(runner._monitor)
            down.assert_not_called()

    def test_short_press_finishes_three_taps_and_busy_repress_is_ignored(self):
        with Harness([ActionConfig(X, "burst", 70, 15, X, 3)]) as h:
            h.edge(X, True)
            h.wait(lambda: h.count("down", 0x58) == 1)
            h.edge(X, False); h.edge(X, True); h.edge(X, False)
            h.wait(lambda: h.count("up", 0x58) == 3)
            self.assertEqual(h.count("down", 0x58), 3)
            h.edge(X, True)
            h.wait(lambda: h.count("up", 0x58) == 6)
            h.edge(X, False)
            self.assertEqual(h.errors, [])

    def test_held_trigger_autorepeat_does_not_restart_finished_burst(self):
        with Harness([ActionConfig(X, "burst", 25, 5, X, 2)]) as h:
            h.edge(X, True)
            h.wait(lambda: h.count("up", 0x58) == 2)
            for _ in range(10): h.edge(X, True)
            h.edge(X, False)
        self.assertEqual(h.count("down", 0x58), 2)

    def test_release_cancels_held_repeat_without_waiting_for_press_duration(self):
        with Harness([ActionConfig(C, "repeat", 10, 99999, X)]) as h:
            h.edge(X, True)
            h.wait(lambda: h.count("down", 0x43) == 1)
            before = time.perf_counter(); h.edge(X, False)
            h.wait(lambda: h.count("up", 0x43) == 1)
            self.assertLess(time.perf_counter() - before, .3)
        self.assertEqual(h.count("down", 0x43), 1)

    def test_ordered_combo_hold_releases_in_reverse(self):
        with Harness([ActionConfig(COMBO, "hold", 100, 50, SIDE, combo_gap_ms=25)]) as h:
            h.edge(SIDE, True)
            h.wait(lambda: h.count("down", "right") == 1)
            h.edge(SIDE, False)
            h.wait(lambda: h.count("up", 0x43) == 1)
        self.assertEqual([(kind, atom.code) for kind, atom, _ in h.events], [("down", 0x43), ("down", "right"), ("up", "right"), ("up", 0x43)])
        self.assertGreaterEqual(h.events[1][2] - h.events[0][2], .022)

    def test_release_during_combo_wait_never_sends_late_mouse_down(self):
        with Harness([ActionConfig(COMBO, "hold", 100, 50, SIDE, combo_gap_ms=99999)]) as h:
            h.edge(SIDE, True)
            h.wait(lambda: h.count("down", 0x43) == 1)
            h.edge(SIDE, False)
            h.wait(lambda: h.count("up", 0x43) == 1)
        self.assertEqual(h.count("down", "right"), 0)

    def test_total_stop_releases_combo_and_stops_monitor(self):
        with Harness([ActionConfig(COMBO, "hold", 100, 50, SIDE, combo_gap_ms=10)]) as h:
            h.edge(SIDE, True)
            h.wait(lambda: h.count("down", "right") == 1)
            h.runner.stop()
            self.assertTrue(h.monitor.stopped)
        self.assertEqual([(kind, atom.code) for kind, atom, _ in h.events][-2:], [("up", "right"), ("up", 0x43)])

    def test_waiting_binding_does_not_block_automatic_row(self):
        with Harness([ActionConfig(C, "repeat", 20, 5), ActionConfig(InputBinding("keyboard", 0x42), "hold", 100, trigger=X)]) as h:
            h.wait(lambda: h.count("down", 0x43) >= 3)
            self.assertEqual(h.count("down", 0x42), 0)
            h.edge(X, True)
            h.wait(lambda: h.count("down", 0x42) == 1)

    def test_two_hold_owners_release_only_after_both_triggers_end(self):
        with Harness([ActionConfig(C, "hold", 100, trigger=X), ActionConfig(C, "hold", 100, trigger=SIDE)]) as h:
            h.edge(X, True); h.edge(SIDE, True)
            h.wait(lambda: h.count("down", 0x43) == 1)
            h.edge(X, False)
            h.edge(SIDE, False)
            h.wait(lambda: h.count("up", 0x43) == 1)
        self.assertEqual(h.count("down", 0x43), 1)

    def test_duplicates_reserved_hotkey_and_permanent_hold_conflicts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "触发键重复"):
            validate_actions([ActionConfig(C, "hold", 100, trigger=X), ActionConfig(InputBinding("mouse", "right"), "hold", 100, trigger=X)])
        with self.assertRaisesRegex(ValueError, "总启停"):
            validate_actions([ActionConfig(C, "hold", 100, trigger=X)], X)
        with self.assertRaisesRegex(ValueError, "冲突"):
            validate_actions([ActionConfig(C, "hold", 100), ActionConfig(C, "repeat", 10, trigger=SIDE)])
        validate_actions([ActionConfig(C, "hold", 100, trigger=X), ActionConfig(C, "repeat", 10, trigger=SIDE)])
        with self.assertRaisesRegex(ValueError, "原生"):
            AhkRunner._build_script([ActionConfig(C, "hold", 100, trigger=X)], Path("stop"), None)


class BindingInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registration = patch.object(ClickerShell, "_register_global_hotkey")
        self.registration.start()
        self.window = ClickerShell(QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat))
        self.window.groups[0].add_action()
        self.row = self.window.groups[0].actions[0]
    def tearDown(self):
        self.window.close(); self.window.deleteLater(); APP.processEvents()
        self.registration.stop(); self.temp.cleanup()
    def test_bound_burst_roundtrip_and_hold_mode_transition(self):
        self.row.apply_action_config(ActionConfig(COMBO, "hold", 80, trigger=SIDE, combo_gap_ms=20))
        self.row.apply_action_config(ActionConfig(X, "burst", 70, 50, X, 4))
        saved = self.window.configuration_dict()
        self.window.apply_configuration(saved, replace=True)
        row = self.window.groups[0].actions[0]
        self.assertEqual(row.action_config(), ActionConfig(X, "burst", 70, 50, X, 4))
        self.assertEqual(row.record_button.text(), "X → X ×4 · 短发")
        self.assertEqual(row.repeat_button.text(), "间隔")
        self.assertTrue(row.state_button.isEnabled())
        self.assertFalse(row.repeat_button.isEnabled())
        self.assertFalse(row.hold_button.isEnabled())
    def test_cancelled_editor_leaves_original_configuration_intact(self):
        self.row.apply_action_config(ActionConfig(C, "repeat", 150))
        before = self.row.to_dict()
        editor = ActionEditor(self.row)
        editor.trigger = SIDE; editor.count.setValue(8); editor.reject()
        self.assertEqual(self.row.to_dict(), before)
    def test_switching_group_stops_old_group_without_starting_new(self):
        old_group = self.window.active_group
        new_group = self.window.create_group("B", activate=False)
        self.window._running = True
        self.window.set_running_ui(True)
        self.assertTrue(new_group.name_button.isEnabled())
        with patch.object(self.window.native_scheduler, "stop") as stop, patch.object(self.window.native_scheduler, "start") as start:
            self.window.activate_group(new_group)
            stop.assert_called_once()
            start.assert_not_called()
        self.assertIsNot(self.window.active_group, old_group)
        self.assertFalse(self.window._running)
    def test_malformed_bound_config_never_falls_back_to_auto_execution(self):
        self.row.load_dict({"binding": C.to_dict(), "trigger": {"kind": "keyboard", "code": True}, "mode": "burst"})
        self.assertIsNone(self.row.action_config())

    def test_bound_row_keeps_inline_enable_and_disables_automatic_modes(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150, trigger=SIDE))
        for widget in (self.row.repeat_button, self.row.hold_button):
            self.assertFalse(widget.isEnabled())
        self.assertTrue(self.row.execution_control.isEnabled())
        self.assertTrue(self.row.state_button.isEnabled())
        self.assertEqual(self.row.action_config().mode, "hold")
        self.assertTrue(self.row.settings_button.isEnabled())
        self.assertFalse(self.row.interval_field.isEnabled())
        self.assertFalse(self.row.press_field.isEnabled())
        self.row.apply_action_config(ActionConfig(C, "repeat", 150, trigger=SIDE))
        self.assertTrue(self.row.interval_field.isEnabled())
        self.assertTrue(self.row.press_field.isEnabled())
        self.window.set_running_ui(True)
        self.assertFalse(self.row.settings_button.isEnabled())
        self.window.set_running_ui(False)
        self.assertTrue(self.row.state_button.isEnabled())
        self.assertTrue(self.row.settings_button.isEnabled())

    def test_inline_enable_can_disable_and_restore_bound_row_after_roundtrip(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150, trigger=SIDE))
        self.row.state_button.click()
        self.assertIsNone(self.row.action_config())
        self.assertEqual(self.row.state_button.text(), "停")
        self.assertTrue(self.row.settings_button.isEnabled())
        self.assertEqual(self.row.record_button.text(), "侧键1 → C · 跟随")
        self.assertFalse(self.row.record_button.isEnabled())
        self.assertFalse(self.row.interval_field.isEnabled())
        self.assertFalse(self.row.press_field.isEnabled())
        saved = self.window.configuration_dict()
        self.window.apply_configuration(saved, replace=True)
        row = self.window.groups[0].actions[0]
        self.assertIsNone(row.action_config())
        self.assertTrue(row.state_button.isEnabled())
        self.assertFalse(row.record_button.isEnabled())
        row.state_button.click()
        self.assertEqual(row.state_button.text(), "启")
        self.assertEqual(row.action_config().trigger, SIDE)
        self.assertTrue(row.state_button.isEnabled())
        self.assertTrue(row.record_button.isEnabled())

    def test_editing_binding_does_not_reenable_a_disabled_row(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150, trigger=SIDE))
        self.row.state_button.click()
        editor = ActionEditor(self.row)
        self.assertFalse(hasattr(editor, "enabled"))
        editor.set_output(X)
        editor.accept()
        self.row.apply_action_config(editor.config)
        self.assertFalse(self.row.state_button.isChecked())
        self.assertIsNone(self.row.action_config())
        self.assertEqual(self.row.binding, X)

    def test_global_start_uses_only_inline_enabled_bindings(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150, trigger=SIDE))
        self.window.groups[0].add_action()
        other = self.window.groups[0].actions[-1]
        other.apply_action_config(ActionConfig(X, "burst", 70, trigger=X))
        self.row.state_button.click()
        with patch.object(self.window.native_scheduler, "start") as start, patch.object(self.window.native_scheduler, "stop"):
            self.window.start_execution()
            self.assertEqual(start.call_args.args[0], [other.action_config()])
            self.window.stop_execution()
            self.row.state_button.click()
            self.window.start_execution()
            self.assertEqual(start.call_args.args[0], [self.row.action_config(), other.action_config()])
            self.window.stop_execution()

    def test_unbind_restores_original_automatic_mode_without_starting_execution(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150))
        self.row.apply_action_config(ActionConfig(C, "burst", 150, trigger=SIDE))
        saved = self.window.configuration_dict()
        self.window.apply_configuration(saved, replace=True)
        row = self.window.groups[0].actions[0]
        editor = ActionEditor(row)
        editor.clear_trigger()
        with patch.object(self.window.native_scheduler, "start") as start:
            editor.accept()
            row.apply_action_config(editor.config)
            start.assert_not_called()
        self.assertIsNone(row.trigger)
        self.assertEqual(row.action_config().mode, "hold")
        self.assertTrue(row.execution_control.isEnabled())
        self.assertTrue(row.state_button.isEnabled())
        self.assertFalse(row.settings_button.property("bound"))

    def test_first_binding_defaults_to_follow_and_requires_trigger_and_output(self):
        editor = ActionEditor(self.row)
        self.assertEqual(editor.mode.currentData(), "hold")
        self.assertFalse(editor.save_button.isEnabled())
        editor.set_trigger(SIDE)
        self.assertFalse(editor.save_button.isEnabled())
        editor.set_output(C)
        self.assertTrue(editor.save_button.isEnabled())
        self.assertFalse(editor.interval.isEnabled())
        self.assertFalse(editor.press.isEnabled())
        editor.reject()
        self.assertIsNone(self.row.binding)
        self.assertIsNone(self.row.trigger)

    def test_fixed_parameters_enable_only_applicable_fields(self):
        self.row.apply_action_config(ActionConfig(COMBO, "hold", 150, trigger=SIDE))
        editor = ActionEditor(self.row)
        for field in (editor.gap, editor.count, editor.interval, editor.press):
            self.assertFalse(field.isHidden())
        self.assertTrue(editor.gap.isEnabled())
        self.assertFalse(editor.count.isEnabled())
        self.assertFalse(editor.interval.isEnabled())
        self.assertFalse(editor.press.isEnabled())
        editor.mode.setCurrentIndex(editor.mode.findData("repeat"))
        self.assertTrue(editor.interval.isEnabled())
        self.assertTrue(editor.press.isEnabled())
        editor.mode.setCurrentIndex(editor.mode.findData("burst"))
        self.assertTrue(editor.count.isEnabled())
        editor.count.setValue(1)
        self.assertFalse(editor.interval.isEnabled())
        editor.mode.setCurrentIndex(editor.mode.findData("single"))
        self.assertFalse(editor.count.isEnabled())
        self.assertTrue(editor.press.isEnabled())
        editor.accept()
        self.row.apply_action_config(editor.config)
        self.assertEqual(self.row.action_config().repeat_count, 1)
        self.assertEqual(self.row.action_config().mode, "burst")
        self.assertFalse(self.row.interval_field.isEnabled())
        self.assertTrue(self.row.press_field.isEnabled())

    def test_open_dialog_geometry_stays_fixed_across_modes_and_validation(self):
        self.row.apply_action_config(ActionConfig(COMBO, "burst", 150, trigger=SIDE))
        editor = ActionEditor(self.row)
        editor.show()
        APP.processEvents()
        widgets = (editor.trigger_button, editor.output_button, editor.mode, editor.count,
                   editor.interval, editor.press, editor.gap, editor.preview,
                   editor.passthrough, editor.clear_button, editor.save_button)
        def geometry():
            return (editor.size(), tuple((w.mapTo(editor, QPoint()), w.size()) for w in widgets))
        expected = geometry()
        def unchanged():
            APP.processEvents()
            self.assertEqual(geometry(), expected)
            self.assertLessEqual(editor.preview.height(), editor.preview.fontMetrics().lineSpacing() * 2 + 4)
            for widget in widgets:
                self.assertFalse(widget.isHidden())
        for mode in ("single", "hold", "repeat", "burst", "single", "hold"):
            editor.mode.setCurrentIndex(editor.mode.findData(mode))
            unchanged()
        editor.count.setValue(1)
        unchanged()
        editor.set_output(C)
        unchanged()
        editor.passthrough.setChecked(True)
        unchanged()
        editor.set_error("触发键重复，请修改触发键或停用重复的绑定。")
        unchanged()
        editor.clear_trigger()
        unchanged()
        editor.set_trigger(SIDE)
        unchanged()
        editor.reject()

    def test_inline_combo_capture_preserves_order_until_explicit_save(self):
        self.row.apply_action_config(ActionConfig(X, "repeat", 150))
        original = self.row.to_dict()
        editor = ActionEditor(self.row)
        field = editor.output_button
        with patch.object(field, "grabKeyboard"), patch.object(field, "grabMouse"):
            field.begin_capture()
        self.assertFalse(editor.save_button.isEnabled())
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier))
        field.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(2, 2), Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier))
        field._finish_capture()
        self.assertFalse(field.capturing)
        self.assertEqual(editor.binding.code, 0x43)
        self.assertEqual(editor.binding.additional, (InputAtom("mouse", "right"),))
        self.assertEqual(self.row.to_dict(), original)
        editor.reject()
        self.assertEqual(self.row.to_dict(), original)

    def test_inline_escape_cancels_partial_capture_and_releases_pending_state(self):
        self.row.apply_action_config(ActionConfig(C, "hold", 150, trigger=SIDE))
        editor = ActionEditor(self.row)
        field = editor.output_button
        with patch.object(field, "grabKeyboard"), patch.object(field, "grabMouse"):
            field.begin_capture()
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier))
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(field.capturing)
        self.assertFalse(field._finish_timer.isActive())
        self.assertEqual(editor.binding, C)
        self.assertTrue(editor.save_button.isEnabled())
        editor.reject()

    def test_inline_trigger_capture_completes_single_key_with_modifiers(self):
        self.row.apply_action_config(ActionConfig(C, "repeat", 150))
        editor = ActionEditor(self.row)
        field = editor.trigger_button
        with patch.object(field, "grabKeyboard"), patch.object(field, "grabMouse"):
            field.begin_capture()
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
        self.assertTrue(field.capturing)
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier))
        self.assertFalse(field.capturing)
        self.assertEqual(editor.trigger.code, 0x58)
        self.assertEqual(editor.trigger.modifiers, 2)
        self.assertEqual(editor.mode.currentData(), "hold")
        self.assertTrue(editor.save_button.isEnabled())
        self.assertIsNone(self.row.trigger)
        editor.reject()

    def test_conflicting_trigger_is_reported_inline_without_nested_dialog(self):
        self.row.apply_action_config(ActionConfig(C, "repeat", 150))
        self.window.groups[0].add_action()
        self.window.groups[0].actions[-1].apply_action_config(ActionConfig(X, "hold", 150, trigger=SIDE))
        editor = ActionEditor(self.row)
        editor.set_trigger(SIDE)
        with patch("main.QMessageBox.information") as information:
            editor.accept()
            information.assert_not_called()
        self.assertFalse(editor.error.isHidden())
        self.assertIn("重复", editor.error.text())
        self.assertIsNone(self.row.trigger)
        editor.reject()


if __name__ == "__main__": unittest.main()
