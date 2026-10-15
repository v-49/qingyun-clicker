"""Recording lifecycle, edits, serialization, and mixed native scheduling."""
import os
import ctypes
from ctypes import wintypes
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog
from main import ActionEditor, BindingCaptureButton, ClickerShell, binding_display
from models import ActionConfig, InputAtom, InputBinding
from recording_models import RecordedEvent as E, RecordedSequence as S, RecordingSession, insert_press, remove_events, restore_original
from scheduler import NativeScheduler, validate_actions
from sequence_ui import SequenceEditor
from recorder import NativeRecorder
from wininput import desktop_bounds

APP = QApplication.instance() or QApplication([])


def sample(duration=20_000):
    return S("录制 1", (E(0, "key", 0x43, True, scan=46), E(10_000, "key", 0x43, False, scan=46)), duration,
             screen_bounds=desktop_bounds()).validate()


class TimelineTests(unittest.TestCase):
    def test_roundtrip_is_lossless(self):
        sequence = S("拖动", (E(0, "move", x=-50, y=50), E(1_000, "button", "left", True, -50, 50),
                             E(2_000, "relative", x=5, y=-2), E(3_000, "wheel", delta=-120),
                             E(4_000, "button", "left", False, 80, 50)), 10_000)
        self.assertEqual(S.from_dict(sequence.to_dict()), sequence)

    def test_invalid_timeline_cannot_execute(self):
        for sequence in (replace(sample(), duration_us=1), replace(sample(), events=sample().events[:1]),
                         replace(sample(), events=sample().events[::-1]), replace(sample(), pointer_mode="fake")):
            with self.assertRaises(ValueError):
                sequence.validate()
        raw = sample().to_dict()
        raw["events"][0]["scan"] = True
        with self.assertRaises(ValueError):
            S.from_dict(raw)

    def test_physical_collection_ignores_injected_and_initially_held(self):
        clock = [1_000_000]
        session = RecordingSession(desktop_bounds(), lambda: clock[0])
        session.ignore(("key", 0x41))
        session.append(E(0, "key", 0x41, True))
        session.append(E(0, "key", 0x41, False))
        session.append(E(0, "key", 0x42, True), injected=True)
        clock[0] += 50_000_000
        session.append(E(0, "key", 0x43, True, scan=46))
        clock[0] += 25_000_000
        sequence = session.finish()
        self.assertEqual([(e.code, e.pressed, e.t_us) for e in sequence.events], [(0x43, True, 50_000), (0x43, False, 75_000)])
        self.assertFalse(session.finish().events[-1].pressed)

    def test_insert_preserves_remainder_and_overlap(self):
        sequence = insert_press(sample(), (InputAtom("keyboard", 0x41),), 5_000, 50, 3, 70)
        self.assertEqual(sequence.duration_us, 210_000)
        self.assertEqual(sequence.events[-1].t_us, 200_000)
        with self.assertRaises(ValueError):
            insert_press(sample(), (InputAtom("keyboard", 0x43),), 5_000)
        # A previous completed tap does not count as still held.
        insert_press(sample(), (InputAtom("keyboard", 0x43),), 20_000).validate()

    def test_delete_removes_matching_repeat_and_release_only(self):
        sequence = S("重叠", (E(0, "key", 65, True), E(1, "key", 66, True), E(2, "key", 65, True),
                              E(3, "key", 65, False), E(4, "key", 66, False)), 10)
        updated = remove_events(sequence, [2]).validate()
        self.assertEqual([e.code for e in updated.events], [66, 66])

    def test_reserved_output_is_rejected_and_shared_output_can_take_turns(self):
        config = ActionConfig(None, "burst", 0, repeat_count=1, sequence=sample())
        with self.assertRaises(ValueError):
            validate_actions([config], InputBinding("keyboard", 0x43))
        validate_actions([config, ActionConfig(InputBinding("keyboard", 0x43), "repeat", 150)])
        parsed = ActionConfig.from_dict({"sequence": sample().to_dict(), "binding": None, "mode": "burst", "interval_ms": 0})
        self.assertEqual(parsed.sequence, sample())

    def test_stop_keys_and_app_input_are_filtered(self):
        stopped = []
        recorder = NativeRecorder(lambda: stopped.append(True), self.fail, stop_binding=InputBinding("keyboard", 0x70))
        with patch.object(recorder, "_in_app", return_value=True):
            recorder._capture(E(0, "key", 65, True))
        with patch.object(recorder, "_in_app", return_value=False):
            recorder._capture(E(0, "key", 65, False))
            recorder._capture(E(0, "key", 66, True), injected=True)
            recorder._capture(E(0, "key", 67, True))
            recorder._capture(E(0, "key", 67, False))
            self.assertTrue(recorder._capture(E(0, "key", 0x78, True)))
        sequence = recorder.finish("检查")
        self.assertEqual([event.code for event in sequence.events], [67, 67])
        self.assertEqual(stopped, [True])

    def test_legacy_recording_without_origin_is_unchanged(self):
        raw = sample().to_dict()
        for event in raw["events"]:
            event.pop("origin")
        sequence = S.from_dict(raw)
        self.assertEqual(sequence, sample())
        self.assertFalse(sequence.can_restore)

    def test_original_survives_multiple_edits_and_roundtrip(self):
        first = insert_press(sample(), (InputAtom("keyboard", 65),), 20_000)
        second = insert_press(first, (InputAtom("keyboard", 66),), 70_000)
        edited = remove_events(second, [0]).validate()
        restored = restore_original(S.from_dict(edited.to_dict()))
        self.assertEqual(restored.events, sample().events)
        self.assertEqual(restored.duration_us, sample().duration_us)
        self.assertFalse(restored.can_restore)
        self.assertEqual({e.origin for e in edited.events}, {"inserted"})

    def test_corrupt_original_is_rejected(self):
        raw = insert_press(sample(), (InputAtom("keyboard", 65),), 20_000).to_dict()
        raw["original"]["events"].pop()
        with self.assertRaises(ValueError):
            S.from_dict(raw)


class SequenceSchedulerTests(unittest.TestCase):
    def test_single_replay_finishes_and_notifies(self):
        calls, stopped = [], []
        with patch("scheduler.recorded_input", side_effect=lambda e, mode: calls.append(e)):
            scheduler = NativeScheduler(on_stopped=lambda: stopped.append(True))
            scheduler.start([ActionConfig(None, "burst", 0, repeat_count=1, sequence=sample())])
            scheduler._thread.join(1)
            self.assertFalse(scheduler.running)
            self.assertEqual(calls, list(sample().events))
            self.assertEqual(stopped, [True])
            scheduler.stop()

    def test_mixed_actions_are_not_blocked_by_sequence_waits(self):
        calls = []
        config = ActionConfig(None, "repeat", 5, sequence=sample(500_000))
        ordinary = ActionConfig(InputBinding("keyboard", 0x41), "repeat", 5, 0)
        with patch("scheduler.recorded_input", side_effect=lambda e, mode: calls.append(("seq", e.pressed))), \
             patch("scheduler.binding_tap", side_effect=lambda b: calls.append(("tap", True))):
            scheduler = NativeScheduler()
            scheduler.start([config, ordinary])
            time.sleep(.085)
            scheduler.stop()
        self.assertEqual(calls.count(("seq", True)), 1)
        self.assertGreaterEqual(calls.count(("tap", True)), 3)

    def test_stop_mid_press_releases_captured_scan(self):
        calls = []
        sequence = S("长按", (E(0, "key", 0xA3, True, scan=29, extended=True),
                              E(1_000_000, "key", 0xA3, False, scan=29, extended=True)), 1_000_000)
        with patch("scheduler.recorded_input", side_effect=lambda e, mode: calls.append((e, mode))):
            scheduler = NativeScheduler()
            scheduler.start([ActionConfig(None, "burst", 0, repeat_count=1, sequence=sequence)])
            time.sleep(.025)
            scheduler.stop()
        self.assertEqual([e.pressed for e, _ in calls], [True, False])
        self.assertTrue(calls[-1][0].extended)
        self.assertEqual(calls[-1][0].scan, 29)

    def test_bound_loop_stops_on_physical_release(self):
        calls = []
        class Monitor:
            def __init__(self, router, error):
                self.router = router
            def start(self): pass
            def stop(self): pass
        with patch("scheduler.recorded_input", side_effect=lambda e, mode: calls.append(e)):
            scheduler = NativeScheduler(monitor_factory=Monitor)
            scheduler.start([ActionConfig(None, "repeat", 5, trigger=InputBinding("keyboard", 0x58), sequence=sample())])
            self.assertEqual(calls, [])
            router = scheduler._monitor.router
            router.handle(InputAtom("keyboard", 0x58), True)
            time.sleep(.04)
            router.handle(InputAtom("keyboard", 0x58), False)
            time.sleep(.02)
            count = len(calls)
            time.sleep(.025)
            self.assertEqual(len(calls), count)
            self.assertFalse(calls[-1].pressed)
            scheduler.stop()


class RecordingUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = ClickerShell(QSettings(str(Path(self.temp.name) / "test.ini"), QSettings.Format.IniFormat))
        self.window._hotkey_registration_scheduled = True

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def add_recording(self):
        self.window.active_group.add_action({"sequence": sample().to_dict(), "mode": "burst", "automatic_mode": "burst", "repeat_count": 1})
        return self.window.active_group.actions[-1]

    def test_recording_stop_saves_to_existing_group_without_execution(self):
        class Recorder:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def finish(self, name): return replace(sample(), name=name)
        with patch("main.NativeRecorder", Recorder):
            self.window.toggle_recording()
            self.assertEqual(self.window.recording_button.text(), "3s")
            self.window._recording_started = time.perf_counter() - .01
            self.window.update_recording()
            self.assertEqual(self.window.recording_button.text(), "停止录制")
            self.assertFalse(self.window.start_button.isEnabled())
            self.window.toggle_execution()  # Total hotkey also stops recording.
        self.assertIsNone(self.window.recorder)
        self.assertEqual(self.window.recording_button.text(), "录制动作")
        self.assertFalse(self.window._running)
        row = self.window.active_group.actions[-1]
        self.assertEqual(row.execution_mode, "burst")
        self.assertEqual(row.repeat_button.text(), "循环")
        self.assertFalse(row.repeat_button.isChecked())
        self.assertTrue(row.press_spin.isReadOnly())
        row.repeat_button.click()
        self.assertEqual(row.execution_mode, "repeat")

    def test_roundtrip_and_stopped_binding_style(self):
        row = self.add_recording()
        row.apply_action_config(ActionConfig(None, "repeat", 100, trigger=InputBinding("keyboard", 0x58), sequence=row.sequence))
        row.state_button.click()
        self.assertEqual(row.state_button.text(), "停")
        self.assertNotIn("停用", row.record_button.text())
        self.assertFalse(row.record_button.isEnabled())
        self.assertTrue(row.settings_button.isEnabled())
        configuration = self.window.configuration_dict()
        self.assertEqual(configuration["version"], 2)
        self.window.apply_configuration(configuration, replace=True)
        restored = self.window.active_group.actions[-1]
        self.assertEqual(restored.sequence, row.sequence)
        self.assertEqual(restored.trigger, row.trigger)
        self.assertFalse(restored.state_button.isChecked())

    def test_sequence_binding_editor_and_atomic_edit_cancel(self):
        row = self.add_recording()
        dialog = ActionEditor(row)
        self.assertFalse(dialog.output_button.isEnabled())
        dialog.set_trigger(InputBinding("mouse", "x1"))
        dialog.mode.setCurrentIndex(dialog.mode.findData("repeat"))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(dialog.config.sequence)
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.name.setText("暂不保存")
        editor.capture.set_binding(InputBinding("keyboard", 0x41))
        editor.insert_step()
        editor.reject()
        self.assertEqual(row.sequence, sample())

    def test_sequence_editor_insert_and_save(self):
        row = self.add_recording()
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.name.setText("游戏操作")
        editor.capture.set_binding(InputBinding("keyboard", 0x41))
        editor.insert_step()
        self.assertEqual(len(editor.sequence.events), 4)
        editor.accept()
        self.assertEqual(row.sequence.name, "游戏操作")
        self.assertEqual(row.sequence.duration_us, 70_000)

    def test_malformed_recording_does_not_fall_back_to_automatic_key(self):
        self.window.active_group.add_action({"sequence": {}, "binding": InputBinding("keyboard", 65).to_dict()})
        row = self.window.active_group.actions[-1]
        self.assertIsNone(row.action_config())
        self.assertFalse(row.state_button.isChecked())

    def test_switch_group_keeps_recording_in_origin(self):
        origin = self.window.active_group
        destination = self.window.create_group("第二组", activate=False)
        class Recorder:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def finish(self, name): return replace(sample(), name=name)
        with patch("main.NativeRecorder", Recorder):
            self.window.toggle_recording()
            self.window.activate_group(destination)
        self.assertEqual(len(origin.actions), 1)
        self.assertEqual(len(destination.actions), 0)
        self.assertIs(self.window.active_group, destination)
        self.assertIsNone(self.window.recorder)

    def test_empty_recording_does_not_add_a_fake_action(self):
        class Recorder:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def finish(self, name): return None
        with patch("main.NativeRecorder", Recorder):
            self.window.toggle_recording()
            self.window.finish_recording()
        self.assertEqual(self.window.active_group.actions, [])
        self.assertTrue(self.window.start_button.isEnabled())

    def test_duplicate_global_stop_notification_does_not_start_playback(self):
        class Recorder:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def finish(self, name): return sample()
        message = wintypes.MSG()
        message.message = self.window.WM_HOTKEY
        message.wParam = self.window.HOTKEY_ID
        with patch("main.NativeRecorder", Recorder), patch.object(self.window, "start_execution") as start:
            self.window.toggle_recording()
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            self.window.finish_recording()  # The hook may notify before WM_HOTKEY.
            APP.processEvents()
            self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
            APP.processEvents()
            start.assert_not_called()

    def test_insert_undo_redo_and_restore_are_atomic(self):
        row = self.add_recording()
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.capture.set_binding(InputBinding("keyboard", 65))
        editor.insert_step()
        modified = editor.sequence
        self.assertEqual(editor.table.item(0, 0).data(Qt.ItemDataRole.UserRole), "recorded")
        self.assertEqual(editor.table.item(1, 0).data(Qt.ItemDataRole.UserRole), "inserted")
        editor.undo()
        self.assertEqual(editor.sequence, sample())
        editor.redo()
        self.assertEqual(editor.sequence, modified)
        editor.restore()
        self.assertEqual(editor.sequence.events, sample().events)
        editor.undo()
        self.assertEqual(editor.sequence, modified)
        editor.reject()
        self.assertEqual(row.sequence, sample())

    def test_restore_after_save_and_reopen_preserves_name_and_pointer(self):
        row = self.add_recording()
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.capture.set_binding(InputBinding("keyboard", 65))
        editor.insert_step()
        editor.name.setText("游戏路线")
        editor.pointer.setCurrentIndex(1)
        editor.accept()
        configuration = self.window.configuration_dict()
        self.window.apply_configuration(configuration, replace=True)
        restored_row = self.window.active_group.actions[-1]
        reopened = SequenceEditor(restored_row, BindingCaptureButton, binding_display)
        self.assertTrue(reopened.restore_button.isEnabled())
        self.assertEqual(reopened.table.item(1, 0).data(Qt.ItemDataRole.UserRole), "inserted")
        reopened.restore()
        reopened.accept()
        self.assertEqual(restored_row.sequence.events, sample().events)
        self.assertEqual(restored_row.sequence.duration_us, sample().duration_us)
        self.assertEqual(restored_row.sequence.name, "游戏路线")
        self.assertEqual(restored_row.sequence.pointer_mode, "relative")

    def test_modified_and_deleted_steps_can_be_undone(self):
        row = self.add_recording()
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.table.selectRow(0)
        editor.duration.setValue(50)
        editor.apply_step()
        changed = editor.sequence
        self.assertEqual(changed.events[-1].t_us, 50_000)
        editor.undo()
        self.assertEqual(editor.sequence, sample())
        editor.redo()
        self.assertEqual(editor.sequence, changed)
        editor.capture.set_binding(InputBinding("keyboard", 65))
        editor.table.clearSelection()
        editor.table.setCurrentCell(-1, -1)
        editor.insert_step()
        inserted = editor.sequence
        editor.table.selectRow(0)
        editor.delete_step()
        self.assertEqual({e.code for e in editor.sequence.events}, {65})
        editor.undo()
        self.assertEqual(editor.sequence, inserted)
        editor.reject()

    def test_preview_locks_history_and_new_edit_clears_redo(self):
        row = self.add_recording()
        editor = SequenceEditor(row, BindingCaptureButton, binding_display)
        editor.capture.set_binding(InputBinding("keyboard", 65))
        editor.insert_step()
        editor.undo()
        self.assertTrue(editor.redo_button.isEnabled())
        editor.capture.set_binding(InputBinding("keyboard", 66))
        editor.insert_step()
        self.assertFalse(editor.redo_button.isEnabled())
        snapshot = editor.sequence
        editor.preview()
        self.assertFalse(editor.undo_button.isEnabled())
        self.assertFalse(editor.restore_button.isEnabled())
        editor.undo()
        editor.restore()
        self.assertEqual(editor.sequence, snapshot)
        editor.preview()  # Cancel the pending trial; it must never inject.
        self.assertTrue(editor.undo_button.isEnabled())
        editor.reject()


if __name__ == "__main__":
    unittest.main()
