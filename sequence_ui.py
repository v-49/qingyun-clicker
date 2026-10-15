"""A compact timeline editor for a recording already stored in an action group."""
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QComboBox, QDialog, QDialogButtonBox,
                              QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                              QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QStyledItemDelegate,
                              QStyle, QStyleOptionViewItem)

from models import ActionConfig, InputBinding
from recording_models import insert_press, paired_span, remove_events, preserve_original, restore_original
from wininput import binding_atoms


def number(maximum, value=0, suffix=" ms"):
    field = QSpinBox()
    field.setRange(0, maximum)
    field.setValue(value)
    field.setSuffix(suffix)
    field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    return field


INSERTED_BACKGROUND = "#fff3d7"
INSERTED_SELECTED = "#ffe1a0"
INSERTED_FOREGROUND = "#77501c"


class InsertedStepDelegate(QStyledItemDelegate):
    """Preserve native recorded rows; inserted rows retain their hue when selected."""
    def paint(self, painter, option, index):
        if index.data(Qt.ItemDataRole.UserRole) != "inserted":
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.fillRect(styled.rect, QColor(INSERTED_SELECTED if selected else INSERTED_BACKGROUND))
        painter.setPen(QColor(INSERTED_FOREGROUND))
        painter.setFont(styled.font)
        rect = styled.rect.adjusted(6, 0, -6, 0)
        text = styled.fontMetrics.elidedText(styled.text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class SequenceEditor(QDialog):
    def __init__(self, row, capture_class, display):
        super().__init__(row)
        self.row, self.sequence, self.display = row, row.sequence, display
        self._previewing = False
        self._undo = []
        self._redo = []
        self.entries = []
        self.setWindowTitle("编辑录制")
        self.setObjectName("sequenceEditor")
        self.resize(710, 520)
        self.setMinimumSize(650, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.name = QLineEdit(self.sequence.name)
        self.name.setMaxLength(200)
        self.name.editingFinished.connect(self.rename)
        top.addWidget(QLabel("名称"))
        top.addWidget(self.name, 1)
        self.pointer = QComboBox()
        self.pointer.addItem("屏幕位置", "screen")
        self.pointer.addItem("相对移动", "relative")
        self.pointer.setCurrentIndex(1 if self.sequence.pointer_mode == "relative" else 0)
        self.pointer.setToolTip("屏幕位置：按录制坐标移动。相对移动：按鼠标位移回放，适合锁定鼠标的游戏。")
        self.pointer.currentIndexChanged.connect(self.select_pointer)
        top.addWidget(QLabel("鼠标"))
        top.addWidget(self.pointer)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "动作", "内容 / 位置", "持续"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setItemDelegate(InsertedStepDelegate(self.table))
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 85)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(3, 85)
        self.table.itemSelectionChanged.connect(self.select_step)
        layout.addWidget(self.table, 1)

        edit = QHBoxLayout()
        self.at = number(86_400_000)
        self.duration = number(86_400_000)
        self.x = number(1_000_000, suffix="")
        self.x.setMinimum(-1_000_000)
        self.y = number(1_000_000, suffix="")
        self.y.setMinimum(-1_000_000)
        for label, field in (("时间", self.at), ("持续", self.duration), ("X", self.x), ("Y", self.y)):
            edit.addWidget(QLabel(label))
            edit.addWidget(field)
        self.apply = QPushButton("修改")
        self.apply.clicked.connect(self.apply_step)
        edit.addWidget(self.apply)
        self.delete = QPushButton("删除")
        self.delete.clicked.connect(self.delete_step)
        edit.addWidget(self.delete)
        layout.addLayout(edit)

        insert = QGridLayout()
        self.capture = capture_class(None, single=False)
        self.capture.setText("点击录入插入按键")
        insert.addWidget(self.capture, 0, 0, 1, 2)
        self.insert_duration = number(99999, 50)
        self.count = number(999, 1, " 次")
        self.count.setMinimum(1)
        self.interval = number(99999, 150)
        for column, label, field in ((2, "持续", self.insert_duration), (4, "次数", self.count), (6, "间隔", self.interval)):
            insert.addWidget(QLabel(label), 0, column)
            insert.addWidget(field, 0, column + 1)
        self.insert = QPushButton("插入")
        self.insert.setToolTip("插到选中步骤之前；未选中时追加到录制末尾。")
        self.insert.clicked.connect(self.insert_step)
        insert.addWidget(self.insert, 0, 8)
        layout.addLayout(insert)
        self.error = QLabel()
        self.error.setObjectName("bindingPreview")
        self.error.setWordWrap(True)
        self.error.setMinimumHeight(20)
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.play = QPushButton("单次试放")
        self.play.setToolTip("3 秒后开始，使用总启停快捷键也可停止。")
        self.play.clicked.connect(self.preview)
        footer.addWidget(self.play)
        self.summary = QLabel()
        footer.addWidget(self.summary)
        footer.addStretch(1)
        self.undo_button = QPushButton("撤销")
        self.undo_button.setToolTip("撤销上一步修改（Ctrl+Z）")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("重做")
        self.redo_button.setToolTip("重做已撤销的修改（Ctrl+Y）")
        self.redo_button.clicked.connect(self.redo)
        self.restore_button = QPushButton("还原录制")
        self.restore_button.setToolTip("恢复最初的录制步骤和时间，移除插入及修改；本次还原也可撤销")
        self.restore_button.clicked.connect(self.restore)
        for button in (self.undo_button, self.redo_button, self.restore_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save.setText("保存")
        self.save.setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.update_preview)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self.begin_preview)
        self.refresh()

    def select_pointer(self):
        mode = self.pointer.currentData()
        self.change(replace(self.sequence, pointer_mode=mode))
        if mode == "relative" and not any(e.kind == "relative" for e in self.sequence.events):
            self.error.setText("这段录制没有相对位移，鼠标移动将不回放，按键和按钮仍会回放。")
        else:
            self.error.clear()

    def rename(self):
        name = self.name.text().strip()
        if name and name != self.sequence.name and not self._previewing:
            self.change(replace(self.sequence, name=name))

    def refresh(self):
        self.entries = []
        events = self.sequence.events
        used = set()
        i = 0
        while i < len(events):
            event = events[i]
            if i in used or event.key and not event.pressed:
                i += 1
                continue
            if event.kind in ("move", "relative"):
                indexes = []
                while i < len(events) and events[i].kind in ("move", "relative"):
                    indexes.append(i)
                    i += 1
                visible = [index for index in indexes if events[index].kind == ("move" if self.sequence.pointer_mode == "screen" else "relative")]
                if not visible:
                    continue
                first, last = events[visible[0]], events[visible[-1]]
                content = f"{len(visible)} 个点 · ({first.x}, {first.y}) → ({last.x}, {last.y})"
                self.entries.append((indexes, first, last.t_us - first.t_us, "鼠标轨迹", content))
                continue
            if event.key:
                indexes = paired_span(events, i)
                used.update(indexes)
                kind = "keyboard" if event.kind == "key" else "mouse"
                content = self.display(InputBinding(kind, event.code))
                if event.kind == "button":
                    content += f" · ({event.x}, {event.y})"
                repeats = len(indexes) - 2
                if repeats:
                    content += f" · 系统重复 {repeats} 次"
                duration = events[indexes[-1]].t_us - event.t_us
                self.entries.append((indexes, event, duration, "按键" if kind == "keyboard" else "鼠标按钮", content))
            else:
                self.entries.append(([i], event, 0, "横向滚轮" if event.horizontal else "滚轮", f"{event.delta:+d} · ({event.x}, {event.y})"))
            i += 1
        self.table.setRowCount(len(self.entries))
        for index, (_, event, duration, kind, content) in enumerate(self.entries):
            if event.origin == "inserted":
                kind = "插入按键" if event.kind == "key" else "插入按钮"
            for column, text in enumerate((f"{event.t_us / 1000:g} ms", kind, content, f"{duration / 1000:g} ms" if duration else "—")):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, event.origin)
                if event.origin == "inserted":
                    item.setBackground(QBrush(QColor(INSERTED_BACKGROUND)))
                    item.setForeground(QBrush(QColor(INSERTED_FOREGROUND)))
                    item.setToolTip("新插入的动作")
                self.table.setItem(index, column, item)
        self.summary.setText(f"{len(self.entries)} 步 · {self.sequence.duration_us / 1_000_000:.2f} 秒")
        self.select_step()
        self.update_history()

    def selected(self):
        index = self.table.currentRow()
        return self.entries[index] if 0 <= index < len(self.entries) else None

    def select_step(self):
        entry = self.selected()
        for field in (self.at, self.apply, self.delete):
            field.setEnabled(bool(entry) and not self._previewing)
        if not entry:
            self.duration.setDisabled(True)
            self.x.setDisabled(True)
            self.y.setDisabled(True)
            return
        indexes, event, duration, _, _ = entry
        self.at.setValue(round(event.t_us / 1000))
        self.duration.setValue(round(duration / 1000))
        self.duration.setEnabled(bool(event.key) and not self._previewing)
        coordinate = event.kind in ("button", "wheel")
        self.x.setEnabled(coordinate and not self._previewing)
        self.y.setEnabled(coordinate and not self._previewing)
        self.x.setValue(event.x)
        self.y.setValue(event.y)

    def change(self, sequence):
        if self._previewing:
            return False
        if sequence == self.sequence:
            return True
        if sequence.original_events is None and (sequence.events != self.sequence.events or sequence.duration_us != self.sequence.duration_us):
            original = preserve_original(self.sequence)
            sequence = replace(sequence, original_events=original.original_events,
                               original_duration_us=original.original_duration_us)
        try:
            sequence.validate()
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        self._undo.append(self.sequence)
        if len(self._undo) > 32:
            self._undo.pop(0)
        self._redo.clear()
        self.sequence = sequence
        self.error.clear()
        self.refresh()
        return True

    def update_history(self):
        self.undo_button.setEnabled(bool(self._undo) and not self._previewing)
        self.redo_button.setEnabled(bool(self._redo) and not self._previewing)
        self.restore_button.setEnabled(self.sequence.can_restore and not self._previewing)

    def show_snapshot(self, sequence):
        self.sequence = sequence
        with QSignalBlocker(self.name), QSignalBlocker(self.pointer):
            self.name.setText(sequence.name)
            self.pointer.setCurrentIndex(self.pointer.findData(sequence.pointer_mode))
        self.error.clear()
        self.refresh()

    def undo(self):
        if self._undo and not self._previewing:
            self._redo.append(self.sequence)
            self.show_snapshot(self._undo.pop())

    def redo(self):
        if self._redo and not self._previewing:
            self._undo.append(self.sequence)
            self.show_snapshot(self._redo.pop())

    def restore(self):
        if self.sequence.can_restore and not self._previewing:
            self.change(restore_original(self.sequence))

    def keyPressEvent(self, event):
        if not self.capture.capturing and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.redo() if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else self.undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
        super().keyPressEvent(event)

    def apply_step(self):
        entry = self.selected()
        if not entry:
            return
        indexes, original, _, _, _ = entry
        events = list(self.sequence.events)
        difference = self.at.value() * 1000 - original.t_us
        for index in indexes:
            event = events[index]
            event = replace(event, t_us=event.t_us + difference)
            if event.kind in ("button", "wheel"):
                event = replace(event, x=self.x.value(), y=self.y.value())
            if event.key and not event.pressed:
                event = replace(event, t_us=self.at.value() * 1000 + self.duration.value() * 1000)
            events[index] = event
        events.sort(key=lambda e: e.t_us)
        duration = max(self.sequence.duration_us, events[-1].t_us)
        self.change(replace(self.sequence, events=tuple(events), duration_us=duration))

    def delete_step(self):
        entry = self.selected()
        if entry:
            self.change(remove_events(self.sequence, entry[0]))

    def insert_step(self):
        if self.capture.capturing or self.capture.binding is None:
            self.error.setText("请先录入要插入的按键或组合。")
            return
        entry = self.selected()
        stamp = entry[1].t_us if entry else self.sequence.duration_us
        try:
            self.change(insert_press(self.sequence, binding_atoms(self.capture.binding), stamp,
                                     self.insert_duration.value(), self.count.value(), self.interval.value()))
        except ValueError as exc:
            self.error.setText(str(exc))

    def validated(self):
        return replace(self.sequence, name=self.name.text().strip()).validate()

    def preview(self):
        if self._previewing:
            self._delay.stop()
            self.row.owner.window.stop_execution()
            self._previewing = False
            self.update_preview()
            return
        try:
            self.validated()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self._previewing = True
        self.capture.reject()
        for field in (self.name, self.pointer, self.capture, self.insert, self.insert_duration, self.interval, self.count, self.save):
            field.setDisabled(True)
        self.select_step()
        self.update_history()
        self.play.setText("取消试放")
        self.error.setText("3 秒后回放，切到目标窗口；总启停快捷键可停止。")
        self._delay.start(3000)
        self._timer.start()

    def begin_preview(self):
        sequence = self.validated()
        config = ActionConfig(None, "burst", 1, repeat_count=1, sequence=sequence)
        self._previewing = self.row.owner.window.play_sequence(config)
        self.play.setText("停止试放")
        self.error.clear()
        self.update_preview()

    def update_preview(self):
        if self._delay.isActive():
            return
        if not self._previewing or not self.row.owner.window._running:
            self._previewing = False
            self._timer.stop()
            self.play.setText("单次试放")
            for field in (self.name, self.pointer, self.capture, self.insert, self.insert_duration, self.interval, self.count, self.save):
                field.setEnabled(True)
            self.select_step()
            self.update_history()

    def accept(self):
        if self._previewing:
            return
        try:
            sequence = self.validated()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.row.apply_sequence(sequence)
        super().accept()

    def done(self, result):
        self._delay.stop()
        self._timer.stop()
        self.capture.reject()
        if self._previewing:
            self.row.owner.window.stop_execution()
        super().done(result)
