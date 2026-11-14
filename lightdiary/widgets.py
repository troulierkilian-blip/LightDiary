"""Reusable native widgets and vector illustrations, no external assets."""
from datetime import date, timedelta
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QWidget, QComboBox, QCheckBox, QTimeEdit,
)
from .logic import display_weight
from .storage import DEFAULT_HABITS, number

ACCENT = "#426B55"

STYLE = """
QWidget { color:#263D30; font-family:'Microsoft YaHei UI','Microsoft YaHei','Segoe UI'; font-size:13px; }
QMainWindow, QScrollArea, QWidget#page, QWidget#content { background:#F4F7F3; }
QScrollArea { border:none; }
QFrame#sidebar { background:#FFFFFF; border-right:1px solid #E4EBE3; }
QFrame#card { background:#FFFFFF; border:1px solid #E4EBE3; border-radius:16px; }
QFrame#hero { background:#E8F0E5; border:1px solid #DDE8D9; border-radius:18px; }
QLabel { background:transparent; }
QLabel#title { font-size:27px; font-weight:700; }
QLabel#brand { font-size:21px; font-weight:700; }
QLabel#section { font-size:16px; font-weight:600; }
QLabel#muted { color:#728476; }
QLabel#caption { color:#819082; font-size:11px; }
QLabel#metric { font-size:29px; font-weight:600; }
QLabel#heroTitle { font-size:22px; font-weight:600; }
QPushButton { background:#426B55; color:white; border:none; border-radius:8px; padding:9px 18px; font-weight:600; }
QPushButton:hover { background:#345A46; }
QPushButton:pressed { background:#2A4A39; }
QPushButton:disabled { background:#B9C9BC; }
QPushButton#secondary { background:#EDF3EB; color:#426B55; border:1px solid #DEE8DA; }
QPushButton#secondary:hover { background:#E1EBDE; }
QPushButton#danger { background:#FAEDE8; color:#945C4E; }
QPushButton#nav { background:transparent; color:#758378; text-align:left; border-radius:10px; padding:13px 18px; font-size:15px; font-weight:500; }
QPushButton#nav:hover { background:#F3F6F0; }
QPushButton#nav:checked { background:#E8F0E5; color:#36583F; font-weight:600; }
QPushButton#link { background:transparent; color:#426B55; text-align:left; padding:4px 0; font-weight:400; }
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QTimeEdit {
    background:#FAFCF8; border:1px solid #DDE6D8; border-radius:7px; padding:7px 10px; selection-background-color:#CDE1C9;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border:1px solid #719C70; background:white; }
QComboBox::drop-down { border:none; width:24px; }
QCheckBox { spacing:10px; }
QCheckBox::indicator { width:18px; height:18px; border:1px solid #BCCDB8; border-radius:5px; background:white; }
QCheckBox::indicator:checked { background:#426B55; border:1px solid #426B55; image:url('__CHECK__'); }
QProgressBar { border:none; background:#EAF0E5; border-radius:5px; min-height:8px; max-height:8px; }
QProgressBar::chunk { background:#779E72; border-radius:4px; }
QTableWidget { background:white; border:none; gridline-color:#EDF1E9; selection-background-color:#E6EFDF; selection-color:#263D30; }
QHeaderView::section { background:#F4F7F0; color:#687B69; border:none; padding:11px 8px; font-weight:500; }
QTableWidget::item { padding:10px 6px; border-bottom:1px solid #EDF1E9; }
QScrollBar:vertical { border:none; background:transparent; width:9px; margin:2px; }
QScrollBar::handle:vertical { background:#CFDACC; border-radius:4px; min-height:25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QToolTip { background:white; color:#263D30; border:1px solid #DDE6D8; padding:5px; }
QDialog { background:#F4F7F3; }
""".replace("__CHECK__", (Path(__file__).resolve().parent.parent / "assets" / "check.svg").as_posix())


def label(text="", role=None, wrap=False):
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback=None, role=None):
    widget = QPushButton(text)
    if role:
        widget.setObjectName(role)
    if callback:
        widget.clicked.connect(callback)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


class Card(QFrame):
    def __init__(self, title=None):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 20, 22, 20)
        self.body.setSpacing(12)
        if title:
            self.body.addWidget(label(title, "section"))


def app_pixmap(size=128):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 128, size / 128)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#426B55"))
    painter.drawRoundedRect(QRectF(3, 3, 122, 122), 28, 28)
    painter.setBrush(QColor("#E8F0E5"))
    leaf = QPainterPath(QPointF(36, 91))
    leaf.cubicTo(27, 46, 60, 30, 97, 28)
    leaf.cubicTo(100, 68, 77, 101, 36, 91)
    painter.drawPath(leaf)
    painter.setPen(QPen(QColor("#426B55"), 4, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(32, 98), QPointF(78, 52))
    painter.end()
    return pixmap


class GrowthArt(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(190, 112)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#D9E7D3"))
        painter.drawEllipse(QRectF(58, 2, 105, 105))
        painter.setPen(QPen(QColor("#69866C"), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(108, 91), QPointF(108, 39))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#91B184"))
        path = QPainterPath(QPointF(108, 72))
        path.cubicTo(77, 76, 70, 59, 72, 43)
        path.cubicTo(96, 43, 108, 48, 108, 72)
        painter.drawPath(path)
        painter.setBrush(QColor("#648E62"))
        path = QPainterPath(QPointF(108, 60))
        path.cubicTo(107, 39, 124, 28, 146, 29)
        path.cubicTo(147, 48, 135, 64, 108, 60)
        painter.drawPath(path)
        painter.setBrush(QColor("#F9FCF5"))
        for x, y, r in [(38, 31, 5), (167, 84, 4), (153, 10, 3)]:
            painter.drawEllipse(QPointF(x, y), r, r)
        painter.end()


class RecordForm(QWidget):
    saved = Signal(dict)

    def __init__(self, store, day=None, expanded=False):
        super().__init__()
        self.store = store
        self.day = day or date.today().isoformat()
        self.unit = store.settings()["unit"]
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.weight = QLineEdit()
        self.weight.setObjectName("weightInput")
        self.weight.setPlaceholderText("选填，例如 70.5")
        self.weight_title = label(f"体重 · {'斤' if self.unit == 'jin' else '公斤'}", "muted")
        self.activity = QLineEdit()
        self.activity.setPlaceholderText("散步、骑车……")
        self.minutes = QLineEdit()
        self.minutes.setPlaceholderText("选填，分钟")
        for column, (title, field) in enumerate([(self.weight_title, self.weight), (label("运动项目", "muted"), self.activity), (label("运动时长", "muted"), self.minutes)]):
            grid.addWidget(title, 0, column)
            grid.addWidget(field, 1, column)
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)
        root.addWidget(label("今天吃了什么", "muted"))
        self.diet = QPlainTextEdit()
        self.diet.setObjectName("dietInput")
        self.diet.setPlaceholderText("简单记下一餐也很好，不必计算每一口。")
        self.diet.setFixedHeight(67)
        root.addWidget(self.diet)
        self.more = button("＋ 补充步数、热量和回顾", role="link")
        self.more.setCheckable(True)
        root.addWidget(self.more)
        self.details = QWidget()
        details = QGridLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.steps, self.calories, self.reflection = QLineEdit(), QLineEdit(), QLineEdit()
        self.steps.setPlaceholderText("选填，步")
        self.calories.setPlaceholderText("选填，千卡")
        self.reflection.setPlaceholderText("今天有什么值得肯定的小事？")
        details.addWidget(label("步数", "muted"), 0, 0)
        details.addWidget(label("手动记录热量", "muted"), 0, 1)
        details.addWidget(self.steps, 1, 0)
        details.addWidget(self.calories, 1, 1)
        details.addWidget(label("今日回顾", "muted"), 2, 0, 1, 2)
        details.addWidget(self.reflection, 3, 0, 1, 2)
        root.addWidget(self.details)
        self.more.toggled.connect(self.details.setVisible)
        self.details.setVisible(expanded)
        self.more.setChecked(expanded)
        self.status = label("其他项目都可以留空。", "muted", True)
        root.addWidget(self.status)
        self.save_button = button("保存今天的记录", self.save)
        self.save_button.setObjectName("saveRecordButton")
        root.addWidget(self.save_button)
        self.load()

    def load(self, day=None):
        if day:
            self.day = day
        self.unit = self.store.settings()["unit"]
        self.weight_title.setText(f"体重 · {'斤' if self.unit == 'jin' else '公斤'}")
        row = self.store.record(self.day) or {}
        weight = row.get("weight_kg")
        self.weight.setText("" if weight is None else f"{weight * (2 if self.unit == 'jin' else 1):g}")
        for field, key in [(self.activity, "activity"), (self.minutes, "minutes"), (self.steps, "steps"), (self.calories, "calories"), (self.reflection, "reflection")]:
            field.setText("" if row.get(key) is None else str(row[key]))
        self.diet.setPlainText(row.get("diet", ""))
        self.save_button.setText("保存今天的记录" if self.day == date.today().isoformat() else "保存这一天的记录")

    def value(self):
        weight = number(self.weight.text().strip(), "体重", 1000 if self.unit == "jin" else 500)
        return {"day": self.day, "weight_kg": None if weight is None else weight / (2 if self.unit == "jin" else 1),
                "diet": self.diet.toPlainText(), "activity": self.activity.text(), "minutes": self.minutes.text().strip(),
                "steps": self.steps.text().strip(), "calories": self.calories.text().strip(), "reflection": self.reflection.text()}

    def save(self):
        try:
            value = self.value()
            self.store.save_record(value)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color:#A06350")
            return
        self.status.setStyleSheet("color:#426B55")
        self.status.setText("已保存。这一小步，已经留下来了。")
        self.saved.emit(value)


class ProfileForm(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self.unit = QComboBox()
        self.unit.addItem("公斤（kg）", "kg")
        self.unit.addItem("斤", "jin")
        self.start, self.target, self.reason = QLineEdit(), QLineEdit(), QLineEdit()
        self.start.setObjectName("startWeightInput")
        self.target.setObjectName("targetWeightInput")
        self.start.setPlaceholderText("例如 75")
        self.target.setPlaceholderText("例如 68")
        self.reason.setPlaceholderText("例如：想更轻松地爬楼，想让自己更有精神。")
        grid = QGridLayout()
        for column, (title, field) in enumerate([("起始体重", self.start), ("目标体重", self.target), ("显示单位", self.unit)]):
            grid.addWidget(label(title, "muted"), 0, column)
            grid.addWidget(field, 1, column)
        root.addLayout(grid)
        root.addWidget(label("为什么想开始", "muted"))
        root.addWidget(self.reason)
        root.addWidget(label("每日小目标 · 一行一个，可随时调整", "muted"))
        self.habits = QPlainTextEdit()
        self.habits.setFixedHeight(100)
        root.addWidget(self.habits)
        row = QHBoxLayout()
        self.enabled = QCheckBox("开启每日温和提醒")
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        row.addWidget(self.enabled)
        row.addStretch()
        row.addWidget(self.time)
        root.addLayout(row)
        root.addWidget(label("提醒需要软件正在运行或驻留托盘。默认不开机自启。", "caption", True))
        self.unit.currentIndexChanged.connect(self.convert_unit)
        self.enabled.toggled.connect(self.time.setEnabled)
        self._unit = "kg"
        self.load()

    def load(self):
        from PySide6.QtCore import QTime
        values = self.store.settings()
        self.unit.blockSignals(True)
        self.unit.setCurrentIndex(1 if values["unit"] == "jin" else 0)
        self.unit.blockSignals(False)
        self._unit = values["unit"]
        factor = 2 if self._unit == "jin" else 1
        self.start.setText("" if values["start_weight"] is None else f"{values['start_weight'] * factor:g}")
        self.target.setText("" if values["target_weight"] is None else f"{values['target_weight'] * factor:g}")
        self.reason.setText(values["reason"])
        self.habits.setPlainText("\n".join(row["name"] for row in self.store.habits()))
        self.enabled.setChecked(values["reminder_enabled"])
        self.time.setTime(QTime.fromString(values["reminder_time"], "HH:mm"))
        self.time.setEnabled(self.enabled.isChecked())

    def convert_unit(self):
        new_unit = self.unit.currentData()
        factor = (2 if new_unit == "jin" else 1) / (2 if self._unit == "jin" else 1)
        for field in (self.start, self.target):
            try:
                if field.text().strip():
                    field.setText(f"{float(field.text()) * factor:g}")
            except ValueError:
                pass
        self._unit = new_unit

    def save(self):
        factor = 2 if self.unit.currentData() == "jin" else 1
        start = number(self.start.text().strip(), "起始体重", 500 * factor)
        target = number(self.target.text().strip(), "目标体重", 500 * factor)
        self.store.save_profile(None if start is None else start / factor, None if target is None else target / factor,
            self.reason.text(), self.unit.currentData(), self.habits.toPlainText().splitlines(),
            self.enabled.isChecked(), self.time.time().toString("HH:mm"))


class WeightChart(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(255)
        self.setMouseTracking(True)
        self.rows, self.days, self.unit, self.target = [], 30, "kg", None
        self.points = []

    def set_data(self, rows, days, unit, target):
        self.rows, self.days, self.unit, self.target = rows, days, unit, target
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(54, 15, max(20, self.width() - 80), max(20, self.height() - 58))
        today = date.today()
        first = today - timedelta(days=self.days - 1)
        rows = [row for row in self.rows if first.isoformat() <= row["day"] <= today.isoformat() and row["weight_kg"] is not None]
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        self.points = []
        if not rows:
            painter.setPen(QColor("#8B9A8A"))
            painter.drawText(area, Qt.AlignCenter, "留下第一条体重记录，趋势会从这里开始。")
            painter.end()
            return
        factor = 2 if self.unit == "jin" else 1
        weights = [row["weight_kg"] * factor for row in rows]
        target = self.target * factor if self.target is not None else None
        low, high = min(weights), max(weights)
        if target is not None and low - 5 * factor <= target <= high + 5 * factor:
            low, high = min(low, target), max(high, target)
        padding = max((high - low) * .18, .5 * factor)
        low, high = low - padding, high + padding
        for index in range(5):
            y = area.bottom() - area.height() * index / 4
            painter.setPen(QPen(QColor("#EAF0E5"), 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor("#869583"))
            painter.drawText(QRectF(0, y - 10, 43, 20), Qt.AlignRight | Qt.AlignVCenter, f"{low + (high-low)*index/4:.1f}")
        if target is not None and low <= target <= high:
            y = area.bottom() - (target - low) / (high - low) * area.height()
            painter.setPen(QPen(QColor("#B1C3A7"), 1, Qt.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor("#879879"))
            painter.drawText(QRectF(area.right() - 75, y - 20, 75, 18), Qt.AlignRight, "目标")
        path = QPainterPath()
        last_day = None
        for row, weight in zip(rows, weights):
            day = date.fromisoformat(row["day"])
            point = QPointF(area.left() + (day - first).days / max(1, self.days - 1) * area.width(), area.bottom() - (weight - low) / (high - low) * area.height())
            self.points.append((point, row))
            if last_day is None or (day - last_day).days > 1:
                path.moveTo(point)
            else:
                path.lineTo(point)
            last_day = day
        painter.setPen(QPen(QColor("#658960"), 2.5, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(path)
        painter.setBrush(QColor("#658960"))
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        for point, row in self.points:
            painter.drawEllipse(point, 4, 4)
        painter.setPen(QColor("#869583"))
        for fraction in (0, .5, 1):
            day = first + timedelta(days=round((self.days - 1) * fraction))
            x = area.left() + area.width() * fraction
            painter.drawText(QRectF(x - 32, area.bottom() + 10, 64, 24), Qt.AlignCenter, day.strftime("%m/%d"))
        painter.end()

    def mouseMoveEvent(self, event):
        from PySide6.QtWidgets import QToolTip
        position = event.position()
        for point, row in self.points:
            if (point - position).manhattanLength() < 16:
                QToolTip.showText(event.globalPosition().toPoint(), f"{row['day']}\n{display_weight(row['weight_kg'], self.unit)} {'斤' if self.unit == 'jin' else '公斤'}", self)
                return
        QToolTip.hideText()
