"""Qt 6 desktop interface shell for the clicker product."""

from __future__ import annotations

import ctypes
import json
import math
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QSettings, QSignalBlocker, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QIntValidator, QKeyEvent, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ahk_engine import AhkRunner, find_ahk
from app_version import APP_NAME, APP_TITLE, APP_VERSION
from models import DEFAULT_PRESS_MS, ActionConfig, InputAtom, InputBinding
from input_names import VK_NAMES, MOUSE_NAMES, atom_name, binding_name, binding_display
from recording_models import RecordedSequence
from recorder import NativeRecorder, RECORDING_START_DELAY_SECONDS
from scheduler import NativeScheduler, validate_actions, find_overlaps
from shutdown_timer import ShutdownCountdown
from wininput import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    WindowInfo,
    binding_atoms,
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
QWidget#executionControl:disabled { background: #eeefe9; }
QPushButton#modeButton:disabled, QPushButton#stateButton:disabled,
QPushButton#modeButton:disabled:checked, QPushButton#stateButton:disabled:checked {
    color: #a1a79c; background: transparent; border: 0; font-weight: 400;
}
QPushButton#bindButton {
    min-height: 30px; padding: 0; font-size: 12px; color: #747a70;
    border-color: #e0e2d9; background: #fdfdfb;
}
QPushButton#bindButton[bound="true"] {
    color: #485863; background: #ebeff1; border-color: #c6d2da; font-weight: 600;
}
QPushButton#bindButton:hover { border-color: #7d939f; }
QPushButton#bindButton:disabled { color: #a1a79c; background: #eeefe9; }
QPushButton#recordButton:disabled { color: #a1a79c; background: #eeefe9; }
QDialog#bindingEditor { background: #faf9f6; }
QDialog#sequenceEditor { background: #faf9f6; }
QDialog#sequenceEditor QTableWidget { background: #fdfdfb; border: 1px solid #dfe2d8; gridline-color: #e6e8df; selection-background-color: #e8eeeb; selection-color: #292f29; }
QDialog#sequenceEditor QTableWidget::item { border: none; padding-left: 5px; }
QDialog#sequenceEditor QTableWidget::item:selected { background: #e8eeeb; color: #292f29; border: none; }
QDialog#sequenceEditor QHeaderView::section { background: #e9eee3; border: 0; border-bottom: 1px solid #dfe2d8; padding: 7px; color: #444d43; }
QDialog#sequenceEditor QLabel#bindingPreview { color: #485863; font-size: 12px; }
QDialog#bindingEditor QLabel { color: #444d43; }
QDialog#bindingEditor QLabel:disabled { color: #a1a79c; }
QComboBox#bindingMode {
    min-height: 32px; padding: 0 10px; border: 1px solid #e0e2d9;
    border-radius: 8px; background: #fdfdfb; color: #292f29;
}
QComboBox#bindingMode:focus { border-color: #465e49; }
QComboBox#bindingMode:disabled { color: #a1a79c; background: #eeefe9; }
QComboBox#bindingMode::drop-down { border: 0; width: 28px; }
QComboBox#bindingMode::down-arrow { image: none; }
QComboBox#bindingMode QAbstractItemView {
    background: #fdfdfb; color: #292f29; selection-background-color: #e9eee5;
    selection-color: #292f29; border: 1px solid #c9d3c5;
}
QPushButton#captureField { text-align: left; padding: 0 10px; }
QPushButton#captureField[capturing="true"] {
    border-color: #465e49; background: #eef2e9; color: #2c3c30;
}
QDialog#bindingEditor QLabel#bindingError { color: #aa352e; font-size: 12px; }
QDialog#bindingEditor QLabel#bindingPreview { color: #485863; font-size: 12px; }
"""


def resource_path(filename: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / filename)


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


class InputCaptureMixin:
    """Shared keyboard/mouse parsing for the original dialog and inline fields."""
    def reset_inputs(self) -> None:
        self._atoms: list[InputAtom] = []
        self._modifier_atoms: list[InputAtom] = []
        self._modifier_flags = 0

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


class CaptureDialog(InputCaptureMixin, QDialog):
    def __init__(self, parent: QWidget, allow_mouse: bool, title: str) -> None:
        super().__init__(parent)
        self.allow_mouse = allow_mouse
        self.binding: InputBinding | None = None
        self.reset_inputs()
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


class BindingCaptureButton(InputCaptureMixin, QPushButton):
    bindingCaptured = Signal(object)
    captureStateChanged = Signal(bool)

    def __init__(self, binding: InputBinding | None, *, single: bool) -> None:
        super().__init__()
        self.binding, self.single = binding, single
        self.allow_mouse, self.capturing = True, False
        self.reset_inputs()
        self.setObjectName("captureField")
        self.setAutoDefault(False)
        self.setToolTip("点击后按下键盘键或鼠标按钮；Esc 取消录入")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.setInterval(1000)
        self._finish_timer.timeout.connect(self._finish_capture)
        self.clicked.connect(self.begin_capture)
        self.set_binding(binding)

    def set_binding(self, binding: InputBinding | None) -> None:
        self.binding = binding
        self.setText(binding_display(binding) if binding else "点击录入触发键" if self.single else "点击录入输出")

    def begin_capture(self) -> None:
        if self.capturing:
            return
        self.reset_inputs()
        self.capturing = True
        self.setProperty("capturing", True)
        self.style().unpolish(self); self.style().polish(self)
        self.setText("请按下触发键 · Esc 取消" if self.single else "请按下输出键 · Esc 取消")
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard(); self.grabMouse()
        self.captureStateChanged.emit(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.capturing:
            if event.key() == Qt.Key.Key_Escape and event.modifiers() == Qt.KeyboardModifier.NoModifier:
                self.reject()
            else:
                InputCaptureMixin.keyPressEvent(self, event)
        else:
            QPushButton.keyPressEvent(self, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.capturing:
            InputCaptureMixin.mousePressEvent(self, event)
        else:
            QPushButton.mousePressEvent(self, event)

    def _capture_changed(self) -> None:
        preview = self._current_binding()
        if preview is None:
            return
        if self.single and self._atoms:
            self._finish_capture()
        else:
            self.setText(f"{preview.display} · 1 秒后完成")
            self._finish_timer.start()

    def reject(self) -> None:
        self._finish_timer.stop()
        if not self.capturing:
            return
        self.capturing = False
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.setProperty("capturing", False)
        self.style().unpolish(self); self.style().polish(self)
        self.set_binding(self.binding)
        self.captureStateChanged.emit(False)

    def _finish_capture(self) -> None:
        binding = self._current_binding()
        if self.single and not self._atoms and self._modifier_atoms:
            primary = self._modifier_atoms[-1]
            flags = {vk: flag for vk, flag in MODIFIER_KEY_BINDINGS.values()}
            modifiers = self._modifier_flags & ~flags[primary.code]
            binding = InputBinding(primary.kind, primary.code, modifiers)
        if binding is None:
            self.reject()
            return
        self.reject()
        self.set_binding(binding)
        self.bindingCaptured.emit(binding)


class UiBridge(QObject):
    execution_error = Signal(str)
    execution_stopped = Signal()
    recording_finished = Signal()
    recording_error = Signal(str)


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


def press_duration_field(value: int = DEFAULT_PRESS_MS) -> tuple[IntervalField, IntervalSpinBox]:
    field = IntervalField()
    field.setObjectName("intervalField")
    field.setFixedWidth(112)
    layout = QHBoxLayout(field)
    layout.setContentsMargins(4, 1, 4, 1)
    layout.setSpacing(2)
    label = QLabel("持续")
    label.setObjectName("intervalUnit")
    layout.addWidget(label)
    spin = IntervalSpinBox()
    spin.setObjectName("intervalSpin")
    spin.setRange(0, 99999)
    spin.setValue(value)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setAccessibleName("按下时长，毫秒")
    spin.setToolTip("0 毫秒为按下后立即松开；持续按住模式不使用此值")
    layout.addWidget(spin)
    unit = QLabel("ms")
    unit.setObjectName("intervalUnit")
    layout.addWidget(unit)
    return field, spin


class BindingModeCombo(QComboBox):
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#747a70"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 18, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)
        painter.end()


class ActionEditor(QDialog):
    """Configure a binding atomically without moving controls between modes."""
    def __init__(self, row: "ActionRow") -> None:
        super().__init__(row)
        self.row = row
        self.binding, self.trigger = row.binding, row.trigger
        self.sequence = row.sequence
        self._unbinding = False
        self._error_message = ""
        self.setObjectName("bindingEditor")
        self.setWindowTitle("绑定按键")
        self.setModal(True)
        self.setFixedWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        self.trigger_button = BindingCaptureButton(self.trigger, single=True)
        self.trigger_button.setAccessibleName("录入触发键")
        self.trigger_button.bindingCaptured.connect(self.set_trigger)
        self.trigger_button.captureStateChanged.connect(self.refresh)
        form.addRow("触发键", self.trigger_button)
        self.output_button = BindingCaptureButton(self.binding, single=False)
        self.output_button.setAccessibleName("录入输出按键或组合")
        self.output_button.bindingCaptured.connect(self.set_output)
        self.output_button.captureStateChanged.connect(self.refresh)
        if self.sequence:
            self.output_button.setText(self.sequence.name)
            self.output_button.setDisabled(True)
        form.addRow("输出", self.output_button)
        self.mode = BindingModeCombo()
        self.mode.setObjectName("bindingMode")
        modes = (("按住循环", "repeat"), ("指定次数", "burst"), ("单次", "single")) if self.sequence else (("跟随按住", "hold"), ("按住连发", "repeat"), ("短连发", "burst"), ("单次", "single"))
        for label, value in modes:
            self.mode.addItem(label, value)
        selected = "single" if row.execution_mode == "burst" and row.repeat_count == 1 else row.execution_mode
        self.mode.setCurrentIndex(max(0, self.mode.findData(selected if self.trigger else "single" if self.sequence else "hold")))
        self.mode_label = QLabel("执行方式")
        form.addRow(self.mode_label, self.mode)
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        self.count.setValue(row.repeat_count)
        self.count.setSuffix(" 次")
        self.count.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.count_label = QLabel("次数")
        self.interval = QSpinBox()
        self.interval.setRange(0 if self.sequence else 1, 99999)
        self.interval.setValue(row.interval_spin.value())
        self.interval.setSuffix(" ms")
        self.interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.interval_label = QLabel("循环等待" if self.sequence else "连发间隔")
        self.press = QSpinBox()
        self.press.setRange(0, 86_400_000 if self.sequence else 99999)
        self.press.setValue(row.press_spin.value())
        self.press.setSuffix(" ms")
        self.press.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.press_label = QLabel("录制时长" if self.sequence else "持续时长")
        self.gap = QSpinBox()
        self.gap.setRange(0, 99999)
        self.gap.setValue(row.combo_gap_ms)
        self.gap.setSuffix(" ms")
        self.gap.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.gap_label = QLabel("组合间隔")
        parameters = QGridLayout()
        parameters.setHorizontalSpacing(10)
        parameters.setVerticalSpacing(10)
        parameters.setColumnStretch(1, 1)
        parameters.setColumnStretch(3, 1)
        for line, column, label, field in (
            (0, 0, self.count_label, self.count),
            (0, 2, self.interval_label, self.interval),
            (1, 0, self.press_label, self.press),
            (1, 2, self.gap_label, self.gap),
        ):
            parameters.addWidget(label, line, column)
            parameters.addWidget(field, line, column + 1)
        layout.addLayout(parameters)
        self.preview = QLabel()
        self.preview.setObjectName("bindingPreview")
        self.preview.setWordWrap(True)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.preview.ensurePolished()
        self.preview.setFixedHeight(self.preview.fontMetrics().lineSpacing() * 2 + 2)
        layout.addWidget(self.preview)
        # Validation shares the explanation slot so errors never resize the dialog.
        self.error = self.preview
        self.passthrough = QCheckBox("触发键原本功能也生效")
        self.passthrough.setChecked(row.pass_original)
        self.passthrough.setToolTip("例如侧键 → C：不勾选时接管侧键；勾选时侧键原功能与 C 都执行。")
        layout.addWidget(self.passthrough)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.count.valueChanged.connect(self.refresh)
        footer = QHBoxLayout()
        self.clear_button = QPushButton("解除绑定")
        self.clear_button.setObjectName("quietButton")
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(self.clear_trigger)
        footer.addWidget(self.clear_button)
        footer.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("保存")
        self.save_button.setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        self.refresh()
        self.ensurePolished()
        layout.activate()
        self.setFixedSize(480, layout.sizeHint().height())

    def set_output(self, binding: InputBinding) -> None:
        self.binding = binding
        self.output_button.set_binding(binding)
        self._error_message = ""
        self.refresh()

    def set_trigger(self, binding: InputBinding) -> None:
        if binding.additional:
            self.set_error("触发键使用单键或鼠标按钮，可附加 Ctrl、Shift、Alt、Win。")
            self.trigger_button.set_binding(self.trigger)
            return
        self.trigger = binding
        self._unbinding = False
        self.trigger_button.set_binding(binding)
        self._error_message = ""
        self.refresh()

    def clear_trigger(self) -> None:
        self.trigger = None
        self._unbinding = True
        self.trigger_button.set_binding(None)
        self._error_message = ""
        self.refresh()

    def refresh(self, *_) -> None:
        if not hasattr(self, "save_button"):
            return
        selected = self.mode.currentData()
        active = not self._unbinding
        self.mode.setEnabled(active)
        self.mode_label.setEnabled(active)
        burst = active and selected == "burst"
        self.count.setEnabled(burst)
        self.count_label.setEnabled(burst)
        repeat = active and (selected == "repeat" or selected == "burst" and self.count.value() > 1)
        self.interval.setEnabled(repeat)
        self.interval_label.setEnabled(repeat)
        tap = active and selected != "hold" and self.sequence is None
        self.press.setEnabled(tap)
        self.press_label.setEnabled(tap)
        combo = active and self.sequence is None and self.binding is not None and len(binding_atoms(self.binding)) > 1
        self.gap.setEnabled(combo)
        self.gap_label.setEnabled(combo)
        self.passthrough.setEnabled(active)
        self.clear_button.setEnabled(self.trigger is not None)
        self.preview.setObjectName("bindingError" if self._error_message else "bindingPreview")
        descriptions = {
            "repeat": "按住触发键期间循环回放，抬起即停止。",
            "burst": f"每次按下触发键回放 {self.count.value()} 次，抬起不打断。",
            "single": "每次按下触发键回放一次。",
        } if self.sequence else {
            "hold": "按下触发键时保持输出，抬起时释放。",
            "repeat": "按住触发键期间连发，抬起即停止。",
            "burst": f"每次按下触发键执行 {self.count.value()} 次，抬起不打断。",
            "single": "每次按下触发键执行一次。",
        }
        description = descriptions[selected] if active else "保存后解除绑定，恢复自动执行。"
        detail = description
        if (self.binding or self.sequence) and self.row.state_button.isChecked():
            entries = self.group_entries()
            for overlap in find_overlaps([config for _, config in entries]):
                if entries[overlap.first][0] is self.row or entries[overlap.second][0] is self.row:
                    other = entries[overlap.second][0] if entries[overlap.first][0] is self.row else entries[overlap.first][0]
                    description += f"\n与{other.row_label}共用{overlap.summary_resource}，按先后执行。"
                    detail += f"\n与{other.row_label}共用{overlap.resource}；等待当前动作完成后执行。"
                    break
        self.preview.setText(self._error_message or description)
        self.preview.setToolTip(self._error_message or detail)
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
        if self._unbinding and not self.trigger_button.capturing:
            self.trigger_button.setText("自动执行 · 点击重新绑定")
        capturing = self.trigger_button.capturing or self.output_button.capturing
        self.save_button.setEnabled((self.binding is not None or self.sequence is not None) and (self.trigger is not None or self._unbinding) and not capturing)

    def set_error(self, message: str) -> None:
        self._error_message = message
        self.refresh()

    def candidate_config(self) -> ActionConfig:
        gap = self.gap.value() if self.binding and len(binding_atoms(self.binding)) > 1 else 0
        selected = self.mode.currentData()
        mode = self.row.automatic_mode if self._unbinding else "burst" if selected == "single" else selected
        count = 1 if selected == "single" or self._unbinding and self.sequence else self.count.value()
        return ActionConfig(self.binding, mode, self.interval.value(), 0 if self.sequence else self.press.value(), self.trigger, count, gap, self.passthrough.isChecked() if self.trigger else False, self.sequence)

    def group_entries(self):
        return [(row, self.candidate_config() if row is self.row else config)
                for row in self.row.owner.actions if (config := row.action_config()) is not None
                or row is self.row and row.state_button.isChecked()]

    def accept(self) -> None:
        if self.trigger_button.capturing or self.output_button.capturing:
            return
        if not self._unbinding and self.trigger is None:
            self.set_error("请先点击触发键，按下要绑定的键。")
            return
        if self.binding is None and self.sequence is None:
            self.set_error("请先录入输出按键或组合。")
            return
        self.config = self.candidate_config()
        try:
            validate_actions([self.config], self.row.owner.window.global_hotkey, labels=[self.row.row_label])
            if self.row.state_button.isChecked():
                entries = self.group_entries()
                validate_actions([config for _, config in entries], self.row.owner.window.global_hotkey,
                                 labels=[row.row_label for row, _ in entries])
        except ValueError as exc:
            self.set_error(str(exc))
            return
        super().accept()

    def done(self, result: int) -> None:
        self.trigger_button.reject()
        self.output_button.reject()
        super().done(result)


class ActionRow(QFrame):
    @property
    def row_label(self) -> str:
        return f"第{self.owner.actions.index(self) + 1}行"

    def __init__(self, owner: "GroupWidget", data: dict | None = None) -> None:
        super().__init__()
        self.owner = owner
        self.binding: InputBinding | None = None
        self.sequence: RecordedSequence | None = None
        self.trigger: InputBinding | None = None
        self.execution_mode = "repeat"
        self.automatic_mode = "repeat"
        self._locked = False
        self.repeat_count = 3
        self.combo_gap_ms = 0
        self.pass_original = False
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
        self.execution_control = execution
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

        self.settings_button = QPushButton("绑")
        self.settings_button.setObjectName("bindButton")
        self.settings_button.setFixedWidth(32)
        self.settings_button.setAccessibleName("绑定按键")
        self.settings_button.setToolTip("绑定触发键")
        self.settings_button.clicked.connect(self.edit_action)
        row.addWidget(self.settings_button)

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

        self.press_field, self.press_spin = press_duration_field()
        self.press_spin.valueChanged.connect(owner.window.schedule_save)
        row.addWidget(self.press_field)

        self.hold_button.toggled.connect(self.update_controls)
        self.repeat_button.toggled.connect(self.update_controls)
        self.state_button.toggled.connect(self.update_controls)
        if data:
            self.load_dict(data)
        self.update_controls()

    def capture_binding(self) -> None:
        if self.sequence:
            from sequence_ui import SequenceEditor
            SequenceEditor(self, BindingCaptureButton, binding_display).exec()
            return
        if self.trigger:
            self.edit_action()
            return
        dialog = CaptureDialog(self, allow_mouse=True, title="录入动作")
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.binding is None:
            return
        previous = self.binding
        self.binding = dialog.binding
        self.refresh_binding()
        if previous is None and self.binding.kind == "mouse" and self.binding.code == "left" and self.interval_spin.value() == 150:
            self.interval_spin.setValue(8)
        self.owner.window.schedule_save()

    def edit_action(self) -> None:
        dialog = ActionEditor(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_action_config(dialog.config)

    def apply_action_config(self, config: ActionConfig, *, enabled: bool | None = None) -> None:
        if self.trigger is None and config.trigger:
            self.automatic_mode = self.execution_mode if self.execution_mode in ("repeat", "hold") or self.sequence else "repeat"
        self.binding, self.trigger = config.binding, config.trigger
        self.sequence = config.sequence
        self.execution_mode = config.mode
        if self.trigger is None:
            self.automatic_mode = config.mode
        self.repeat_count, self.combo_gap_ms, self.pass_original = config.repeat_count, config.combo_gap_ms, config.pass_original
        with QSignalBlocker(self.hold_button), QSignalBlocker(self.repeat_button), QSignalBlocker(self.state_button):
            self._modes.setExclusive(self.sequence is None)
            self.hold_button.setChecked(self.automatic_mode == "hold")
            self.repeat_button.setChecked(self.automatic_mode == "repeat" if self.sequence else self.automatic_mode != "hold")
            if enabled is not None:
                self.state_button.setChecked(enabled)
        self.interval_spin.setValue(config.interval_ms)
        self.press_spin.setValue(config.press_ms)
        self.update_controls()
        self.refresh_binding()

    def apply_sequence(self, sequence: RecordedSequence) -> None:
        self.sequence = sequence.validate()
        self.binding = None
        self.press_spin.setRange(0, 86_400_000)
        self.press_spin.setValue(round(sequence.playback_timing.duration_us / 1000))
        self.update_controls()

    def refresh_binding(self) -> None:
        output = self.sequence.name if self.sequence else binding_display(self.binding) if self.binding else "未设置按键"
        label = f"{binding_display(self.trigger)} → {output}" if self.trigger else output
        if self.trigger:
            label += " · 循环" if self.sequence and self.execution_mode in ("repeat", "hold") else " · 跟随" if self.execution_mode == "hold" else " · 连发" if self.execution_mode == "repeat" else " · 单次" if self.repeat_count == 1 else f" ×{self.repeat_count} · 短发"
        self.record_button.setText(label)
        self.record_button.setToolTip(f"{label}；点击查看、编辑录制步骤" if self.sequence else f"{label}；点击编辑绑定" if self.trigger else "点击录入输出，点“绑”设置触发键")
        self.settings_button.setProperty("bound", self.trigger is not None)
        self.settings_button.setToolTip("编辑绑定；随总开关启用" if self.trigger else "绑定触发键")
        self.settings_button.style().unpolish(self.settings_button)
        self.settings_button.style().polish(self.settings_button)

    def update_controls(self) -> None:
        bound = self.trigger is not None
        if not bound:
            self.execution_mode = ("repeat" if self.repeat_button.isChecked() else "burst") if self.sequence else "hold" if self.hold_button.isChecked() else "repeat"
            self.automatic_mode = self.execution_mode
            if self.sequence:
                self.repeat_count = 1
        self.repeat_button.setText("循环" if self.sequence else "间隔")
        self.repeat_button.setToolTip("已绑定，只由触发键执行；自动模式不生效" if bound else "勾选循环；取消后仅回放一次" if self.sequence else "按间隔自动执行")
        self.refresh_binding()
        enabled = self.state_button.isChecked()
        self.state_button.setText("启" if enabled else "停")
        self.execution_control.setEnabled(not self._locked)
        self.state_button.setEnabled(not self._locked)
        self.state_button.setToolTip("启用或停用这一条动作；随总开关执行")
        self.repeat_button.setEnabled(enabled and not bound and not self._locked)
        self.hold_button.setEnabled(enabled and not bound and not self._locked and self.sequence is None)
        self.record_button.setEnabled(enabled and not self._locked)
        self.settings_button.setEnabled(not self._locked)
        taps = self.execution_mode != "hold"
        repeating = self.execution_mode == "repeat" or self.execution_mode == "burst" and self.repeat_count > 1
        self.interval_field.setEnabled(enabled and repeating and not self._locked)
        self.press_field.setEnabled(enabled and taps and not self._locked)
        self.press_spin.setReadOnly(self.sequence is not None)
        self.interval_field.setToolTip("每次完整回放之后等待的时间" if self.sequence else "按下到下一次按下的间隔")
        if self.sequence:
            self.interval_spin.setMinimum(0)
            self.press_spin.setRange(0, 86_400_000)
            self.press_spin.setValue(round(self.sequence.playback_timing.duration_us / 1000))
            self.press_field.setToolTip(f"回放时长；原录制 {self.sequence.duration_us / 1000:g} ms，加速 {self.sequence.movement_speed:g}×。点击录制名称调整。")
        else:
            self.press_field.setToolTip("一次点按从按下到松开的持续时间")
        for label in self.press_field.findChildren(QLabel):
            if label.text() in ("持续", "时长"):
                label.setText("时长" if self.sequence else "持续")
        self.owner.window.schedule_save()

    def action_config(self) -> ActionConfig | None:
        if not self.state_button.isChecked() or self.binding is None and self.sequence is None:
            return None
        return ActionConfig(self.binding, self.execution_mode, self.interval_spin.value(), 0 if self.sequence else self.press_spin.value(), self.trigger, self.repeat_count, self.combo_gap_ms, self.pass_original, self.sequence)

    def to_dict(self) -> dict:
        return {
            "enabled": self.state_button.isChecked(),
            "mode": self.execution_mode,
            "automatic_mode": self.automatic_mode,
            "interval_ms": self.interval_spin.value(),
            "press_ms": self.press_spin.value(),
            "binding": self.binding.to_dict() if self.binding else None,
            "trigger": self.trigger.to_dict() if self.trigger else None,
            "repeat_count": self.repeat_count,
            "combo_gap_ms": self.combo_gap_ms,
            "pass_original": self.pass_original,
            "sequence": self.sequence.to_dict() if self.sequence else None,
        }

    def load_dict(self, data: dict) -> None:
        try:
            self.sequence = RecordedSequence.from_dict(data["sequence"]) if data.get("sequence") is not None else None
        except (ValueError, TypeError, KeyError):
            self.sequence = None
            data = {**data, "binding": None, "trigger": None, "enabled": False}
        binding = InputBinding.from_dict(data.get("binding"))
        self.binding = binding
        if self.sequence:
            self.binding = None
        trigger_raw = data.get("trigger")
        self.trigger = InputBinding.from_dict(trigger_raw)
        if trigger_raw is not None and (self.trigger is None or self.trigger.additional):
            self.trigger = None
            self.binding = None
            self.sequence = None
        self.execution_mode = data.get("mode", "repeat")
        if self.execution_mode not in ("repeat", "hold", "burst") or self.execution_mode == "burst" and not self.trigger and not self.sequence:
            if self.execution_mode == "burst":
                self.binding = None
            self.execution_mode = "repeat"
        automatic_mode = data.get("automatic_mode")
        self.automatic_mode = automatic_mode if automatic_mode in (("repeat", "burst") if self.sequence else ("repeat", "hold")) else self.execution_mode if self.trigger is None else "burst" if self.sequence else "repeat"
        count, gap = data.get("repeat_count", 3), data.get("combo_gap_ms", 0)
        self.repeat_count = max(1, min(999, count)) if isinstance(count, int) and not isinstance(count, bool) else 3
        self.combo_gap_ms = max(0, min(99999, gap)) if isinstance(gap, int) and not isinstance(gap, bool) else 0
        self.pass_original = data.get("pass_original") is True
        if binding is not None:
            self.record_button.setText(binding_display(binding))
        try:
            interval = int(data.get("interval_ms", 150))
        except (TypeError, ValueError):
            interval = 150
        self.interval_spin.setMinimum(0 if self.sequence else 1)
        self.interval_spin.setValue(interval)
        duration = data.get("press_ms", DEFAULT_PRESS_MS)
        self.press_spin.setRange(0, 86_400_000 if self.sequence else 99999)
        self.press_spin.setValue(duration if isinstance(duration, int) and not isinstance(duration, bool) else DEFAULT_PRESS_MS)
        with QSignalBlocker(self.hold_button), QSignalBlocker(self.repeat_button), QSignalBlocker(self.state_button):
            self._modes.setExclusive(self.sequence is None)
            self.hold_button.setChecked(self.automatic_mode == "hold")
            self.repeat_button.setChecked(self.automatic_mode == "repeat" if self.sequence else self.automatic_mode != "hold")
            self.state_button.setChecked(bool(data.get("enabled", True)))
        self.update_controls()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.drag_handle.setDisabled(locked)
        self.remove_button.setDisabled(locked)
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
        self.name_button.setEnabled(True)
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
        self.setWindowTitle(APP_TITLE)
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
        self.recorder = None
        self._recording_group = None
        self._recording_started = 0.0
        self._last_control_stop = float("-inf")
        self._last_control_stop_tick = None
        self._last_hotkey_stamp = None
        self.global_hotkey = InputBinding("keyboard", 0x77, 0, "F8")
        self.input_mode = "原生"
        self.target_window: WindowInfo | None = None
        self.ahk_path = str(self._settings.value("runtime/ahk_path", "") or "")
        self.bridge = UiBridge(self)
        self.bridge.execution_error.connect(self.execution_failed)
        self.bridge.execution_stopped.connect(self.stop_execution)
        self.bridge.recording_finished.connect(self.finish_recording)
        self.bridge.recording_error.connect(self.recording_failed)
        self.native_scheduler = NativeScheduler(lambda message: self.bridge.execution_error.emit(message), on_stopped=self.bridge.execution_stopped.emit)
        self.ahk_runner = AhkRunner()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self.save_configuration)
        self.shutdown_countdown = ShutdownCountdown(execute=self.perform_shutdown)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(1000)
        self._shutdown_timer.timeout.connect(self.update_shutdown)
        self._recording_timer = QTimer(self)
        self._recording_timer.setInterval(250)
        self._recording_timer.timeout.connect(self.update_recording)

        self.setMinimumSize(QSize(740, 250))
        saved_geometry = self._settings.value("window/geometry")
        if saved_geometry is None or not self.restoreGeometry(saved_geometry):
            self.resize(740, 420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if os.environ.get("QINGYUN_RUNTIME_CACHE"):
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self.show_cache_menu)

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
        heading.addSpacing(116)
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

        self.recording_button = QPushButton("录制动作")
        self.recording_button.setFixedWidth(80)
        self.recording_button.setObjectName("shutdownButton")
        self.recording_button.setToolTip("3秒后录制；再次点击、F9或总启停键结束，保存到当前动作组")
        self.recording_button.clicked.connect(self.toggle_recording)
        controls.addWidget(self.recording_button)
        self.shutdown_button = QPushButton("定时关机")
        self.shutdown_button.setObjectName("shutdownButton")
        self.shutdown_button.setMinimumWidth(128)
        self.shutdown_button.setToolTip("设置多少分钟后关机；再次点击取消，退出软件也会取消")
        self.shutdown_button.clicked.connect(self.toggle_shutdown)
        controls.addWidget(self.shutdown_button)
        controls.addStretch(1)

        global_label = QLabel("总启停")
        global_label.setObjectName("globalLabel")
        controls.addWidget(global_label)
        self.hotkey_button = QPushButton("F8")
        self.hotkey_button.setObjectName("hotkeyButton")
        self.hotkey_button.setFixedWidth(72)
        self.hotkey_button.setToolTip("点击后录入新的全局启动/停止按键")
        self.hotkey_button.clicked.connect(self.capture_global_hotkey)
        controls.addWidget(self.hotkey_button)

        self.start_button = QPushButton("启动")
        self.start_button.setToolTip("启动当前组：自动动作执行，绑定动作监听；重复输出按先后执行")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setProperty("launch", True)
        self.start_button.clicked.connect(self.toggle_execution)
        controls.addWidget(self.start_button)
        main.addLayout(controls)

        self.load_configuration()
        self._loading = False
        self.setFocus()

    def show_cache_menu(self, position):
        menu = QMenu(self)
        folder = menu.addAction("打开运行缓存目录")
        clear = menu.addAction("清理运行缓存并退出")
        chosen = menu.exec(self.mapToGlobal(position))
        if chosen == folder:
            os.startfile(os.environ["QINGYUN_RUNTIME_CACHE"])
        elif chosen == clear:
            launcher = os.environ.get("QINGYUN_LAUNCHER_PATH")
            wrapper = os.environ.get("QINGYUN_WRAPPER_PID")
            if launcher and wrapper:
                try:
                    subprocess.Popen([launcher, "--clear-cache-after", wrapper], creationflags=subprocess.CREATE_NO_WINDOW)
                    self.close()
                except OSError as exc:
                    QMessageBox.warning(self, "无法清理缓存", str(exc))

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
        self.finish_recording()
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
        if group not in self.groups:
            return
        if self.recorder:
            if group is self.active_group:
                return
            self.finish_recording()
        if self._running:
            if group is self.active_group:
                return
            self.stop_execution()
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
                stamp = int(msg.time)
                if stamp == self._last_hotkey_stamp:
                    return True, 0
                self._last_hotkey_stamp = stamp
                if self.recorder:
                    QTimer.singleShot(0, self.finish_recording)
                elif self._running:
                    QTimer.singleShot(0, self.stop_execution)
                else:
                    modal = QApplication.activeModalWidget()
                    if modal is not None and getattr(modal, "_previewing", False):
                        QTimer.singleShot(0, modal.preview)
                    elif modal is None and (self._last_control_stop_tick is None or
                        0 < ((stamp - self._last_control_stop_tick) & 0xFFFFFFFF) < 0x80000000):
                        QTimer.singleShot(0, self.start_execution)
                return True, 0
        except (TypeError, ValueError):
            pass
        return super().nativeEvent(event_type, message)

    def toggle_execution(self) -> None:
        if self.recorder:
            self.finish_recording()
            return
        if self._running:
            self.stop_execution()
        else:
            self.start_execution()

    def start_execution(self) -> None:
        if self.recorder:
            return
        group = self.active_group
        if group is None:
            return
        entries = [(row, config) for row in group.actions if (config := row.action_config()) is not None]
        actions = [config for _, config in entries]
        if not actions:
            QMessageBox.information(self, "无法启动", "当前动作组没有已设置且启用的动作。")
            return
        try:
            validate_actions(actions, self.global_hotkey, labels=[row.row_label for row, _ in entries],
                             allow_overlap=self.input_mode == "原生")
            if self.input_mode != "原生" and any(action.sequence or action.trigger or action.mode == "burst" or action.combo_gap_ms for action in actions):
                QMessageBox.information(self, "输入方式", "录制回放、绑定、短连发和组合间隔请使用原生输入。")
                return
            if self.input_mode == "原生":
                self.native_scheduler.start(actions, stop_binding=self.global_hotkey)
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

    def play_sequence(self, config: ActionConfig) -> bool:
        if self.recorder:
            return False
        self.stop_execution()
        try:
            self.native_scheduler.start([config], stop_binding=self.global_hotkey)
        except Exception as exc:
            QMessageBox.warning(self, "无法试放", str(exc))
            return False
        self._running = True
        self.set_running_ui(True)
        return True

    def toggle_recording(self) -> None:
        if self.recorder:
            self.finish_recording()
            return
        if self.input_mode != "原生":
            QMessageBox.information(self, "输入方式", "全屏录制和回放请使用原生输入。")
            return
        self.stop_execution()
        recorder = NativeRecorder(self.bridge.recording_finished.emit, self.bridge.recording_error.emit,
                                  stop_binding=self.global_hotkey, start_delay_seconds=RECORDING_START_DELAY_SECONDS)
        try:
            recorder.start()
        except Exception as exc:
            QMessageBox.critical(self, "无法录制", str(exc))
            return
        self.recorder = recorder
        self._recording_group = self.active_group
        self._recording_started = getattr(recorder, "capture_start_seconds", time.perf_counter() + RECORDING_START_DELAY_SECONDS)
        self.recording_button.setProperty("active", True)
        self.recording_button.style().unpolish(self.recording_button)
        self.recording_button.style().polish(self.recording_button)
        self.set_running_ui(False)
        self._recording_timer.start()
        self.update_recording()

    def update_recording(self) -> None:
        if self.recorder and self._recording_group:
            elapsed = time.perf_counter() - self._recording_started
            if elapsed < 0:
                remaining = math.ceil(-elapsed)
                self.recording_button.setText(f"{remaining}s")
                return
            self.recording_button.setText("停止录制")
            seconds = int(elapsed)
            minutes, seconds = divmod(seconds, 60)
            self._recording_group.count_label.setText(f"录制 {minutes:02d}:{seconds:02d}")
            self.setWindowTitle(f"{APP_TITLE} — 录制中 · F9停止")

    def finish_recording(self) -> None:
        recorder = self.recorder
        if recorder is None:
            return
        group = self._recording_group
        number = sum(row.sequence is not None for row in group.actions) + 1 if group else 1
        if group:
            names = {row.sequence.name for row in group.actions if row.sequence}
            while f"录制 {number}" in names:
                number += 1
        try:
            sequence = recorder.finish(f"录制 {number}")
        except Exception as exc:
            # Preserve the live recorder reference if its thread could not stop.
            QMessageBox.critical(self, "停止录制失败", str(exc))
            return
        self.recorder = None
        self._last_control_stop = time.perf_counter()
        self._last_control_stop_tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        self._recording_group = None
        self._recording_timer.stop()
        self.recording_button.setText("录制动作")
        self.recording_button.setProperty("active", False)
        self.recording_button.style().unpolish(self.recording_button)
        self.recording_button.style().polish(self.recording_button)
        self.set_running_ui(False)
        if group in self.groups:
            if sequence:
                group.add_action({"sequence": sequence.to_dict(), "binding": None, "mode": "burst",
                                  "automatic_mode": "burst", "repeat_count": 1, "enabled": True,
                                  "interval_ms": 1000, "press_ms": 0})
            group.refresh_count()
        self.save_configuration()

    def recording_failed(self, message: str) -> None:
        if self.recorder:
            self.finish_recording()
            QMessageBox.warning(self, "录制已停止", message)

    def stop_execution(self) -> None:
        if self._running:
            self._last_control_stop = time.perf_counter()
            self._last_control_stop_tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        self.native_scheduler.stop()
        self.ahk_runner.stop()
        self._running = False
        self.set_running_ui(False)

    def execution_failed(self, message: str) -> None:
        self.stop_execution()
        QMessageBox.critical(self, "执行已停止", message)

    def set_running_ui(self, running: bool) -> None:
        self.start_button.setText("停止" if running else "启动")
        self.setWindowTitle(f"{APP_TITLE} — {self.active_group.name}运行中" if running and self.active_group else APP_TITLE)
        locked = running or self.recorder is not None
        for button in self.engine_buttons.values():
            button.setDisabled(locked)
        self.target_button.setDisabled(locked)
        self.add_action_button.setDisabled(locked)
        self.add_group_button.setDisabled(locked)
        self.import_button.setDisabled(locked)
        self.hotkey_button.setDisabled(locked)
        self.start_button.setDisabled(self.recorder is not None)
        for group in self.groups:
            group.set_locked(locked)

    def configuration_dict(self) -> dict:
        active_index = self.groups.index(self.active_group) if self.active_group in self.groups else 0
        return {
            "version": 2 if any(row.sequence for group in self.groups for row in group.actions) else 1,
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
            if not isinstance(data, dict) or data.get("version") not in (1, 2) or not isinstance(data.get("groups"), list):
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
        self.finish_recording()
        if self.recorder:
            event.ignore()
            return
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
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
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
            ready_at = time.perf_counter()

            def finish_smoke():
                try:
                    assert window.isVisible()
                    assert window.groups[0].actions[0].interval_spin.value() == 2000
                    assert window.groups[0].actions[0].press_spin.value() == DEFAULT_PRESS_MS
                    assert window.windowTitle() == APP_TITLE
                    assert window.shutdown_button.text() == "定时关机"
                    assert window.recording_button.text() == "录制动作"
                    row = window.groups[0].actions[0]
                    assert row.settings_button.text() == "绑"
                    row.apply_action_config(ActionConfig(InputBinding("keyboard", 0x43, additional=(InputAtom("mouse", "right"),)), "hold", 2000, trigger=InputBinding("mouse", "x1"), combo_gap_ms=25))
                    assert row.execution_control.isEnabled() and row.state_button.isEnabled()
                    assert not row.repeat_button.isEnabled() and not row.hold_button.isEnabled()
                    assert row.settings_button.isEnabled()
                    editor = ActionEditor(row)
                    editor.show()
                    app.processEvents()
                    assert editor.save_button.isEnabled()
                    assert not editor.interval.isEnabled() and not editor.press.isEnabled()
                    assert editor.grab().save(str(report.with_name(report.stem + ".binding.png")))
                    editor.reject()
                    assert window.grab().save(str(report.with_suffix(".png")))
                    from recording_models import RecordedEvent
                    from sequence_ui import SequenceEditor
                    from wininput import desktop_bounds
                    sequence = RecordedSequence("录制 1", (RecordedEvent(0, "key", 0x41, True), RecordedEvent(50_000, "key", 0x41, False)), 150_000, screen_bounds=desktop_bounds())
                    window.groups[0].add_action({"sequence": sequence.to_dict(), "mode": "burst", "automatic_mode": "burst", "repeat_count": 1})
                    recorded_row = window.groups[0].actions[-1]
                    assert recorded_row.sequence == sequence and recorded_row.press_spin.isReadOnly()
                    sequence_editor = SequenceEditor(recorded_row, BindingCaptureButton, binding_display)
                    sequence_editor.show()
                    app.processEvents()
                    assert sequence_editor.table.rowCount() == 1
                    sequence_editor.capture.set_binding(InputBinding("keyboard", 0x42))
                    sequence_editor.insert_step()
                    assert sequence_editor.table.rowCount() == 2 and sequence_editor.sequence.can_restore
                    assert sequence_editor.table.item(1, 0).data(Qt.ItemDataRole.UserRole) == "inserted"
                    sequence_editor.undo()
                    assert sequence_editor.sequence == sequence
                    sequence_editor.redo()
                    modified = sequence_editor.sequence
                    sequence_editor.restore()
                    assert sequence_editor.sequence.events == sequence.events
                    sequence_editor.undo()
                    assert sequence_editor.sequence == modified
                    sequence_editor.table.selectRow(1)
                    app.processEvents()
                    assert sequence_editor.grab().save(str(report.with_name(report.stem + ".recording.png")))
                    sequence_editor.reject()
                    from recording_tail import TailCut, trim_recording_tail
                    raw_sequence = RecordedSequence("录制 1", (
                        RecordedEvent(0, "key", 0x41, True), RecordedEvent(50_000, "key", 0x41, False),
                        RecordedEvent(100_000, "key", 0xA4, True), RecordedEvent(120_000, "key", 0x09, True),
                        RecordedEvent(140_000, "key", 0x09, False), RecordedEvent(160_000, "key", 0xA4, False),
                    ), 500_000, screen_bounds=desktop_bounds()).validate()
                    trimmed = trim_recording_tail(raw_sequence, TailCut(2, 100_000_000), 0)
                    assert trimmed.duration_us == 100_000 and trimmed.can_restore
                    recorded_row.apply_action_config(ActionConfig(None, "burst", 1000, repeat_count=1, sequence=trimmed))
                    tail_editor = SequenceEditor(recorded_row, BindingCaptureButton, binding_display)
                    tail_editor.show()
                    app.processEvents()
                    assert tail_editor.restore_button.isEnabled()
                    assert tail_editor.grab().save(str(report.with_name(report.stem + ".trimmed.png")))
                    tail_editor.restore()
                    assert tail_editor.sequence.events == raw_sequence.events
                    tail_editor.undo()
                    assert tail_editor.sequence == trimmed
                    tail_editor.reject()
                    assert recorded_row.sequence == trimmed
                    speed_events = tuple(RecordedEvent(i * 50_000, "move", x=100 + i * 10, y=200)
                                         for i in range(17)) + (
                        RecordedEvent(900_000, "button", "left", True, 260, 200),
                        RecordedEvent(980_000, "button", "left", False, 260, 200),
                        RecordedEvent(1_600_000, "key", 0x57, True),
                        RecordedEvent(1_650_000, "move", x=300, y=200),
                        RecordedEvent(1_700_000, "move", x=350, y=200),
                        RecordedEvent(1_800_000, "key", 0x57, False),
                        RecordedEvent(1_900_000, "wheel", x=350, y=200, delta=120),
                    )
                    speed_sequence = RecordedSequence("录制 1", speed_events, 2_000_000, screen_bounds=desktop_bounds()).validate()
                    recorded_row.apply_action_config(ActionConfig(None, "burst", 1000, repeat_count=1, sequence=speed_sequence))
                    speed_editor = SequenceEditor(recorded_row, BindingCaptureButton, binding_display)
                    speed_editor.show()
                    app.processEvents()
                    speed_geometry = speed_editor.size()
                    speed_editor.speed.setCurrentIndex(speed_editor.speed.findData(2))
                    app.processEvents()
                    assert speed_editor.size() == speed_geometry
                    assert speed_editor.sequence.events == speed_sequence.events
                    assert speed_editor.sequence.playback_timing.duration_us == 1_600_000
                    assert speed_editor.summary.text() == "2.00→1.60 秒"
                    assert speed_editor.grab().save(str(report.with_name(report.stem + ".speed.png")))
                    speed_editor.accept()
                    assert recorded_row.press_spin.value() == 1600
                    recorded_row.apply_action_config(ActionConfig(None, "burst", 1000, repeat_count=1, sequence=trimmed))
                    window.groups[0].add_action()
                    window.groups[0].actions[-1].apply_action_config(ActionConfig(InputBinding("keyboard", 0x43), "repeat", 150))
                    mixed_editor = ActionEditor(row)
                    mixed_editor.show()
                    app.processEvents()
                    assert "共用C" in mixed_editor.preview.text()
                    assert mixed_editor.grab().save(str(report.with_name(report.stem + ".mixed.png")))
                    mixed_editor.accept()
                    assert mixed_editor.result() == QDialog.DialogCode.Accepted
                    # Exercise the actual countdown UI with isolated data and no hooks.
                    class SmokeRecorder:
                        def __init__(self, *args, **kwargs):
                            assert kwargs["start_delay_seconds"] == 3
                            self.capture_start_seconds = time.perf_counter() + 3
                        def start(self): pass
                        def finish(self, name): return None
                    recorder_type = globals()["NativeRecorder"]
                    geometry = window.recording_button.geometry()
                    action_count = len(window.active_group.actions)
                    countdown_labels = []
                    try:
                        globals()["NativeRecorder"] = SmokeRecorder
                        window.toggle_recording()
                        for remaining, expected in ((3, "3s"), (2, "2s"), (1, "1s"), (0, "停止录制")):
                            window._recording_started = time.perf_counter() + remaining - .25
                            window.update_recording()
                            app.processEvents()
                            assert window.recording_button.text() == expected
                            assert window.recording_button.geometry() == geometry
                            countdown_labels.append(expected)
                            assert window.grab().save(str(report.with_name(report.stem + f".countdown-{remaining}.png")))
                        window.finish_recording()
                        assert window.recording_button.text() == "录制动作"
                        assert window.start_button.isEnabled() and not window._recording_timer.isActive()
                        assert len(window.active_group.actions) == action_count
                    finally:
                        globals()["NativeRecorder"] = recorder_type
                    report.write_text(json.dumps({"ok": True, "platform": app.platformName(), "frozen": bool(getattr(sys, "frozen", False)), "version": app.applicationVersion(), "default_press_ms": window.groups[0].actions[0].press_spin.value(), "size": [window.width(), window.height()], "ready_perf_counter": ready_at, "mixed_rules_checked": True, "recording_delay_checked": True, "recording_tail_checked": True, "recording_speed_checked": True, "countdown_labels": countdown_labels }), encoding="utf-8")
                    window.close()
                    app.exit(0)
                except Exception as exc:
                    import traceback
                    report.write_text(json.dumps({"ok": False, "error": str(exc), "traceback": traceback.format_exc()}), encoding="utf-8")
                    app.exit(1)

            QTimer.singleShot(700, finish_smoke)
            return app.exec()
    window = ClickerShell()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
