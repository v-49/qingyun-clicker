from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog

from ahk_engine import AhkRunner
from main import CaptureDialog, ClickerShell, binding_name
from models import ActionConfig, InputAtom, InputBinding
from scheduler import NativeScheduler


APP = QApplication.instance() or QApplication([])


class ModelTests(unittest.TestCase):
    def test_binding_roundtrip(self) -> None:
        source = InputBinding("keyboard", 0x41, 0x0006, "Ctrl+Shift+A+B", (InputAtom("keyboard", 0x42),))
        self.assertEqual(InputBinding.from_dict(source.to_dict()), source)

    def test_binding_names(self) -> None:
        self.assertEqual(binding_name("keyboard", 0x77), "F8")
        self.assertEqual(binding_name("mouse", "left", 0x0002), "Ctrl+鼠标左键")
        self.assertEqual(binding_name("keyboard", 0x41, 0, (InputAtom("keyboard", 0x42),)), "A+B")


class SchedulerTests(unittest.TestCase):
    def test_hold_is_released_and_repeat_runs(self) -> None:
        repeat = ActionConfig(InputBinding("keyboard", 0x41, 0, "A"), "repeat", 8)
        hold = ActionConfig(InputBinding("keyboard", 0x57, 0, "W"), "hold", 100)
        calls: list[tuple[str, str]] = []
        with (
            patch("scheduler.binding_down", side_effect=lambda binding: calls.append(("down", binding.display))),
            patch("scheduler.binding_up", side_effect=lambda binding: calls.append(("up", binding.display))),
            patch("scheduler.binding_tap", side_effect=lambda binding: calls.append(("tap", binding.display))),
        ):
            scheduler = NativeScheduler()
            scheduler.start([repeat, hold])
            time.sleep(0.035)
            scheduler.stop()
        self.assertEqual(calls.count(("down", "W")), 1)
        self.assertEqual(calls.count(("up", "W")), 1)
        self.assertGreaterEqual(calls.count(("tap", "A")), 2)


class AhkTests(unittest.TestCase):
    def test_script_contains_repeat_hold_and_graceful_stop(self) -> None:
        actions = [
            ActionConfig(InputBinding("keyboard", 0x41, 0x0002, "Ctrl+A"), "repeat", 25),
            ActionConfig(InputBinding("mouse", "right", 0, "鼠标右键"), "hold", 100),
        ]
        script = AhkRunner._build_script(actions, Path(r"C:\Temp\stop.signal"), None)
        self.assertIn("SetTimer Action1, 25", script)
        self.assertIn("{Ctrl down}{vk41 down}{vk41 up}{Ctrl up}", script)
        self.assertIn("{RButton down}", script)
        self.assertIn("{RButton up}", script)
        self.assertIn("while !FileExist(stopFile)", script)

    def test_window_mouse_uses_control_click(self) -> None:
        action = ActionConfig(InputBinding("mouse", "left", 0x0002, "Ctrl+鼠标左键"), "repeat", 8)
        script = AhkRunner._build_script([action], Path(r"C:\Temp\stop.signal"), 1234)
        self.assertIn('ControlSend("{Ctrl down}"', script)
        self.assertIn('ControlClick(, "ahk_id 1234", , "Left", 1, "D NA")', script)
        self.assertIn('ControlClick(, "ahk_id 1234", , "Left", 1, "U NA")', script)
        self.assertIn('ControlSend("{Ctrl up}"', script)

    def test_multi_key_combo_is_pressed_and_released_in_order(self) -> None:
        binding = InputBinding("keyboard", 0x41, 0, "A+B", (InputAtom("keyboard", 0x42),))
        script = AhkRunner._build_script([ActionConfig(binding, "repeat", 20)], Path(r"C:\Temp\stop.signal"), None)
        self.assertIn("{vk41 down}{vk42 down}{vk42 up}{vk41 up}", script)


class UiConfigurationTests(unittest.TestCase):
    def test_capture_waits_and_collects_multiple_keys(self) -> None:
        with patch.object(ClickerShell, "_register_global_hotkey", return_value=None):
            parent = ClickerShell()
            dialog = CaptureDialog(parent, allow_mouse=True, title="test")
            dialog.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
            dialog.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a"))
            dialog.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier, "b"))
            self.assertIsNone(dialog.binding)
            self.assertTrue(dialog._finish_timer.isActive())
            dialog._finish_capture()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.binding.display, "Ctrl+A+B")
            parent.deleteLater()

    def test_configuration_roundtrip(self) -> None:
        with patch.object(ClickerShell, "_register_global_hotkey", return_value=None):
            first = ClickerShell()
            first._loading = True
            first.apply_configuration({"groups": []}, replace=True)
            first._loading = False
            group = first.groups[0]
            group.add_action()
            row = group.actions[0]
            row.binding = InputBinding("mouse", "left", 0x0002, "Ctrl+鼠标左键+A", (InputAtom("keyboard", 0x41),))
            row.record_button.setText(row.binding.display)
            row.interval_spin.setValue(8)
            data = first.configuration_dict()

            second = ClickerShell()
            second._loading = True
            second.apply_configuration(data, replace=True)
            second._loading = False
            restored = second.groups[0].actions[0]
            self.assertEqual(restored.binding, row.binding)
            self.assertEqual(restored.interval_spin.value(), 8)
            first._unregister_global_hotkey()
            second._unregister_global_hotkey()
            first.deleteLater()
            second.deleteLater()

    def test_unconfigured_rows_are_ignored_when_starting(self) -> None:
        with patch.object(ClickerShell, "_register_global_hotkey", return_value=None):
            window = ClickerShell()
            window._loading = True
            window.apply_configuration({"groups": []}, replace=True)
            group = window.groups[0]
            group.add_action()
            group.add_action()
            group.actions[1].binding = InputBinding("keyboard", 0x41, 0, "A")
            window._loading = False
            with (
                patch.object(window.native_scheduler, "start") as start,
                patch("main.QMessageBox.information") as information,
            ):
                window.start_execution()
                start.assert_called_once()
                self.assertEqual(len(start.call_args.args[0]), 1)
                information.assert_not_called()
            window.stop_execution()
            window.deleteLater()

    def test_action_order_changes_and_serializes(self) -> None:
        with patch.object(ClickerShell, "_register_global_hotkey", return_value=None):
            window = ClickerShell()
            window._loading = True
            window.apply_configuration({"groups": []}, replace=True)
            group = window.groups[0]
            for vk in (0x41, 0x42, 0x43):
                group.add_action()
                group.actions[-1].binding = InputBinding("keyboard", vk, 0, chr(vk))
            group.move_action(group.actions[0], 2)
            self.assertEqual([row.binding.code for row in group.actions], [0x42, 0x43, 0x41])
            self.assertEqual([item["binding"]["code"] for item in group.to_dict()["actions"]], [0x42, 0x43, 0x41])
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
