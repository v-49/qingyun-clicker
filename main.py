"""Qt 6 desktop interface shell for the clicker product."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QSettings, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QIcon, QIntValidator, QKeyEvent, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ahk_engine import AhkRunner, find_ahk
from models import ActionConfig, InputAtom, InputBinding
from scheduler import NativeScheduler
from shutdown_timer import ShutdownCountdown
from wininput import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    WindowInfo,
    is_window,
    register_hotkey,
    unregister_hotkey,
    visible_windows,
)


APP_QSS = r"""
QMainWindow, QWidget#root {
    background: #faf9f6;
    color: #292f29;
    font-family: "Microsoft YaHei UI";
    font-size: 14px;
}

QLabel#columnLabel, QLabel#engineLabel, QLabel#globalLabel {
    color: #747a70;
    font-size: 13px;
    font-weight: 500;
}

QPushButton, QSpinBox {
    min-height: 32px;
    border: 1px solid #e0e2d9;
    border-radius: 8px;
    background: #fdfdfb;
    color: #292f29;
    padding: 0 12px;
}

QPushButton:hover, QSpinBox:hover {
    border-color: #bcc6b6;
    background: #f5f6f0;
}

QPushButton:focus, QSpinBox:focus {
    border: 1px solid #465e49;
}

QPushButton:disabled, QSpinBox:disabled {
    color: #a1a79c;
    background: #eeefe9;
    border-color: #e0e2d9;
}

QPushButton#primaryButton {
    min-width: 80px;
    border-color: #2c3c30;
    background: #2c3c30;
    color: #fdfdfb;
    font-size: 14px;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    border-color: #223026;
    background: #223026;
}

QPushButton#addButton {
    min-width: 32px;
    max-width: 32px;
    border-color: #c9d3c5;
    background: #eef2e9;
    color: #2c3c30;
    font-weight: 600;
    padding: 0;
}

QPushButton#addButton:hover {
    border-color: #85b29d;
    background: #e3f2eb;
}

QPushButton#quietButton, QPushButton#addGroupButton {
    min-height: 30px;
    border-color: transparent;
    background: transparent;
    color: #747a70;
    padding: 0 10px;
}

QPushButton#quietButton:hover, QPushButton#addGroupButton:hover {
    border-color: transparent;
    background: #eeede8;
    color: #292f29;
}

QPushButton#hotkeyButton {
    min-width: 36px;
    max-width: 160px;
    text-align: center;
    padding: 0 3px;
}

QFrame#engineSwitch {
    min-height: 32px;
    max-height: 32px;
    border: 1px solid #e0e2d9;
    border-radius: 8px;
    background: #eeede8;
}

QPushButton#engineOption {
    min-height: 30px;
    max-height: 30px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: #444d43;
    padding: 0 7px;
}

QPushButton#engineOption:hover:!checked {
    border: 0;
    background: #e4e5dd;
}

QPushButton#engineOption:checked {
    border: 0;
    background: #fdfdfb;
    color: #2c3c30;
    font-weight: 600;
}

QPushButton#targetWindowButton {
    width: 80px;
    color: #2c3c30;
}

QScrollArea#groupScroll {
    border: 1px solid #e0e2d9;
    border-radius: 12px;
    background: #fdfdfb;
}

QWidget#groupsPanel {
    background: #fdfdfb;
}

QFrame#groupFrame {
    border: 0;
    border-bottom: 1px solid #e0e2d9;
    background: #fdfdfb;
}

QFrame#groupHeader {
    min-height: 42px;
    border: 0;
    background: #f1f2ed;
}

QFrame#groupFrame[active="true"] QFrame#groupHeader {
    background: #e9eee5;
}

QPushButton#groupToggle, QPushButton#groupName, QPushButton#groupDelete {
    min-height: 27px;
    border-color: transparent;
    background: transparent;
}

QPushButton#groupToggle {
    width: 28px;
    color: #8a9384;
    padding: 0;
}

QPushButton#groupName {
    color: #292f29;
    font-size: 14px;
    font-weight: 600;
    text-align: left;
    padding: 0 2px;
}

QFrame#groupFrame[active="true"] QPushButton#groupName {
    color: #2c3c30;
}

QPushButton#groupDelete {
    width: 28px;
    color: #9ba397;
    font-size: 16px;
    padding: 0;
}

QPushButton#groupDelete:hover {
    border-color: transparent;
    background: #f7e9e7;
    color: #aa352e;
}

QLabel#groupCount {
    color: #747a70;
    font-size: 13px;
    font-weight: 500;
}

QLabel#activeDot {
    color: #2c3c30;
    font-size: 15px;
}

QLabel#emptyGroup {
    min-height: 62px;
    color: #7f7f85;
    font-weight: 500;
    background: #fdfdfb;
}

QFrame#actionRow {
    min-height: 52px;
    border: 0;
    border-top: 1px solid #e0e2d9;
    background: #fdfdfb;
}

QLabel#dragHandle {
    color: #afb6a9;
    font-size: 14px;
}

QPushButton#deleteAction {
    width: 20px;
    min-height: 24px;
    border-color: transparent;
    background: transparent;
    color: #929b8c;
    font-size: 17px;
    padding: 0;
}

QPushButton#deleteAction:hover {
    border-color: transparent;
    background: #f7e9e7;
    color: #aa352e;
}

QWidget#executionControl {
    border: 1px solid transparent;
    border-radius: 11px;
    background: #eeede8;
}

QPushButton#modeButton, QPushButton#stateButton {
    min-height: 30px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    padding: 0 3px;
    font-size: 12px;
}

QPushButton#modeButton:hover {
    background: #e4e5dd;
}

QPushButton#modeButton:checked {
    border: 0;
    background: #fdfdfb;
    color: #2c3c30;
    font-weight: 600;
}

QPushButton#stateButton:checked {
    border: 1px solid #dce3e7;
    background: #ebeff1;
    color: #485863;
    font-weight: 600;
}

QPushButton#stateButton:checked:hover {
    background: #e1e8ec;
    border-color: #c6d2da;
}

QPushButton#stateButton:checked:pressed {
    background: #d6e0e6;
    border-color: #b7c7d1;
}

QPushButton#stateButton:focus { border: 1px solid #7d939f; }

QPushButton#stateButton:!checked {
    color: #747a70;
    background: #d8dbd3;
}

QPushButton#recordButton {
    text-align: left;
    color: #3d453d;
    font-weight: 500;
}

QFrame#intervalField {
    min-height: 32px;
    max-height: 32px;
    border: 1px solid #e0e2d9;
    border-radius: 8px;
    background: #fdfdfb;
}

QFrame#intervalField:hover {
    border-color: #bcc6b6;
    background: #f5f6f0;
}

QFrame#intervalField:disabled {
    border-color: #e0e2d9;
    background: #eeefe9;
}

QSpinBox#intervalSpin {
    min-width: 44px;
    min-height: 28px;
    border: 0;
    border-radius: 0;
    background: transparent;
    padding: 0;
    selection-background-color: #2c3c30;
}

QSpinBox#intervalSpin:hover, QSpinBox#intervalSpin:focus {
    border: 0;
    background: transparent;
}

QLabel#intervalUnit {
    color: #747a70;
    font-size: 12px;
    font-weight: 500;
}

QLabel#intervalUnit:disabled {
    color: #a8a8ad;
}

QDialog#captureDialog {
    background: #faf9f6;
}

QLabel#capturePrompt {
    min-height: 76px;
    border: 1px dashed #c9d3c5;
    border-radius: 10px;
    background: #fdfdfb;
    color: #2c3c30;
    font-size: 15px;
    font-weight: 600;
}

QScrollBar:vertical {
    width: 12px;
    margin: 2px;
    background: transparent;
}

QScrollBar::handle:vertical {
    min-height: 34px;
    border-radius: 5px;
    background: #bec6b7;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QPushButton#shutdownButton {
    background: #e9eee5;
    color: #2c3c30;
    border: 0;
    border-radius: 10px;
    padding: 0 10px;
    font-weight: 600;
}
QPushButton#shutdownButton:hover { background: #dce5d7; }
QPushButton#shutdownButton[active="true"] {
    background: #fff0da;
    color: #845019;
}
QPushButton#shutdownButton[active="true"]:hover { background: #ffe3b5; }
QPushButton#shutdownButton:focus { border: 1px solid #465e49; }
QPushButton:pressed { background: #e4e8dd; }
QPushButton#primaryButton:pressed { background: #1c281f; }
QFrame#groupHeader { background: #f1f2ed; }
QFrame#groupFrame[active="true"] QFrame#groupHeader { background: #e9eee5; }
QPushButton#recordButton { border-color: #e0e2d9; border-radius: 10px; }
QPushButton#recordButton:focus { border-color: #465e49; }
QPushButton#primaryButton { border-radius: 10px; }
QLineEdit { selection-background-color: #2c3c30; selection-color: #fdfdfb; }
QDialog#shutdownDialog { background: #faf9f6; }
QLabel#durationTitle { font-size: 18px; font-weight: 600; color: #292f29; }
QLabel#durationHint { color: #747a70; font-size: 12px; }
QLineEdit#durationInput {
    background: #fdfdfb; color: #292f29; font-size: 30px;
    border: 1px solid #e0e2d9; border-radius: 10px; padding: 6px;
    selection-background-color: #2c3c30;
}
QLineEdit#durationInput:focus { border-color: #2c3c30; }
QLabel#durationUnit { font-size: 14px; color: #747a70; }
QPushButton#primaryButton[launch="true"] {
    background: #ebeff1;
    color: #485863;
    border: 1px solid #dce3e7;
}
QPushButton#primaryButton[launch="true"]:hover {
    background: #e1e8ec;
    border-color: #c6d2da;
}
QPushButton#primaryButton[launch="true"]:pressed {
    background: #d6e0e6;
    border-color: #b7c7d1;
}
QPushButton#primaryButton[launch="true"]:focus {
    border-color: #7d939f;
}
QPushButton#primaryButton[launch="true"]:disabled {
    background: #f0f2f3;
    color: #9aa5ab;
    border-color: #e3e8eb;
}
"""


def resource_path(filename: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / filename)


VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space",
    0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2D: "Insert", 0x2E: "Delete",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt", 0x5B: "Win",
}
MOUSE_NAMES = {"left": "鼠标左键", "right": "鼠标右键", "middle": "鼠标中键", "x1": "鼠标侧键1", "x2": "鼠标侧键2"}
QT_KEY_TO_VK = {
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
}
MODIFIER_QT_KEYS = {
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
}
MODIFIER_KEY_BINDINGS = {
    Qt.Key.Key_Shift: (0x10, MOD_SHIFT),
    Qt.Key.Key_Control: (0x11, MOD_CONTROL),
    Qt.Key.Key_Alt: (0x12, MOD_ALT),
    Qt.Key.Key_Meta: (0x5B, MOD_WIN),
}


def native_modifiers(modifiers: Qt.KeyboardModifier) -> int:
    result = 0
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        result |= MOD_CONTROL
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        result |= MOD_SHIFT
    if modifiers & Qt.KeyboardModifier.AltModifier:
        result |= MOD_ALT
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        result |= MOD_WIN
    return result


def vk_from_event(event: QKeyEvent) -> int:
    native = int(event.nativeVirtualKey())
    if native:
        return native
    key = event.key()
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return 0x41 + key - Qt.Key.Key_A
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return 0x30 + key - Qt.Key.Key_0
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return 0x70 + key - Qt.Key.Key_F1
    return QT_KEY_TO_VK.get(Qt.Key(key), 0)


def atom_name(kind: str, code: int | str) -> str:
    if kind == "mouse":
        return MOUSE_NAMES[str(code)]
    vk = int(code)
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return VK_NAMES.get(vk, f"VK {vk:02X}")


def binding_name(
    kind: str,
    code: int | str,
    modifiers: int = 0,
    additional: tuple[InputAtom, ...] = (),
) -> str:
    prefixes = []
    if modifiers & MOD_CONTROL:
        prefixes.append("Ctrl")
    if modifiers & MOD_SHIFT:
        prefixes.append("Shift")
    if modifiers & MOD_ALT:
        prefixes.append("Alt")
    if modifiers & MOD_WIN:
        prefixes.append("Win")
    names = [atom_name(kind, code), *(atom_name(atom.kind, atom.code) for atom in additional)]
    return "+".join([*prefixes, *names])


def binding_display(binding: InputBinding) -> str:
    return binding.display or binding_name(binding.kind, binding.code, binding.modifiers, binding.additional)


class CaptureDialog(QDialog):
    def __init__(self, parent: QWidget, allow_mouse: bool, title: str) -> None:
        super().__init__(parent)
        self.allow_mouse = allow_mouse
        self.binding: InputBinding | None = None
        self._atoms: list[InputAtom] = []
        self._modifier_atoms: list[InputAtom] = []
        self._modifier_flags = 0
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.setInterval(1000)
        self._finish_timer.timeout.connect(self._finish_capture)
        self.setObjectName("captureDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(410, 142)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        prompt = "请按下一个或多个键盘按键/鼠标按钮\n最后一次输入 1 秒后自动完成 · Esc 取消" if allow_mouse else "请按下新的键盘快捷键\n最后一次输入 1 秒后自动完成 · Esc 取消"
        self.prompt_label = QLabel(prompt)
        self.prompt_label.setObjectName("capturePrompt")
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.prompt_label)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()
        if self.allow_mouse:
            self.grabMouse()

    def done(self, result: int) -> None:
        self._finish_timer.stop()
        self.releaseKeyboard()
        if self.allow_mouse:
            self.releaseMouse()
        super().done(result)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape and event.modifiers() == Qt.KeyboardModifier.NoModifier and not self._atoms and not self._modifier_atoms:
            self.reject()
            return
        modifier_key = MODIFIER_KEY_BINDINGS.get(Qt.Key(event.key()))
        if modifier_key is not None:
            vk, own_flag = modifier_key
            self._modifier_flags |= own_flag
            atom = InputAtom("keyboard", vk)
            if atom not in self._modifier_atoms:
                self._modifier_atoms.append(atom)
        else:
            vk = vk_from_event(event)
            if not vk:
                return
            self._modifier_flags |= native_modifiers(event.modifiers())
            atom = InputAtom("keyboard", vk)
            if atom not in self._atoms:
                self._atoms.append(atom)
        self._capture_changed()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.allow_mouse:
            return
        names = {
            Qt.MouseButton.LeftButton: "left",
            Qt.MouseButton.RightButton: "right",
            Qt.MouseButton.MiddleButton: "middle",
            Qt.MouseButton.XButton1: "x1",
            Qt.MouseButton.XButton2: "x2",
        }
        button = names.get(event.button())
        if button is None:
            return
        self._modifier_flags |= native_modifiers(event.modifiers())
        atom = InputAtom("mouse", button)
        if atom not in self._atoms:
            self._atoms.append(atom)
        self._capture_changed()

    def _current_binding(self) -> InputBinding | None:
        if self._atoms:
            first, *rest = self._atoms
            binding = InputBinding(first.kind, first.code, self._modifier_flags, "", tuple(rest))
        elif self._modifier_atoms:
            first, *rest = self._modifier_atoms
            binding = InputBinding(first.kind, first.code, 0, "", tuple(rest))
        else:
            return None
        return InputBinding(binding.kind, binding.code, binding.modifiers, binding_display(binding), binding.additional)

    def _capture_changed(self) -> None:
        preview = self._current_binding()
        if preview is None:
            return
        self.prompt_label.setText(f"已录入：{preview.display}\n继续按键可组成组合键 · 1 秒后自动完成")
        self._finish_timer.start()

    def _finish_capture(self) -> None:
        self.binding = self._current_binding()
        if self.binding is not None:
            self.accept()


class UiBridge(QObject):
    execution_error = Signal(str)


class DragHandle(QLabel):
    def __init__(self, action: "ActionRow") -> None:
        super().__init__("⋮⋮")
        self.action = action
        self.setObjectName("dragHandle")
        self.setFixedWidth(16)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip("按住并上下拖动排序")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self.isEnabled():
            owner = self.action.owner
            local = owner.actions_widget.mapFromGlobal(event.globalPosition().toPoint())
            owner.reorder_action_at(self.action, local.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()


class ShutdownDialog(QDialog):
    """Direct hours/minutes entry without native spin arrows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("定时关机")
        self.setObjectName("shutdownDialog")
        self.setFixedWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        title = QLabel("在这段时间后关机")
        title.setObjectName("durationTitle")
        layout.addWidget(title)
        duration = QHBoxLayout()
        duration.setSpacing(10)
        self.hours = QLineEdit("0")
        self.minutes = QLineEdit("30")
        for edit, name, maximum in ((self.hours, "小时", 168), (self.minutes, "分钟", 59)):
            edit.setObjectName("durationInput")
            edit.setAccessibleName(name)
            edit.setValidator(QIntValidator(0, maximum, edit))
            edit.setMaxLength(3 if name == "小时" else 2)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setFixedWidth(76)
            duration.addWidget(edit)
            unit = QLabel(name)
            unit.setObjectName("durationUnit")
            duration.addWidget(unit)
        duration.addStretch()
        layout.addLayout(duration)
        self.hint = QLabel("再次点击可取消，退出软件自动取消。")
        self.hint.setObjectName("durationHint")
        layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.confirm = QPushButton("开始计时")
        self.confirm.setObjectName("primaryButton")
        self.confirm.setDefault(True)
        self.confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        self.hours.textChanged.connect(self.validate_duration)
        self.minutes.textChanged.connect(self.validate_duration)
        self.minutes.setFocus()
        self.minutes.selectAll()

    def total_minutes(self):
        return int(self.hours.text() or 0) * 60 + int(self.minutes.text() or 0)

    def validate_duration(self):
        valid = self.hours.hasAcceptableInput() and self.minutes.hasAcceptableInput() and 1 <= self.total_minutes() <= 10080
        self.confirm.setEnabled(valid)
        self.hint.setText("再次点击可取消，退出软件自动取消。" if valid else "请填写 1 分钟至 168 小时，分钟为 0–59。")

    def accept(self):
        self.validate_duration()
        if self.confirm.isEnabled():
            super().accept()


class IntervalField(QFrame):
    def mousePressEvent(self, event):
        spin = self.findChild(QSpinBox)
        if spin is not None and spin.isEnabled():
            spin.setFocus()
            spin.selectAll()
        super().mousePressEvent(event)


class IntervalEdit(QLineEdit):
    """Native editing, with compact trailing zeros only when not editing."""

    def paintEvent(self, event):
        value = self.text()
        if self.hasFocus() or len(value) < 3 or not value.endswith("00"):
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = self.font()
        small = QFont(font)
        small.setPixelSize(max(9, round(QFontMetricsF(font).height() * 0.55)))
        normal_metrics, small_metrics = QFontMetricsF(font), QFontMetricsF(small)
        width = normal_metrics.horizontalAdvance(value[:-2]) + small_metrics.horizontalAdvance("00")
        x = self.width() - width - 2
        baseline = (self.height() - normal_metrics.height()) / 2 + normal_metrics.ascent()
        painter.setPen(self.palette().color(QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        painter.setFont(font)
        painter.drawText(int(x), int(baseline), value[:-2])
        painter.setFont(small)
        painter.drawText(int(x + normal_metrics.horizontalAdvance(value[:-2])), int(baseline), "00")


class IntervalSpinBox(QSpinBox):
    def __init__(self):
        super().__init__()
        self.setLineEdit(IntervalEdit())
        self.setAccessibleName("动作间隔，毫秒")
        self.setToolTip("1–99999 毫秒；点击编辑完整数字，末尾两个零在显示时缩小")


class ActionRow(QFrame):
    def __init__(self, owner: "GroupWidget", data: dict | None = None) -> None:
        super().__init__()
        self.owner = owner
        self.binding: InputBinding | None = None
        self.setObjectName("actionRow")

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 7, 6, 7)
        row.setSpacing(4)

        self.drag_handle = DragHandle(self)
        row.addWidget(self.drag_handle)

        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("deleteAction")
        self.remove_button.setFixedWidth(20)
        self.remove_button.setToolTip("删除动作")
        self.remove_button.clicked.connect(lambda: owner.remove_action(self))
        row.addWidget(self.remove_button)

        execution = QWidget()
        execution.setObjectName("executionControl")
        execution.setFixedWidth(126)
        execution_layout = QHBoxLayout(execution)
        execution_layout.setContentsMargins(3, 3, 3, 3)
        execution_layout.setSpacing(2)

        self.repeat_button = QPushButton("间隔")
        self.repeat_button.setObjectName("modeButton")
        self.repeat_button.setCheckable(True)
        self.repeat_button.setChecked(True)
        self.hold_button = QPushButton("按住")
        self.hold_button.setObjectName("modeButton")
        self.hold_button.setCheckable(True)
        self.state_button = QPushButton("启")
        self.state_button.setObjectName("stateButton")
        self.state_button.setCheckable(True)
        self.state_button.setChecked(True)
        self.state_button.setFixedWidth(28)

        modes = QButtonGroup(self)
        modes.setExclusive(True)
        modes.addButton(self.repeat_button)
        modes.addButton(self.hold_button)
        self._modes = modes

        execution_layout.addWidget(self.repeat_button, 1)
        execution_layout.addWidget(self.state_button)
        execution_layout.addWidget(self.hold_button, 1)
        row.addWidget(execution)

        self.record_button = QPushButton("未设置按键")
        self.record_button.setObjectName("recordButton")
        self.record_button.setMinimumWidth(100)
        self.record_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.record_button.clicked.connect(self.capture_binding)
        row.addWidget(self.record_button, 1)

        self.interval_field = IntervalField()
        self.interval_field.setObjectName("intervalField")
        self.interval_field.setFixedWidth(78)
        interval_layout = QHBoxLayout(self.interval_field)
        interval_layout.setContentsMargins(4, 1, 4, 1)
        interval_layout.setSpacing(2)

        self.interval_spin = IntervalSpinBox()
        self.interval_spin.setObjectName("intervalSpin")
        self.interval_spin.setRange(1, 99999)
        self.interval_spin.setValue(150)
        self.interval_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.interval_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.interval_spin.valueChanged.connect(owner.window.schedule_save)
        interval_layout.addWidget(self.interval_spin)

        interval_unit = QLabel("ms")
        interval_unit.setObjectName("intervalUnit")
        interval_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        interval_layout.addWidget(interval_unit)
        row.addWidget(self.interval_field)

        self.hold_button.toggled.connect(self.update_controls)
        self.state_button.toggled.connect(self.update_controls)
        if data:
            self.load_dict(data)
        self.update_controls()

    def capture_binding(self) -> None:
        dialog = CaptureDialog(self, allow_mouse=True, title="录入动作")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.binding is None:
            return
        previous = self.binding
        self.binding = dialog.binding
        self.record_button.setText(self.binding.display)
        self.record_button.setToolTip(f"当前动作：{self.binding.display}；点击可重新录入")
        if previous is None and self.binding.kind == "mouse" and self.binding.code == "left" and self.interval_spin.value() == 150:
            self.interval_spin.setValue(8)
        self.owner.window.schedule_save()

    def update_controls(self) -> None:
        enabled = self.state_button.isChecked()
        self.state_button.setText("启" if enabled else "停")
        self.repeat_button.setEnabled(enabled)
        self.hold_button.setEnabled(enabled)
        self.record_button.setEnabled(enabled)
        self.interval_field.setEnabled(enabled and self.repeat_button.isChecked())
        self.owner.window.schedule_save()

    def action_config(self) -> ActionConfig | None:
        if not self.state_button.isChecked() or self.binding is None:
            return None
        mode = "hold" if self.hold_button.isChecked() else "repeat"
        return ActionConfig(self.binding, mode, self.interval_spin.value())

    def to_dict(self) -> dict:
        return {
            "enabled": self.state_button.isChecked(),
            "mode": "hold" if self.hold_button.isChecked() else "repeat",
            "interval_ms": self.interval_spin.value(),
            "binding": self.binding.to_dict() if self.binding else None,
        }

    def load_dict(self, data: dict) -> None:
        binding = InputBinding.from_dict(data.get("binding"))
        self.binding = binding
        if binding is not None:
            self.record_button.setText(binding_display(binding))
        try:
            interval = int(data.get("interval_ms", 150))
        except (TypeError, ValueError):
            interval = 150
        self.interval_spin.setValue(interval)
        self.hold_button.setChecked(data.get("mode") == "hold")
        self.repeat_button.setChecked(data.get("mode") != "hold")
        self.state_button.setChecked(bool(data.get("enabled", True)))

    def set_locked(self, locked: bool) -> None:
        self.drag_handle.setDisabled(locked)
        self.remove_button.setDisabled(locked)
        self.state_button.setDisabled(locked)
        if locked:
            self.repeat_button.setDisabled(True)
            self.hold_button.setDisabled(True)
            self.record_button.setDisabled(True)
            self.interval_field.setDisabled(True)
        else:
            self.update_controls()


class GroupWidget(QFrame):
    def __init__(self, window: "ClickerShell", name: str, data: dict | None = None) -> None:
        super().__init__()
        self.window = window
        self.name = name
        self.actions: list[ActionRow] = []
        self.collapsed = False
        self.setObjectName("groupFrame")
        self.setProperty("active", False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("groupHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 6, 12, 6)
        header_layout.setSpacing(6)

        self.toggle_button = QPushButton("▾")
        self.toggle_button.setObjectName("groupToggle")
        self.toggle_button.setToolTip("折叠动作组")
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header_layout.addWidget(self.toggle_button)

        self.name_button = QPushButton(name)
        self.name_button.setObjectName("groupName")
        self.name_button.clicked.connect(lambda: window.activate_group(self))
        header_layout.addWidget(self.name_button, 1)

        self.count_label = QLabel("0 项")
        self.count_label.setObjectName("groupCount")
        header_layout.addWidget(self.count_label)

        self.delete_button = QPushButton("×")
        self.delete_button.setObjectName("groupDelete")
        self.delete_button.setToolTip("删除动作组")
        self.delete_button.clicked.connect(lambda: window.delete_group(self))
        header_layout.addWidget(self.delete_button)

        self.active_dot = QLabel("●")
        self.active_dot.setObjectName("activeDot")
        self.active_dot.setFixedWidth(14)
        self.active_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_dot.hide()
        header_layout.addWidget(self.active_dot)
        outer.addWidget(header)

        self.actions_widget = QWidget()
        self.actions_layout = QVBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(0)

        self.empty_label = QLabel("当前动作组还没有动作")
        self.empty_label.setObjectName("emptyGroup")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.actions_layout.addWidget(self.empty_label)
        outer.addWidget(self.actions_widget)

        if data:
            for action_data in data.get("actions", []):
                if isinstance(action_data, dict):
                    self.add_action(action_data)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.active_dot.setVisible(active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        self.actions_widget.setVisible(not self.collapsed)
        self.toggle_button.setText("▸" if self.collapsed else "▾")
        self.toggle_button.setToolTip("展开动作组" if self.collapsed else "折叠动作组")

    def add_action(self, data: dict | None = None) -> None:
        if self.collapsed:
            self.toggle_collapsed()
        action = ActionRow(self, data)
        self.actions.append(action)
        self.actions_layout.insertWidget(self.actions_layout.count() - 1, action)
        self.refresh_count()

    def remove_action(self, action: ActionRow) -> None:
        if action not in self.actions:
            return
        self.actions.remove(action)
        action.deleteLater()
        self.refresh_count()

    def move_action(self, action: ActionRow, target_index: int) -> None:
        if action not in self.actions or self.window._running:
            return
        old_index = self.actions.index(action)
        target_index = max(0, min(target_index, len(self.actions) - 1))
        if old_index == target_index:
            return
        self.actions.pop(old_index)
        self.actions.insert(target_index, action)
        self.actions_layout.removeWidget(action)
        self.actions_layout.insertWidget(target_index, action)
        self.window.schedule_save()

    def reorder_action_at(self, action: ActionRow, y: int) -> None:
        others = [row for row in self.actions if row is not action]
        target_index = sum(y > row.geometry().center().y() for row in others)
        self.move_action(action, target_index)

    def to_dict(self) -> dict:
        return {"name": self.name, "actions": [action.to_dict() for action in self.actions]}

    def set_locked(self, locked: bool) -> None:
        self.name_button.setDisabled(locked)
        self.delete_button.setDisabled(locked)
        for action in self.actions:
            action.set_locked(locked)

    def refresh_count(self) -> None:
        self.count_label.setText(f"{len(self.actions)} 项")
        self.empty_label.setVisible(not self.actions)
        self.window.refresh_footer()
        self.window.schedule_save()


class ClickerShell(QMainWindow):
    HOTKEY_ID = 0xC11C
    WM_HOTKEY = 0x0312

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("轻云连点器")
        icon_path = resource_path("app.ico")
        if Path(icon_path).exists():
            self.setWindowIcon(QIcon(icon_path))
        self._settings = settings if settings is not None else QSettings("Clicker", "Clicker")
        self._loading = True
        self._registered_hotkey = False
        self._hotkey_hwnd = 0
        self._hotkey_registration_scheduled = False
        self._hotkey_retry_count = 0
        self._running = False
        self.global_hotkey = InputBinding("keyboard", 0x77, 0, "F8")
        self.input_mode = "原生"
        self.target_window: WindowInfo | None = None
        self.ahk_path = str(self._settings.value("runtime/ahk_path", "") or "")
        self.bridge = UiBridge(self)
        self.bridge.execution_error.connect(self.execution_failed)
        self.native_scheduler = NativeScheduler(lambda message: self.bridge.execution_error.emit(message))
        self.ahk_runner = AhkRunner()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self.save_configuration)
        self.shutdown_countdown = ShutdownCountdown(execute=self.perform_shutdown)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(1000)
        self._shutdown_timer.timeout.connect(self.update_shutdown)

        self.setMinimumSize(QSize(660, 250))
        saved_geometry = self._settings.value("window/geometry")
        if saved_geometry is None or not self.restoreGeometry(saved_geometry):
            self.resize(740, 420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.groups: list[GroupWidget] = []
        self.active_group: GroupWidget | None = None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(20, 14, 20, 12)
        main.setSpacing(9)

        heading = QHBoxLayout()
        heading.setSpacing(4)
        engine_label = QLabel("输入方式")
        engine_label.setObjectName("engineLabel")
        heading.addWidget(engine_label)

        engine_switch = QFrame()
        engine_switch.setObjectName("engineSwitch")
        engine_switch_layout = QHBoxLayout(engine_switch)
        engine_switch_layout.setContentsMargins(1, 1, 1, 1)
        engine_switch_layout.setSpacing(0)
        self.engine_modes = QButtonGroup(self)
        self.engine_modes.setExclusive(True)
        self.engine_buttons: dict[str, QPushButton] = {}
        for mode, width in (("原生", 46), ("AHK", 44), ("AHK窗口", 66)):
            button = QPushButton(mode)
            button.setObjectName("engineOption")
            button.setCheckable(True)
            button.setFixedWidth(width)
            self.engine_modes.addButton(button)
            self.engine_buttons[mode] = button
            engine_switch_layout.addWidget(button)
        heading.addWidget(engine_switch)

        self.target_button = QPushButton("选择窗口")
        self.target_button.setObjectName("targetWindowButton")
        self.target_button.setFixedHeight(34)
        self.target_button.clicked.connect(self.select_target_window)
        self.target_button.setVisible(False)
        heading.addWidget(self.target_button)
        for mode, button in self.engine_buttons.items():
            button.toggled.connect(lambda checked, selected=mode: checked and self.set_input_mode(selected))

        heading.addStretch(1)
        interval_label = QLabel("间隔")
        interval_label.setObjectName("columnLabel")
        interval_label.setFixedWidth(78)
        interval_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.addWidget(interval_label)
        main.addLayout(heading)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("groupScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(98)
        self.groups_panel = QWidget()
        self.groups_panel.setObjectName("groupsPanel")
        self.groups_layout = QVBoxLayout(self.groups_panel)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(0)
        self.groups_layout.addStretch(1)
        self.scroll.setWidget(self.groups_panel)
        main.addWidget(self.scroll, 1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.add_action_button = QPushButton("＋")
        self.add_action_button.setObjectName("addButton")
        self.add_action_button.setToolTip("添加动作")
        self.add_action_button.setFixedWidth(32)
        self.add_action_button.clicked.connect(self.add_action)
        controls.addWidget(self.add_action_button)

        self.add_group_button = QPushButton("新分组")
        self.add_group_button.setObjectName("addGroupButton")
        self.add_group_button.clicked.connect(self.add_group)
        controls.addWidget(self.add_group_button)

        self.import_button = QPushButton("导入")
        self.import_button.setObjectName("quietButton")
        self.import_button.clicked.connect(self.import_configuration)
        self.export_button = QPushButton("导出")
        self.export_button.setObjectName("quietButton")
        self.export_button.clicked.connect(self.export_configuration)
        controls.addWidget(self.import_button)
        controls.addWidget(self.export_button)
        controls.addStretch(1)

        self.shutdown_button = QPushButton("定时关机")
        self.shutdown_button.setObjectName("shutdownButton")
        self.shutdown_button.setMinimumWidth(128)
        self.shutdown_button.setToolTip("设置多少分钟后关机；再次点击取消，退出软件也会取消")
        self.shutdown_button.clicked.connect(self.toggle_shutdown)
        controls.addWidget(self.shutdown_button)
        controls.addStretch(1)

        global_label = QLabel("快捷键")
        global_label.setObjectName("globalLabel")
        controls.addWidget(global_label)
        self.hotkey_button = QPushButton("F8")
        self.hotkey_button.setObjectName("hotkeyButton")
        self.hotkey_button.setFixedWidth(72)
        self.hotkey_button.setToolTip("点击后录入新的全局启动/停止按键")
        self.hotkey_button.clicked.connect(self.capture_global_hotkey)
        controls.addWidget(self.hotkey_button)

        self.start_button = QPushButton("启动")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setProperty("launch", True)
        self.start_button.clicked.connect(self.toggle_execution)
        controls.addWidget(self.start_button)
        main.addLayout(controls)

        self.load_configuration()
        self._loading = False
        self.setFocus()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API naming
        super().showEvent(event)
        if not self._hotkey_registration_scheduled:
            self._hotkey_registration_scheduled = True
            QTimer.singleShot(100, self._register_global_hotkey)

    def toggle_shutdown(self) -> None:
        if self.shutdown_countdown.active:
            self.shutdown_countdown.cancel()
            self.update_shutdown()
            return
        dialog = ShutdownDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.shutdown_countdown.start(dialog.total_minutes())
            self._shutdown_timer.start()
            self.update_shutdown()

    def perform_shutdown(self) -> None:
        from shutdown_timer import shutdown_windows
        self.stop_execution()
        self.save_configuration()
        shutdown_windows()

    def update_shutdown(self) -> None:
        try:
            self.shutdown_countdown.tick()
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, "关机未完成", str(exc))
        active = self.shutdown_countdown.active
        if active:
            minutes, seconds = divmod(self.shutdown_countdown.remaining, 60)
            self.shutdown_button.setText(f"取消 · {minutes:02d}:{seconds:02d}")
        else:
            self._shutdown_timer.stop()
            self.shutdown_button.setText("定时关机")
        self.shutdown_button.setProperty("active", active)
        self.shutdown_button.style().unpolish(self.shutdown_button)
        self.shutdown_button.style().polish(self.shutdown_button)

    def set_input_mode(self, mode: str) -> None:
        self.input_mode = mode
        self.target_button.setVisible(mode == "AHK窗口")
        self.schedule_save()

    def create_group(self, name: str, activate: bool = True, data: dict | None = None) -> GroupWidget:
        group = GroupWidget(self, name, data)
        self.groups.append(group)
        self.groups_layout.insertWidget(self.groups_layout.count() - 1, group)
        if activate:
            self.activate_group(group)
        self.refresh_footer()
        return group

    def activate_group(self, group: GroupWidget) -> None:
        if group not in self.groups or self._running:
            return
        self.active_group = group
        for item in self.groups:
            item.set_active(item is group)
        self.refresh_footer()
        self.schedule_save()

    def add_group(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建动作组", "动作组名称：")
        name = name.strip()
        if not accepted or not name:
            return
        if any(group.name.casefold() == name.casefold() for group in self.groups):
            QMessageBox.information(self, "名称已存在", "请使用另一个动作组名称。")
            return
        self.create_group(name, activate=True)

    def delete_group(self, group: GroupWidget) -> None:
        if self._running:
            return
        if len(self.groups) <= 1:
            QMessageBox.information(self, "无法删除", "至少保留一个动作组。")
            return
        if group.actions:
            result = QMessageBox.question(
                self, "删除动作组", f"确定删除“{group.name}”及其中 {len(group.actions)} 项动作吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        index = self.groups.index(group)
        was_active = group is self.active_group
        self.groups.remove(group)
        group.deleteLater()
        if was_active:
            self.activate_group(self.groups[min(index, len(self.groups) - 1)])
        self.refresh_footer()
        self.schedule_save()

    def add_action(self) -> None:
        if self.active_group is not None and not self._running:
            self.active_group.add_action()

    def select_target_window(self) -> None:
        windows = visible_windows(int(self.winId()))
        if not windows:
            QMessageBox.information(self, "选择窗口", "当前没有可选择的可见窗口。")
            return
        labels = [f"{item.title}  ·  PID {item.pid}  ·  0x{item.hwnd:X}" for item in windows]
        selected, accepted = QInputDialog.getItem(self, "选择目标窗口", "窗口：", labels, 0, False)
        if not accepted:
            return
        self.target_window = windows[labels.index(selected)]
        self.target_button.setText("已选窗口")
        self.target_button.setToolTip(self.target_window.title)

    def capture_global_hotkey(self) -> None:
        previous = self.global_hotkey
        self._unregister_global_hotkey()
        dialog = CaptureDialog(self, allow_mouse=False, title="录入全局启动/停止快捷键")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.binding is None:
            self.global_hotkey = previous
            self._register_global_hotkey()
            return
        modifier_vks = {0x10, 0x11, 0x12, 0x5B, 0x5C}
        if dialog.binding.kind != "keyboard" or dialog.binding.additional or int(dialog.binding.code) in modifier_vks:
            QMessageBox.information(self, "快捷键格式", "全局快捷键只能使用一个主键，可搭配 Ctrl、Shift、Alt 或 Win。")
            self.global_hotkey = previous
            self._register_global_hotkey()
            return
        self.global_hotkey = dialog.binding
        try:
            self._register_global_hotkey(raise_error=True)
        except OSError:
            self.global_hotkey = previous
            self._register_global_hotkey()
            return
        self.hotkey_button.setText(self.global_hotkey.display)
        self.hotkey_button.setToolTip(f"全局启动/停止：{self.global_hotkey.display}")
        self.schedule_save()

    def _register_global_hotkey(self, raise_error: bool = False) -> None:
        self._unregister_global_hotkey()
        self._hotkey_hwnd = int(self.winId())
        if not is_window(self._hotkey_hwnd):
            if not raise_error and self._hotkey_retry_count < 5:
                self._hotkey_retry_count += 1
                QTimer.singleShot(200, self._register_global_hotkey)
            return
        try:
            register_hotkey(self._hotkey_hwnd, self.HOTKEY_ID, self.global_hotkey)
            self._registered_hotkey = True
            self._hotkey_retry_count = 0
        except OSError as exc:
            if not raise_error and getattr(exc, "errno", None) == 1400 and self._hotkey_retry_count < 5:
                self._hotkey_retry_count += 1
                QTimer.singleShot(200, self._register_global_hotkey)
                return
            if raise_error:
                QMessageBox.warning(self, "快捷键不可用", f"{self.global_hotkey.display} 已被其他程序占用。")
                raise
            self.hotkey_button.setToolTip(f"注册失败：{exc}")

    def _unregister_global_hotkey(self) -> None:
        if self._registered_hotkey and self._hotkey_hwnd:
            unregister_hotkey(self._hotkey_hwnd, self.HOTKEY_ID)
        self._registered_hotkey = False

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt API naming
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and int(msg.wParam) == self.HOTKEY_ID:
                QTimer.singleShot(0, self.toggle_execution)
                return True, 0
        except (TypeError, ValueError):
            pass
        return super().nativeEvent(event_type, message)

    def toggle_execution(self) -> None:
        if self._running:
            self.stop_execution()
        else:
            self.start_execution()

    def start_execution(self) -> None:
        group = self.active_group
        if group is None:
            return
        actions = [config for row in group.actions if (config := row.action_config()) is not None]
        if not actions:
            QMessageBox.information(self, "无法启动", "当前动作组没有已设置且启用的动作。")
            return
        try:
            if self.input_mode == "原生":
                self.native_scheduler.start(actions)
            else:
                executable = find_ahk(self.ahk_path)
                if executable is None:
                    chosen, _ = QFileDialog.getOpenFileName(self, "选择 AutoHotkey v2", "", "AutoHotkey (AutoHotkey*.exe);;程序 (*.exe)")
                    if not chosen:
                        return
                    executable = Path(chosen)
                    self.ahk_path = str(executable)
                    self._settings.setValue("runtime/ahk_path", self.ahk_path)
                target = None
                if self.input_mode == "AHK窗口":
                    if self.target_window is None or not is_window(self.target_window.hwnd):
                        QMessageBox.information(self, "目标窗口无效", "请重新选择一个正在运行的目标窗口。")
                        return
                    target = self.target_window.hwnd
                self.ahk_runner.start(executable, actions, target)
        except Exception as exc:
            QMessageBox.critical(self, "启动失败", str(exc))
            return
        self._running = True
        self.set_running_ui(True)

    def stop_execution(self) -> None:
        self.native_scheduler.stop()
        self.ahk_runner.stop()
        self._running = False
        self.set_running_ui(False)

    def execution_failed(self, message: str) -> None:
        self.stop_execution()
        QMessageBox.critical(self, "执行已停止", message)

    def set_running_ui(self, running: bool) -> None:
        self.start_button.setText("停止" if running else "启动")
        self.setWindowTitle(f"轻云连点器 — {self.active_group.name}运行中" if running and self.active_group else "轻云连点器")
        for button in self.engine_buttons.values():
            button.setDisabled(running)
        self.target_button.setDisabled(running)
        self.add_action_button.setDisabled(running)
        self.add_group_button.setDisabled(running)
        self.import_button.setDisabled(running)
        self.hotkey_button.setDisabled(running)
        for group in self.groups:
            group.set_locked(running)

    def configuration_dict(self) -> dict:
        active_index = self.groups.index(self.active_group) if self.active_group in self.groups else 0
        return {
            "version": 1,
            "input_mode": self.input_mode,
            "global_hotkey": self.global_hotkey.to_dict(),
            "active_group": active_index,
            "groups": [group.to_dict() for group in self.groups],
        }

    def schedule_save(self) -> None:
        if not self._loading and hasattr(self, "_save_timer"):
            self._save_timer.start()

    def save_configuration(self) -> None:
        if self._loading:
            return
        self._settings.setValue("configuration/json", json.dumps(self.configuration_dict(), ensure_ascii=False))
        self._settings.sync()

    def load_configuration(self) -> None:
        raw = str(self._settings.value("configuration/json", "") or "")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.apply_configuration(data, replace=True)

    def apply_configuration(self, data: dict, replace: bool) -> None:
        if replace:
            for group in self.groups:
                group.deleteLater()
            self.groups.clear()
            self.active_group = None
        mode = data.get("input_mode", "原生")
        if mode not in self.engine_buttons:
            mode = "原生"
        binding = InputBinding.from_dict(data.get("global_hotkey"))
        if binding is not None and binding.kind == "keyboard":
            self.global_hotkey = binding
        self.hotkey_button.setText(self.global_hotkey.display)
        self.engine_buttons[mode].setChecked(True)
        groups_data = data.get("groups", [])
        if isinstance(groups_data, list):
            for index, group_data in enumerate(groups_data):
                if not isinstance(group_data, dict):
                    continue
                name = str(group_data.get("name", f"动作组 {index + 1}")).strip() or f"动作组 {index + 1}"
                self.create_group(name, activate=False, data=group_data)
        if not self.groups:
            self.create_group("动作组 1", activate=False)
        active = data.get("active_group", 0)
        if not isinstance(active, int):
            active = 0
        self.activate_group(self.groups[max(0, min(active, len(self.groups) - 1))])

    def export_configuration(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出动作配置", "轻云连点器配置.json", "JSON 配置 (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.configuration_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def import_configuration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入动作配置", "", "JSON 配置 (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("groups"), list):
                raise ValueError("不是受支持的轻云连点器配置文件")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self._loading = True
        self.apply_configuration(data, replace=True)
        self._loading = False
        self._register_global_hotkey()
        self.save_configuration()

    def refresh_footer(self) -> None:
        pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API naming
        self.shutdown_countdown.cancel()
        self._shutdown_timer.stop()
        self.stop_execution()
        self._unregister_global_hotkey()
        self._settings.setValue("window/geometry", self.saveGeometry())
        self.save_configuration()
        super().closeEvent(event)


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("轻云连点器")
    icon_path = resource_path("app.ico")
    if Path(icon_path).exists():
        app.setWindowIcon(QIcon(icon_path))
    app_font = QFont("Microsoft YaHei UI")
    app_font.setPointSizeF(10.0)
    app_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(app_font)
    app.setStyleSheet(APP_QSS)
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        import tempfile
        report = Path(sys.argv[2]).resolve()
        with tempfile.TemporaryDirectory(prefix="clicker_smoke_") as temporary:
            settings = QSettings(str(Path(temporary) / "settings.ini"), QSettings.Format.IniFormat)
            window = ClickerShell(settings=settings)
            window._hotkey_registration_scheduled = True
            window.groups[0].add_action()
            window.groups[0].actions[0].interval_spin.setValue(2000)
            window.show()

            def finish_smoke():
                try:
                    assert window.isVisible()
                    assert window.groups[0].actions[0].interval_spin.value() == 2000
                    assert window.shutdown_button.text() == "定时关机"
                    assert window.grab().save(str(report.with_suffix(".png")))
                    report.write_text(json.dumps({"ok": True, "platform": app.platformName(), "frozen": bool(getattr(sys, "frozen", False)), "size": [window.width(), window.height()] }), encoding="utf-8")
                    window.close()
                    app.exit(0)
                except Exception as exc:
                    report.write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
                    app.exit(1)

            QTimer.singleShot(700, finish_smoke)
            return app.exec()
    window = ClickerShell()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
