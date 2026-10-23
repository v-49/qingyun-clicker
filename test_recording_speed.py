"""Conservative movement speed, exact estimates, and a shared executable timeline."""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from main import ClickerShell, BindingCaptureButton, binding_display
from models import ActionConfig, InputBinding
from recording_models import RecordedEvent as E, RecordedSequence as S, preserve_original, restore_original
from scheduler import NativeScheduler
from sequence_ui import SequenceEditor

APP = QApplication.instance() or QApplication([])


def sample(speed=1.0):
    return S("路线", (E(100_000, "move", x=10, y=20), E(150_000, "move", x=50, y=30),
                      E(200_000, "move", x=100, y=40),
                      E(400_000, "button", "left", True, 100, 40),
                      E(480_000, "button", "left", False, 100, 40)),
             1_000_000, movement_speed=speed).validate()


def stamps(sequence):
    return sequence.playback_timing.timestamps or tuple(e.t_us for e in sequence.events)


class MovementTimingTests(unittest.TestCase):
    def test_one_times_is_exact_and_old_json_defaults_to_it(self):
        sequence = sample()
        self.assertIsNone(sequence.playback_timing.timestamps)
        self.assertEqual(sequence.playback_timing.duration_us, sequence.duration_us)
        self.assertNotIn("movement_speed", sequence.to_dict())
        self.assertEqual(S.from_dict(sequence.to_dict()), sequence)

    def test_two_times_only_shortens_movement_preserving_click_and_all_gaps(self):
        sequence = sample(2)
        self.assertEqual(stamps(sequence), (100_000, 125_000, 150_000, 350_000, 430_000))
        self.assertEqual(sequence.playback_timing.duration_us, 950_000)
        self.assertEqual(stamps(sequence)[4] - stamps(sequence)[3], 80_000)
        self.assertEqual(stamps(sequence)[3] - stamps(sequence)[2], 200_000)
        self.assertEqual(sequence.playback_timing.duration_us - stamps(sequence)[-1], 520_000)
        self.assertEqual(sequence.events, sample().events)

    def test_long_gap_inside_mouse_steps_is_kept(self):
        sequence = S("停顿", (E(0, "move"), E(50_000, "move", x=10),
                              E(2_050_000, "move", x=20), E(2_100_000, "move", x=30)),
                     2_500_000, movement_speed=2)
        self.assertEqual(stamps(sequence), (0, 25_000, 2_025_000, 2_050_000))
        self.assertEqual(sequence.playback_timing.duration_us, 2_450_000)

    def test_key_hold_and_drag_motion_are_not_shortened(self):
        for press in (E(0, "key", 0x57, True), E(0, "button", "right", True)):
            with self.subTest(kind=press.kind):
                release = replace(press, t_us=200_000, pressed=False)
                sequence = S("保持", (press, E(50_000, "move", x=10), E(100_000, "move", x=20), release),
                             300_000, movement_speed=3).validate()
                self.assertIsNone(sequence.playback_timing.timestamps)
                self.assertEqual(sequence.playback_timing.duration_us, 300_000)

    def test_overlapping_combination_keeps_both_holds_and_press_order(self):
        events = (E(0, "move"), E(100_000, "move", x=10), E(150_000, "key", 0x43, True),
                  E(175_000, "button", "right", True), E(200_000, "move", x=20),
                  E(225_000, "move", x=30), E(250_000, "button", "right", False),
                  E(300_000, "key", 0x43, False))
        sequence = S("组合", events, 400_000, movement_speed=2).validate()
        mapped = stamps(sequence)
        self.assertEqual(mapped[3] - mapped[2], 25_000)
        self.assertEqual(mapped[-1] - mapped[2], 150_000)
        self.assertEqual(mapped[6] - mapped[3], 75_000)

    def test_relative_mode_keeps_timing_and_speed_choice(self):
        sequence = replace(sample(3), pointer_mode="relative")
        self.assertIsNone(sequence.playback_timing.timestamps)
        self.assertEqual(sequence.playback_timing.duration_us, 1_000_000)
        self.assertEqual(sequence.movement_speed, 3)

    def test_interleaved_inactive_relative_samples_do_not_break_screen_movement(self):
        sequence = S("双来源", (E(0, "move"), E(25_000, "relative", x=5),
                                E(50_000, "move", x=10), E(75_000, "relative", x=5),
                                E(100_000, "move", x=20)), 150_000, movement_speed=2)
        self.assertEqual(stamps(sequence), (0, 12_500, 25_000, 37_500, 50_000))

    def test_stationary_samples_do_not_shorten_waits(self):
        sequence = S("悬停", (E(0, "move", x=20), E(50_000, "move", x=20),
                              E(100_000, "move", x=20)), 200_000, movement_speed=3)
        self.assertIsNone(sequence.playback_timing.timestamps)

    def test_same_timestamp_order_and_event_content_are_preserved(self):
        sequence = S("同时", (E(0, "move"), E(100_000, "move", x=10),
                              E(100_000, "key", 65, True), E(100_000, "key", 66, True),
                              E(200_000, "key", 66, False), E(200_000, "key", 65, False)),
                     300_000, movement_speed=3).validate()
        self.assertEqual(stamps(sequence)[1:4], (33_333, 33_333, 33_333))
        self.assertEqual(stamps(sequence)[4] - stamps(sequence)[2], 100_000)

    def test_all_rates_use_one_mapping_and_preserve_click_duration(self):
        for speed, saved in ((2, 50_000), (3, 66_667), (5, 80_000)):
            with self.subTest(speed=speed):
                sequence = sample(speed)
                self.assertEqual(sequence.playback_timing.saved_us, saved)
                self.assertEqual(stamps(sequence)[4] - stamps(sequence)[3], 80_000)
                self.assertEqual(tuple(sorted(stamps(sequence))), stamps(sequence))

    def test_invalid_speed_is_rejected(self):
        for value in (True, 0, -1, 1.2, 1.5, "2", float("inf"), float("nan"), None):
            with self.subTest(value=value):
                raw = sample().to_dict()
                raw["movement_speed"] = value
                with self.assertRaises(ValueError):
                    S.from_dict(raw)

    def test_timing_cache_is_local_and_recomputed_after_edit(self):
        sequence = sample(2)
        self.assertIs(sequence.playback_timing, sequence.playback_timing)
        changed = replace(sequence, movement_speed=3)
        self.assertNotEqual(changed.playback_timing.duration_us, sequence.playback_timing.duration_us)
        self.assertEqual(S.from_dict(changed.to_dict()), changed)
        self.assertNotIn("_playback_timing", changed.to_dict())

    def test_restore_retains_playback_setting_without_overwriting_raw_baseline(self):
        original = preserve_original(sample())
        sequence = replace(original, movement_speed=2)
        restored = restore_original(sequence)
        self.assertEqual(restored.events, sample().events)
        self.assertEqual(restored.movement_speed, 2)


class SimulatedClock:
    def __init__(self, runner): self.runner, self.now, self.steps = runner, 10.0, 0
    def clear(self): pass
    def set(self): pass
    def wait(self, timeout=None):
        self.steps += 1
        if self.steps > 10_000:
            raise RuntimeError("Scheduler did not finish")
        if timeout is None:
            self.runner._stop.set()
        else:
            self.now += max(timeout, 1e-8)
            if self.now >= 15:
                self.runner._stop.set()  # A completed bound action keeps listening.


class MovementSchedulerTests(unittest.TestCase):
    def run_sequence(self, speed=2, count=1, trigger=None):
        sequence = sample(speed)
        errors, observed = [], []
        runner = NativeScheduler(errors.append)
        runner._actions = (ActionConfig(None, "burst", 200, trigger=trigger, repeat_count=count, sequence=sequence),)
        clock = SimulatedClock(runner)
        runner._wake = clock
        if trigger:
            runner._events.append((0, True))
        with patch("scheduler.time.perf_counter", side_effect=lambda: clock.now), \
             patch("scheduler.recorded_input", side_effect=lambda event, mode: observed.append((event, round((clock.now - 10) * 1_000_000)))):
            runner._run()
        self.assertEqual(errors, [])
        return sequence, observed, round((clock.now - 10) * 1_000_000)

    def test_executor_and_estimate_share_exact_timing(self):
        sequence, events, ended = self.run_sequence()
        self.assertEqual([e for e, _ in events], list(sequence.events))
        self.assertEqual(tuple(t for _, t in events), stamps(sequence))
        self.assertEqual(ended, sequence.playback_timing.duration_us)

    def test_repeated_sequence_uses_same_speed_and_preserves_cycle_wait(self):
        sequence, events, ended = self.run_sequence(count=2)
        self.assertEqual(len(events), 10)
        self.assertEqual(events[5][1] - events[0][1], sequence.playback_timing.duration_us + 200_000)
        self.assertEqual(ended, 2 * sequence.playback_timing.duration_us + 200_000)

    def test_bound_sequence_uses_its_own_speed(self):
        sequence, events, _ = self.run_sequence(trigger=InputBinding("keyboard", 0x58))
        self.assertEqual(tuple(t for _, t in events), stamps(sequence))


class MovementEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = ClickerShell(QSettings(str(Path(self.temp.name) / "speed.ini"), QSettings.Format.IniFormat))
        self.window._hotkey_registration_scheduled = True
        self.window.active_group.add_action({"sequence": sample().to_dict(), "mode": "burst", "repeat_count": 1})
        self.row = self.window.active_group.actions[-1]
        self.editor = SequenceEditor(self.row, BindingCaptureButton, binding_display)

    def tearDown(self):
        self.editor.reject()
        self.window.close()
        self.temp.cleanup()

    def test_live_calculation_preserves_original_steps_and_cancel(self):
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(2))
        self.assertEqual(self.editor.summary.text(), "1.00→0.95 秒")
        self.assertEqual(self.editor.table.item(0, 0).text(), "100 ms")
        self.assertEqual(self.row.sequence.movement_speed, 1)
        self.editor.reject()
        self.assertEqual(self.row.sequence, sample())

    def test_saved_speed_updates_main_time_and_survives_export(self):
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(2))
        self.editor.accept()
        self.assertEqual(self.row.press_spin.value(), 950)
        self.assertEqual(self.row.action_config().sequence.movement_speed, 2)
        configuration = self.window.configuration_dict()
        self.window.apply_configuration(configuration, replace=True)
        row = self.window.active_group.actions[-1]
        self.assertEqual(row.press_spin.value(), 950)
        self.assertEqual(row.sequence.movement_speed, 2)

    def test_speed_undo_redo_and_one_times_restore_original_timing(self):
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(3))
        self.editor.undo()
        self.assertEqual(self.editor.speed.currentData(), 1)
        self.editor.redo()
        self.assertEqual(self.editor.speed.currentData(), 3)
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(1))
        self.assertEqual(self.editor.sequence.playback_timing.duration_us, 1_000_000)
        self.assertFalse(self.editor.sequence.can_restore)

    def test_relative_mode_disables_speed_and_switching_back_restores_it(self):
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(2))
        self.editor.pointer.setCurrentIndex(self.editor.pointer.findData("relative"))
        self.assertFalse(self.editor.speed.isEnabled())
        self.assertEqual(self.editor.summary.text(), "1.00→1.00 秒")
        self.editor.pointer.setCurrentIndex(self.editor.pointer.findData("screen"))
        self.assertTrue(self.editor.speed.isEnabled())
        self.assertEqual(self.editor.summary.text(), "1.00→0.95 秒")

    def test_preview_locks_speed_and_sends_the_selected_setting(self):
        self.editor.speed.setCurrentIndex(self.editor.speed.findData(2))
        with patch.object(self.window, "play_sequence", return_value=False) as play:
            self.editor.preview()
            self.assertFalse(self.editor.speed.isEnabled())
            self.editor._delay.stop()
            self.editor.begin_preview()
            config = play.call_args.args[0]
        self.assertEqual(config.sequence.movement_speed, 2)
        self.assertEqual(config.sequence.playback_timing.duration_us, 950_000)
        self.assertTrue(self.editor.speed.isEnabled())


if __name__ == "__main__":
    unittest.main()
