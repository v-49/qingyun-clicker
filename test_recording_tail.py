"""Only the final confirmed return is trimmed; original timing stays recoverable."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from main import ClickerShell, BindingCaptureButton, binding_display
from models import InputBinding
from recorder import NativeRecorder
from recording_models import RecordedEvent as E, RecordedSequence, RecordingSession, insert_press, restore_original
from sequence_ui import SequenceEditor

APP = QApplication.instance() or QApplication([])


class TailTests(unittest.TestCase):
    def setUp(self):
        self.clock = [10_000_000_000]
        self.own = False
        self.recorder = NativeRecorder(lambda: None, self.fail, stop_binding=InputBinding("keyboard", 0x77))
        self.recorder.session = RecordingSession((0, 0, 1920, 1080), lambda: self.clock[0])
        self.recorder._in_app = lambda: self.own
        self.recorder._in_app_at = lambda event: False
        self.focus(False)

    def event(self, ms, event):
        self.clock[0] = 10_000_000_000 + ms * 1_000_000
        return self.recorder._capture(event)

    def focus(self, own, ms=0):
        self.clock[0] = 10_000_000_000 + ms * 1_000_000
        self.own = own
        self.recorder._tail.focus(own, self.recorder.session, self.clock[0])

    def gameplay(self):
        self.event(100, E(0, "key", 0x43, True, scan=46))
        self.event(150, E(0, "key", 0x43, False, scan=46))

    def switch(self, at=1000, reverse=False):
        if reverse:
            self.event(at - 10, E(0, "key", 0xA0, True, scan=42))
        self.event(at, E(0, "key", 0xA4, True, scan=56))
        self.event(at + 20, E(0, "key", 0x09, True, scan=15))
        self.event(at + 50, E(0, "key", 0x09, False, scan=15))

    def finish(self, ms=5000):
        self.clock[0] = 10_000_000_000 + ms * 1_000_000
        return self.recorder.finish("录制 1")

    def test_final_alt_tab_and_wait_are_removed_but_original_is_complete(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        self.event(1120, E(0, "key", 0xA4, False, scan=56))
        self.event(1500, E(0, "move", x=50, y=70))
        sequence = self.finish()
        self.assertEqual([(e.code, e.pressed) for e in sequence.events], [(0x43, True), (0x43, False)])
        self.assertEqual(sequence.duration_us, 1_000_000)
        original = restore_original(sequence)
        self.assertEqual(original.duration_us, 5_000_000)
        self.assertEqual([e.code for e in original.events], [0x43, 0x43, 0xA4, 0x09, 0x09, 0xA4])
        self.assertTrue(sequence.can_restore)

    def test_focus_before_alt_release_needs_no_further_input(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        sequence = self.finish()
        self.assertEqual(sequence.duration_us, 1_000_000)
        restore_original(sequence).validate()

    def test_final_focus_check_handles_stop_click_before_callback(self):
        self.gameplay()
        self.switch()
        self.own = True
        self.assertEqual(self.finish().duration_us, 1_000_000)

    def test_mouse_event_on_own_window_does_not_invalidate_pending_switch(self):
        self.gameplay()
        self.switch()
        self.event(1100, E(0, "key", 0xA4, False))
        self.own = True
        self.event(1200, E(0, "move", x=50, y=70))
        self.assertEqual(self.finish().duration_us, 1_000_000)

    def test_focus_after_f9_does_not_change_where_the_recording_stopped(self):
        self.gameplay()
        self.switch()
        with patch("recorder.user32.PostThreadMessageW"):
            self.event(1100, E(0, "key", 0x78, True))
        self.own = True  # Window changed before queued GUI completion ran.
        sequence = self.finish()
        self.assertFalse(sequence.can_restore)
        self.assertIn(0x09, [e.code for e in sequence.events])

    def test_alt_shift_tab_is_one_return_gesture(self):
        self.gameplay()
        self.switch(reverse=True)
        self.focus(True, 1100)
        sequence = self.finish()
        self.assertEqual(sequence.duration_us, 990_000)
        self.assertEqual(len(sequence.events), 2)

    def test_cycle_with_alt_held_keeps_first_gesture_boundary(self):
        self.gameplay()
        self.switch()
        self.event(4000, E(0, "key", 0x09, True))
        self.event(4020, E(0, "key", 0x09, False))
        self.focus(True, 4100)
        self.assertEqual(self.finish().duration_us, 1_000_000)

    def test_slow_alt_tab_selection_does_not_expire_while_alt_is_held(self):
        self.gameplay()
        self.switch()
        self.focus(True, 4000)
        self.assertEqual(self.finish().duration_us, 1_000_000)

    def test_mid_recording_return_is_preserved_after_resuming_gameplay(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        self.event(1120, E(0, "key", 0xA4, False))
        self.focus(False, 2000)
        self.event(2100, E(0, "key", 0x41, True))
        self.event(2150, E(0, "key", 0x41, False))
        with patch("recorder.user32.PostThreadMessageW"):
            self.event(2200, E(0, "key", 0x78, True))
        sequence = self.finish()
        self.assertFalse(sequence.can_restore)
        self.assertIn(0x09, [e.code for e in sequence.events])
        self.assertEqual(sequence.duration_us, 2_200_000)

    def test_only_last_return_is_cut_when_there_were_multiple_returns(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        self.event(1120, E(0, "key", 0xA4, False))
        self.focus(False, 2000)
        self.event(2100, E(0, "key", 0x41, True))
        self.event(2150, E(0, "key", 0x41, False))
        self.switch(3000)
        self.focus(True, 3100)
        sequence = self.finish()
        self.assertEqual(sequence.duration_us, 3_000_000)
        self.assertEqual(sum(e.code == 0x09 for e in sequence.events), 2)
        self.assertIn(0x41, [e.code for e in sequence.events])

    def test_external_input_invalidates_old_switch_candidate(self):
        self.gameplay()
        self.switch()
        self.event(1100, E(0, "key", 0xA4, False))
        self.event(1200, E(0, "key", 0x42, True))
        self.event(1250, E(0, "key", 0x42, False))
        self.focus(True, 2000)
        sequence = self.finish()
        self.assertIn(0x42, [e.code for e in sequence.events])
        self.assertEqual(sequence.duration_us, 2_000_000)

    def test_external_mouse_movement_after_switch_is_not_guessed_away(self):
        self.gameplay()
        self.switch()
        self.event(1100, E(0, "key", 0xA4, False))
        self.event(1200, E(0, "move", x=400, y=300))
        self.focus(True, 2000)
        sequence = self.finish()
        self.assertEqual(sequence.events[-1].kind, "move")
        self.assertEqual(sequence.duration_us, 2_000_000)

    def test_direct_mouse_return_preserves_uncertain_gameplay_movement(self):
        self.gameplay()
        self.event(1000, E(0, "move", x=400, y=300))
        self.focus(True, 1500)
        sequence = self.finish()
        self.assertEqual(sequence.events[-1].kind, "move")
        self.assertEqual(sequence.duration_us, 1_500_000)

    def test_cut_balances_game_key_and_mouse_in_reverse_order(self):
        self.event(100, E(0, "key", 0x57, True, scan=17))
        self.event(200, E(0, "button", "right", True, 400, 500))
        self.switch()
        self.focus(True, 1100)
        sequence = self.finish()
        self.assertEqual([(e.kind, e.code, e.pressed) for e in sequence.events],
                         [("key", 0x57, True), ("button", "right", True),
                          ("button", "right", False), ("key", 0x57, False)])
        self.assertEqual([e.t_us for e in sequence.events[-2:]], [1_000_000, 1_000_000])
        self.assertEqual(sequence.events[-1].scan, 17)

    def test_long_held_alt_used_in_game_is_preserved(self):
        self.event(100, E(0, "key", 0xA4, True, scan=56))
        self.event(500, E(0, "move", x=40, y=50))
        self.event(2000, E(0, "key", 0x09, True))
        self.focus(True, 2100)
        sequence = self.finish()
        self.assertEqual([e.code for e in sequence.events if e.kind == "key"], [0xA4, 0xA4])
        self.assertEqual(sequence.duration_us, 2_000_000)

    def test_cut_releases_mouse_at_last_game_position_without_jumping_back(self):
        self.event(100, E(0, "button", "right", True, 10, 20))
        self.event(500, E(0, "move", x=500, y=600))
        self.switch()
        self.focus(True, 1100)
        release = self.finish().events[-1]
        self.assertEqual((release.kind, release.code, release.pressed), ("button", "right", False))
        self.assertEqual((release.x, release.y), (500, 600))

    def test_same_timestamp_game_action_before_alt_is_not_lost(self):
        self.event(1000, E(0, "key", 0x43, True))
        self.event(1000, E(0, "key", 0x43, False))
        self.switch()
        self.focus(True, 1100)
        self.assertEqual([e.code for e in self.finish().events], [0x43, 0x43])

    def test_switch_only_with_no_game_actions_creates_no_empty_row(self):
        self.switch()
        self.focus(True, 1100)
        self.assertIsNone(self.finish())

    def test_f9_in_game_never_discards_the_last_three_seconds(self):
        self.gameplay()
        self.event(4700, E(0, "key", 0x41, True))
        self.event(4750, E(0, "key", 0x41, False))
        with patch("recorder.user32.PostThreadMessageW"):
            self.event(4800, E(0, "key", 0x78, True))
        sequence = self.finish()
        self.assertEqual([e.code for e in sequence.events], [0x43, 0x43, 0x41, 0x41])
        self.assertEqual(sequence.duration_us, 4_800_000)

    def test_original_survives_save_reopen_and_later_insertion(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        sequence = RecordedSequence.from_dict(self.finish().to_dict())
        from models import InputAtom
        inserted = insert_press(sequence, (InputAtom("keyboard", 0x42),), 200_000)
        self.assertEqual(restore_original(inserted).events, sequence.original_events)

    def test_restore_button_undo_and_cancel_work_for_automatically_trimmed_data(self):
        self.gameplay()
        self.switch()
        self.focus(True, 1100)
        sequence = self.finish()
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            window = ClickerShell(settings)
            window._hotkey_registration_scheduled = True
            try:
                window.active_group.add_action({"sequence": sequence.to_dict(), "mode": "burst"})
                row = window.active_group.actions[-1]
                editor = SequenceEditor(row, BindingCaptureButton, binding_display)
                self.assertTrue(editor.restore_button.isEnabled())
                editor.restore()
                self.assertEqual(editor.sequence.events, sequence.original_events)
                editor.undo()
                self.assertEqual(editor.sequence, sequence)
                editor.reject()
                self.assertEqual(row.sequence, sequence)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
