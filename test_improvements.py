import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QDialog
from main import APP_QSS, ClickerShell, ShutdownDialog
from shutdown_timer import ShutdownCountdown, shutdown_windows

APP = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
APP.setFont(QFont("Microsoft YaHei UI", 10))


class CountdownTests(unittest.TestCase):
    def test_expiry_executes_once_and_cancel_prevents_shutdown(self):
        clock, execute = Mock(return_value=100), Mock()
        timer = ShutdownCountdown(clock, execute)
        timer.start(2)
        clock.return_value = 160
        self.assertEqual(timer.remaining, 60)
        timer.tick()
        execute.assert_not_called()
        timer.cancel()
        clock.return_value = 300
        timer.tick()
        execute.assert_not_called()
        timer.start(1)
        clock.return_value = 1000
        timer.tick()
        timer.tick()
        execute.assert_called_once()

    def test_failure_clears_countdown_and_invalid_input_is_rejected(self):
        timer = ShutdownCountdown(Mock(return_value=0), Mock(side_effect=OSError("denied")))
        for value in (0, -1, 10081, True, 1.5):
            with self.assertRaises(ValueError):
                timer.start(value)
        timer.start(1)
        timer.clock.return_value = 61
        with self.assertRaises(OSError):
            timer.tick()
        self.assertFalse(timer.active)

    def test_system_command_never_forces_app_closure(self):
        with patch("shutdown_timer.subprocess.run", return_value=Mock(returncode=0)) as run:
            shutdown_windows()
        self.assertEqual(run.call_args.args[0][1:], ["/s", "/t", "0"])


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "test.ini"), QSettings.Format.IniFormat)
        self.patch_settings = patch("main.QSettings", return_value=self.settings)
        self.patch_settings.start()
        self.patch_hotkey = patch.object(ClickerShell, "_register_global_hotkey")
        self.patch_hotkey.start()
        APP.setStyleSheet(APP_QSS)
        self.window = ClickerShell()
        self.window.show()
        self.window.groups[0].add_action()
        APP.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.patch_hotkey.stop()
        self.patch_settings.stop()
        self.temp.cleanup()

    def test_full_numeric_editing_and_debounced_save(self):
        spin = self.window.groups[0].actions[0].interval_spin
        for value in (2000, 9999, 99999):
            spin.setFocus()
            spin.selectAll()
            QTest.keyClicks(spin, str(value))
            QTest.keyClick(spin, Qt.Key.Key_Tab)
            self.assertEqual(spin.value(), value)
            self.assertEqual(spin.lineEdit().text(), str(value))
            self.assertGreaterEqual(spin.lineEdit().width(), spin.fontMetrics().horizontalAdvance(str(value)) + 4)
        self.assertTrue(self.window._save_timer.isActive())
        QTest.qWait(300)
        self.assertIn('99999', self.settings.value("configuration/json"))

    def test_timer_button_can_start_cancel_and_close_without_os_request(self):
        self.window.shutdown_countdown.execute = Mock()
        with patch("main.ShutdownDialog.exec", return_value=QDialog.DialogCode.Accepted):
            self.window.shutdown_button.click()
        self.assertIn("30:00", self.window.shutdown_button.text())
        self.window.shutdown_button.click()
        self.assertFalse(self.window.shutdown_countdown.active)
        self.assertFalse(self.window._shutdown_timer.isActive())
        self.window.shutdown_countdown.start(1)
        self.window.close()
        self.assertFalse(self.window.shutdown_countdown.active)
        self.window.shutdown_countdown.execute.assert_not_called()

    def test_shutdown_failure_is_reported_and_button_recovers(self):
        self.window.shutdown_countdown.execute = Mock(side_effect=OSError("denied"))
        self.window.shutdown_countdown.deadline = 0
        with patch("main.QMessageBox.warning") as warning:
            self.window.update_shutdown()
        warning.assert_called_once()
        self.assertEqual(self.window.shutdown_button.text(), "定时关机")

    def test_hours_minutes_direct_entry_and_validation(self):
        dialog = ShutdownDialog(self.window)
        dialog.hours.setText("2")
        dialog.minutes.setText("15")
        self.assertEqual(dialog.total_minutes(), 135)
        self.assertTrue(dialog.confirm.isEnabled())
        for hours, minutes in (("0", "0"), ("168", "1"), ("0", "60")):
            dialog.hours.setText(hours)
            dialog.minutes.setText(minutes)
            self.assertFalse(dialog.confirm.isEnabled())
        dialog.hours.setText("168")
        dialog.minutes.setText("0")
        self.assertTrue(dialog.confirm.isEnabled())


if __name__ == "__main__":
    unittest.main()
