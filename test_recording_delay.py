"""Preparation excludes input, preserves stop controls, and keeps the original UI."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from main import ClickerShell
from models import InputBinding
from recorder import NativeRecorder, RECORDING_START_DELAY_SECONDS
from recording_models import RecordedEvent as E, RecordingSession

APP = QApplication.instance() or QApplication([])


def delayed_recorder(clock, stopped=None):
    recorder = NativeRecorder(lambda: stopped.append(True) if stopped is not None else None,
                              lambda error: None, start_delay_seconds=RECORDING_START_DELAY_SECONDS,
                              stop_binding=InputBinding("keyboard", 0x77))
    recorder.session = RecordingSession((0, 0, 1920, 1080), lambda: clock[0])
    recorder.session.started += 3_000_000_000
    recorder._in_app = lambda: False
    recorder._in_app_at = lambda event: False
    return recorder


class PreparationCaptureTests(unittest.TestCase):
    def setUp(self):
        self.clock = [10_000_000_000]
        self.recorder = delayed_recorder(self.clock)

    def advance(self, ms):
        self.clock[0] += int(ms * 1_000_000)

    def test_preparation_excludes_all_input_and_timeline_begins_after_it(self):
        for event in (E(0, "key", 65, True), E(0, "key", 65, False),
                      E(0, "move", x=100, y=200), E(0, "relative", x=5, y=-2),
                      E(0, "wheel", delta=120), E(0, "button", "left", True),
                      E(0, "button", "left", False)):
            self.recorder._capture(event)
        self.assertEqual(self.recorder.session.events, [])
        self.advance(3000)
        self.recorder._capture(E(0, "key", 66, True, scan=48))
        self.advance(50)
        self.recorder._capture(E(0, "key", 66, False, scan=48))
        sequence = self.recorder.finish("录制 1")
        self.assertEqual([e.t_us for e in sequence.events], [0, 50_000])
        self.assertEqual(sequence.duration_us, 50_000)

    def test_held_through_countdown_ignored_until_released_then_fresh_press_records(self):
        self.recorder._capture(E(0, "key", 65, True))
        self.recorder._capture(E(0, "button", "left", True))
        self.advance(3001)
        self.recorder._capture(E(0, "key", 65, True))  # OS auto-repeat.
        self.recorder._capture(E(0, "button", "left", False))
        self.recorder._capture(E(0, "key", 65, False))
        self.assertEqual(self.recorder.session.events, [])
        self.recorder._capture(E(0, "key", 65, True))
        self.advance(50)
        self.recorder._capture(E(0, "key", 65, False))
        self.assertEqual(len(self.recorder.finish("新按下").events), 2)

    def test_preparation_can_cancel_without_creating_empty_recording(self):
        self.advance(1000)
        self.recorder._capture(E(0, "move", x=10, y=20))
        self.assertIsNone(self.recorder.finish("取消"))
        self.advance(4000)
        self.recorder._capture(E(0, "key", 65, True))
        self.assertEqual(self.recorder.session.events, [])

    def test_f9_and_total_hotkey_cancel_preparation(self):
        for code in (0x78, 0x77):
            with self.subTest(code=code):
                stopped = []
                recorder = delayed_recorder(self.clock, stopped)
                with patch("recorder.user32.PostThreadMessageW"):
                    self.assertTrue(recorder._capture(E(0, "key", code, True)))
                self.assertEqual(stopped, [True])
                self.assertIsNone(recorder.finish("取消"))

    def test_stop_timestamp_excludes_gui_dispatch_and_thread_cleanup_delay(self):
        self.advance(3100)
        self.recorder._capture(E(0, "key", 65, True, scan=30))
        self.advance(50)
        with patch("recorder.user32.PostThreadMessageW"):
            self.recorder._capture(E(0, "key", 0x78, True))
        self.advance(2000)
        sequence = self.recorder.finish("停止")
        self.assertEqual(sequence.duration_us, 150_000)
        self.assertEqual([(e.code, e.pressed, e.t_us) for e in sequence.events],
                         [(65, True, 100_000), (65, False, 150_000)])

    def test_first_stop_button_click_filtered_before_app_receives_focus(self):
        self.advance(3100)
        self.recorder._in_app_at = lambda event: True
        self.recorder._capture(E(0, "button", "left", True, 100, 200))
        self.recorder._in_app_at = lambda event: False
        self.recorder._capture(E(0, "button", "left", False, 100, 200))
        self.assertIsNone(self.recorder.finish("空录制"))

    def test_release_begun_outside_app_is_retained_when_pointer_enters_app(self):
        self.advance(3100)
        self.recorder._capture(E(0, "button", "left", True, 500, 500))
        self.advance(50)
        self.recorder._in_app_at = lambda event: True
        self.recorder._capture(E(0, "button", "left", False, 100, 200))
        sequence = self.recorder.finish("拖动")
        self.assertEqual([(e.pressed, e.t_us) for e in sequence.events], [(True, 100_000), (False, 150_000)])

    def test_injected_stop_key_does_not_cancel_preparation(self):
        self.assertFalse(self.recorder._capture(E(0, "key", 0x78, True), injected=True))
        self.assertFalse(self.recorder._stop.is_set())
        self.assertEqual(self.recorder._physical, set())


class PreparationUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = ClickerShell(QSettings(str(Path(self.temp.name) / "test.ini"), QSettings.Format.IniFormat))
        self.window._hotkey_registration_scheduled = True
        self.clock = [10_000_000_000]
        self.recorder = delayed_recorder(self.clock)
        self.recorder.start = lambda: None

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_countdown_only_changes_button_text_without_moving_layout(self):
        self.window.show()
        APP.processEvents()
        title = self.window.windowTitle()
        count = self.window.active_group.count_label.text()
        layout = (self.window.size(), self.window.recording_button.geometry(), self.window.start_button.geometry())
        with patch("main.NativeRecorder", return_value=self.recorder), \
             patch("main.time.perf_counter", side_effect=lambda: self.clock[0] / 1_000_000_000):
            self.window.toggle_recording()
            for offset, text in ((0, "3s"), (1_000_000_000, "2s"), (2_000_000_000, "1s"),
                                 (3_000_000_000, "停止录制")):
                self.clock[0] = 10_000_000_000 + offset
                self.window.update_recording()
                APP.processEvents()
                self.assertEqual(self.window.recording_button.text(), text)
                self.assertEqual((self.window.size(), self.window.recording_button.geometry(), self.window.start_button.geometry()), layout)
                if offset < 3_000_000_000:
                    self.assertEqual(self.window.windowTitle(), title)
                    self.assertEqual(self.window.active_group.count_label.text(), count)
            self.window.finish_recording()
        self.assertEqual(self.window.recording_button.text(), "录制动作")
        self.assertTrue(self.window.start_button.isEnabled())

    def test_click_again_or_total_stop_cancels_countdown_without_row(self):
        for stop in (self.window.toggle_recording, self.window.toggle_execution):
            with self.subTest(stop=stop.__name__):
                self.clock[0] = 10_000_000_000
                self.recorder = delayed_recorder(self.clock)
                self.recorder.start = lambda: None
                count = len(self.window.active_group.actions)
                with patch("main.NativeRecorder", return_value=self.recorder):
                    self.window.toggle_recording()
                    stop()
                self.assertIsNone(self.window.recorder)
                self.assertFalse(self.window._recording_timer.isActive())
                self.assertEqual(len(self.window.active_group.actions), count)
                self.assertEqual(self.window.recording_button.text(), "录制动作")

    def test_startup_failure_leaves_original_controls(self):
        with patch("main.NativeRecorder", return_value=self.recorder), \
             patch.object(self.recorder, "start", side_effect=RuntimeError("测试启动失败")), \
             patch("main.QMessageBox.critical") as error:
            self.window.toggle_recording()
        error.assert_called_once()
        self.assertIsNone(self.window.recorder)
        self.assertEqual(self.window.recording_button.text(), "录制动作")
        self.assertFalse(self.window._recording_timer.isActive())
        self.assertTrue(self.window.start_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
