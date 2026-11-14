"""The four-page desktop UI and tray lifecycle."""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QScrollArea, QProgressBar, QCheckBox, QDialog, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QFileDialog, QSystemTrayIcon, QMenu, QComboBox, QTabWidget,
)
from .logic import display_weight, progress, weekly_stats, encouragement, reminder_due
from .widgets import Card, GrowthArt, RecordForm, ProfileForm, WeightChart, app_pixmap, label, button
from .diet_ui import DietPage, NutritionProfile, summary_text
from .nutrition import fmt, validate_profile
from .ai_network import AIClient
from .ai_ui import AIPage, APISettings


class SetupDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欢迎来到轻盈日记")
        self.setMinimumWidth(590)
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 26)
        root.setSpacing(16)
        root.addWidget(label("从适合自己的节奏开始", "title"))
        root.addWidget(label("设定一个方向，让每一天的小行动有处可记。", "muted"))
        self.form = ProfileForm(store)
        self.nutrition = NutritionProfile(store)
        tabs = QTabWidget()
        tabs.addTab(self.form,'日常目标')
        tabs.addTab(self.nutrition,'饮食目标（选填）')
        root.addWidget(tabs)
        self.status = label("目标可以随时调整，今天先开始。", "muted", True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(button("稍后设置", self.reject, "secondary"))
        row.addWidget(button("开始我的日记", self.save))
        root.addLayout(row)

    def save(self):
        try:
            nutrition_value = validate_profile(self.nutrition.value())
            self.form.save()
            self.form.store.save_nutrition_profile(nutrition_value)
        except (ValueError, sqlite3.Error) as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color:#A06350")
            return
        self.accept()


class RecordDialog(QDialog):
    def __init__(self, store, day=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("记录一天 · 轻盈日记")
        self.setMinimumWidth(600)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(14)
        root.addWidget(label("让今天的一小步留下来", "section"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setMaximumDate(QDate.currentDate())
        self.date_edit.setDate(QDate.fromString(day or date.today().isoformat(), "yyyy-MM-dd"))
        root.addWidget(self.date_edit)
        root.addWidget(label("切换日期会加载那天的已有记录；保存会更新同一天的内容。", "caption", True))
        self.form = RecordForm(store, day, expanded=True)
        root.addWidget(self.form)
        self.date_edit.dateChanged.connect(lambda value: self.form.load(value.toString("yyyy-MM-dd")))
        self.form.saved.connect(self.accept)
        root.addWidget(button("取消", self.reject, "secondary"))


class Window(QMainWindow):
    def __init__(self, store, show_onboarding=True):
        super().__init__()
        self.store = store
        self.ai_client = AIClient(self)
        self._quitting = False
        self._tray_notice = False
        self.reminders_paused = False
        self.setWindowTitle("轻盈日记 · 每一天，轻一点")
        self.setWindowIcon(QIcon(app_pixmap()))
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width = min(1180, available.width() - 40) if available else 1180
        height = min(800, available.height() - 70) if available else 800
        self.setMinimumSize(min(960, width), min(640, height))
        self.resize(width, height)
        self.setObjectName("mainWindow")
        content = QWidget()
        content.setObjectName("content")
        self.setCentralWidget(content)
        shell = QHBoxLayout(content)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(186)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 22)
        side.setSpacing(9)
        logo = label()
        logo.setPixmap(app_pixmap(42))
        side.addWidget(logo)
        side.addWidget(label("轻盈日记", "brand"))
        side.addWidget(label("每一天，轻一点", "caption"))
        side.addSpacing(34)
        self.nav = []
        self.page_ids = {'today':0,'diet':1,'records':2,'trends':3,'ai':4,'settings':5}
        for key, title in [('today',"◉    今天"),('diet',"◇    饮食"),('records',"≡    记录"),('trends',"↗    趋势"),('ai',"AI    分析"),('settings',"⚙    设置")]:
            nav = button(title, role="nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, page=key: self.change_page(page))
            self.nav.append(nav)
            side.addWidget(nav)
        side.addStretch()
        side.addWidget(label("一点点行动\n也在认真向前。", "muted", True))
        side.addSpacing(22)
        side.addWidget(label("本机记录 · AI 按需连接", "caption", True))
        shell.addWidget(sidebar)
        self.stack = QStackedWidget()
        shell.addWidget(self.stack, 1)
        self.build_home()
        diet_root = self.page('每天吃什么，心里有数','按食堂和外卖场景安排三餐；记录实际份量，了解自己的饮食。')
        self.diet_page = DietPage(store)
        self.diet_page.changed.connect(lambda:self.refresh())
        self.diet_page.manual_saved.connect(lambda day,value:self.today_form.calories.setText(str(value)) if self.today_form.day==day else None)
        diet_root.addWidget(self.diet_page)
        diet_root.addStretch()
        self.build_records()
        self.build_trends()
        ai_root = self.page('读懂记录，照顾好每一天','主动分析、自由追问；从已有记录中找到下一步。')
        self.ai_page = AIPage(store, self.ai_client, self.open_api_settings)
        ai_root.addWidget(self.ai_page)
        ai_root.addStretch()
        self.build_settings()
        self.build_tray()
        self.change_page(0)
        self.refresh(reload_form=True)
        self.current_day = date.today()
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        if show_onboarding and not store.settings().get("onboarded"):
            QTimer.singleShot(150, self.onboard)

    def page(self, title, subtitle):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 27, 30, 27)
        layout.setSpacing(18)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(subtitle, "muted", True))
        area.setWidget(page)
        self.stack.addWidget(area)
        return layout

    def change_page(self, index):
        if isinstance(index,str):
            index = self.page_ids[index]
        self.stack.setCurrentIndex(index)
        for i, nav in enumerate(self.nav):
            nav.setChecked(i == index)

    def build_home(self):
        self.home_date = label("", "caption")
        root = self.page("今天，也为自己留一点时间", "不用一次做到所有事。从一个小行动开始就好。")
        hero = QFrame()
        hero.setObjectName("hero")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 14, 8, 14)
        copy = QVBoxLayout()
        copy.setSpacing(10)
        copy.addWidget(self.home_date)
        self.hero_title = label("", "heroTitle", True)
        self.hero_text = label("", "muted", True)
        copy.addWidget(self.hero_title)
        copy.addWidget(self.hero_text)
        layout.addLayout(copy, 1)
        layout.addWidget(GrowthArt())
        root.addWidget(hero)
        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.metric_labels = {}
        for key, title in [("current", "最近记录体重"), ("target", "我的目标"), ("days", "已经留下的记录")]:
            card = Card()
            card.body.setSpacing(4)
            card.body.addWidget(label(title, "muted"))
            value = label("—", "metric")
            self.metric_labels[key] = value
            card.body.addWidget(value)
            metrics.addWidget(card)
        root.addLayout(metrics)
        food_card = Card('今天的饮食')
        self.nutrition_summary = label('','muted',True)
        food_card.body.addWidget(self.nutrition_summary)
        food_card.body.addWidget(button('安排三餐 / 记录食物 →',lambda:self.change_page('diet'),'link'))
        food_card.body.addWidget(button('分析今天 →', self.analyze_today, 'link'))
        root.addWidget(food_card)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        log = Card("快捷记录")
        self.today_form = RecordForm(self.store)
        self.today_form.saved.connect(lambda value: self.refresh())
        log.body.addWidget(self.today_form)
        columns.addWidget(log, 3)
        companion = Card("今天的小目标")
        self.habit_count = label("", "muted")
        companion.body.addWidget(self.habit_count)
        self.habit_box = QWidget()
        self.habit_layout = QVBoxLayout(self.habit_box)
        self.habit_layout.setContentsMargins(0, 0, 0, 0)
        self.habit_layout.setSpacing(15)
        companion.body.addWidget(self.habit_box)
        self.goal_bar = QProgressBar()
        self.goal_bar.setTextVisible(False)
        companion.body.addSpacing(8)
        companion.body.addWidget(self.goal_bar)
        self.goal_caption = label("", "caption", True)
        companion.body.addWidget(self.goal_caption)
        companion.body.addStretch()
        companion.body.addWidget(label("记得你为什么开始", "section"))
        self.reason = label("", "muted", True)
        companion.body.addWidget(self.reason)
        companion.body.addWidget(button("调整目标和小习惯 →", lambda: self.change_page('settings'), "link"))
        columns.addWidget(companion, 2)
        root.addLayout(columns)
        root.addWidget(label("一次波动不代表全部。记录是为了了解自己，也为了看见已经发生的改变。", "caption", True))
        root.addStretch()

    def build_records(self):
        root = self.page("每一天，都有迹可循", "记录可以补充、修改。空白的日子也可以从今天继续。")
        card = Card()
        row = QHBoxLayout()
        row.addWidget(label("我的日常记录", "section"))
        row.addStretch()
        row.addWidget(button("＋ 记录 / 补记一天", lambda: self.edit_record()))
        row.addWidget(button("编辑所选", self.edit_selected, "secondary"))
        row.addWidget(button("删除所选", self.delete_selected, "danger"))
        card.body.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["日期", "体重", "饮食备注", "运动", "分钟", "步数", "当前摄入千卡"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(365)
        header = self.table.horizontalHeader()
        for index in range(7):
            header.setSectionResizeMode(index, QHeaderView.Stretch if index in (2, 3) else QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_selected())
        card.body.addWidget(self.table)
        self.record_count = label("", "caption", True)
        card.body.addWidget(self.record_count)
        root.addWidget(card)
        root.addStretch()

    def build_trends(self):
        root = self.page("看趋势，也看见自己的努力", "关注一段时间的变化，比盯着某一天的数字更有帮助。")
        chart_card = Card()
        row = QHBoxLayout()
        row.addWidget(label("体重轨迹", "section"))
        row.addStretch()
        self.range = QComboBox()
        for days in (7, 30, 90):
            self.range.addItem(f"最近 {days} 天", days)
        self.range.setCurrentIndex(1)
        self.range.currentIndexChanged.connect(self.refresh_chart)
        row.addWidget(self.range)
        chart_card.body.addLayout(row)
        self.chart = WeightChart()
        chart_card.body.addWidget(self.chart)
        chart_card.body.addWidget(label("圆点代表实际称重；空白日期不填补。移动到圆点可查看数值。", "caption", True))
        root.addWidget(chart_card)
        self.week_card = Card("最近 7 天 · 温和回顾")
        self.week_text = label("", "muted", True)
        self.week_text.setMinimumHeight(75)
        self.week_card.body.addWidget(self.week_text)
        self.week_habits = label("", "muted", True)
        self.week_card.body.addWidget(self.week_habits)
        self.week_card.body.addWidget(label("周平均只使用有体重的日期；两周各至少有 2 次称重时，才显示平均值的变化。", "caption", True))
        root.addWidget(self.week_card)
        nutrition_card = Card('饮食记录 · 最近七天与三十天')
        self.nutrition_trend = label('','muted',True)
        nutrition_card.body.addWidget(self.nutrition_trend)
        nutrition_card.body.addWidget(label('平均摄入与目标符合天数只统计明确完成全天记录的日期；未记录或未完成的日期不视为达标。目标符合范围为当天目标的 ±10%。','caption',True))
        self.nutrition_table = QTableWidget(0,5)
        self.nutrition_table.setHorizontalHeaderLabels(['日期','已记录千卡','目标快照','来源','记录状态'])
        self.nutrition_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.nutrition_table.setMinimumHeight(220)
        self.nutrition_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        nutrition_card.body.addWidget(self.nutrition_table)
        root.addWidget(nutrition_card)
        root.addStretch()

    def build_settings(self):
        root = self.page("让它适合你的生活", "目标和习惯都可以调整。给自己留一点弹性。")
        api = Card('AI 接入 · OpenAI 兼容接口')
        self.api_settings = APISettings(self.store, self.ai_client)
        self.api_settings.saved.connect(self.ai_page.refresh)
        api.body.addWidget(self.api_settings)
        root.addWidget(api)
        profile = Card("我的方向与日常节奏")
        self.profile_form = ProfileForm(self.store)
        profile.body.addWidget(self.profile_form)
        row = QHBoxLayout()
        self.profile_status = label("", "muted", True)
        row.addWidget(self.profile_status, 1)
        row.addWidget(button("保存设置", self.save_settings))
        profile.body.addLayout(row)
        root.addWidget(profile)
        nutrition = Card('饮食目标与忌口')
        self.nutrition_profile_form = NutritionProfile(self.store)
        self.nutrition_profile_form.saved.connect(lambda:self.refresh())
        nutrition.body.addWidget(self.nutrition_profile_form)
        root.addWidget(nutrition)
        data = Card("数据与备份")
        data.body.addWidget(label("记录和 AI 报告保存在本机。主动使用 AI 时，预览的内容会发送给所配置的服务商。更换软件文件不会清空记录。", "muted", True))
        self.data_path = label(str(self.store.path), "caption", True)
        self.data_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        data.body.addWidget(self.data_path)
        row = QHBoxLayout()
        row.addWidget(button("导出 CSV", lambda: self.export("csv"), "secondary"))
        row.addWidget(button('导出餐食明细',lambda:self.export('meals'),'secondary'))
        row.addWidget(button("完整备份", lambda: self.export("backup"), "secondary"))
        row.addWidget(button("恢复备份", self.restore, "secondary"))
        row.addStretch()
        data.body.addLayout(row)
        root.addWidget(data)
        root.addWidget(label("轻盈日记 1.2.0  ·  离线记录 / 可选 AI  ·  托盘菜单可彻底退出软件", "caption"))
        root.addStretch()

    def build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("轻盈日记 · 每一天，轻一点")
        menu = QMenu(self)
        menu.addAction("打开轻盈日记", self.activate)
        self.pause_action = menu.addAction("暂停提醒至下次启动")
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(self.set_paused)
        menu.addSeparator()
        menu.addAction("彻底退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.activate() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.activate)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def set_paused(self, paused):
        self.reminders_paused = paused

    def activate(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def onboard(self):
        dialog = SetupDialog(self.store, self)
        if dialog.exec() == QDialog.Accepted:
            self.profile_form.load()
            self.nutrition_profile_form.load()
            self.refresh(reload_form=True)

    def save_settings(self):
        old_unit = self.store.settings()["unit"]
        try:
            self.profile_form.save()
        except (ValueError, sqlite3.Error) as error:
            self.profile_status.setText(str(error))
            self.profile_status.setStyleSheet("color:#A06350")
            return
        unit = self.store.settings()["unit"]
        if unit != old_unit:
            try:
                if self.today_form.weight.text().strip():
                    factor = (2 if unit == "jin" else 1) / (2 if old_unit == "jin" else 1)
                    self.today_form.weight.setText(f"{float(self.today_form.weight.text()) * factor:g}")
            except ValueError:
                pass
            self.today_form.unit = unit
            self.today_form.weight_title.setText(f"体重 · {'斤' if unit == 'jin' else '公斤'}")
        self.profile_status.setText("已保存，按自己的节奏继续。")
        self.profile_status.setStyleSheet("color:#426B55")
        self.refresh()

    def toggle_habit(self, habit_id, checked):
        try:
            self.store.set_completed(habit_id, date.today().isoformat(), checked)
            self.refresh_habits()
            self.refresh_copy()
            self.refresh_week()
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "暂时无法保存", str(error))

    def refresh_habits(self):
        while self.habit_layout.count():
            child = self.habit_layout.takeAt(0).widget()
            if child:
                child.deleteLater()
        habits = self.store.habits()
        completed = self.store.completed(date.today().isoformat())
        active_count = sum(row["id"] in completed for row in habits)
        self.habit_count.setText(f"已完成 {active_count} / {len(habits)} · 小行动也算数")
        for row in habits:
            check = QCheckBox(row["name"])
            check.setToolTip(row["name"])
            check.setChecked(row["id"] in completed)
            check.toggled.connect(lambda checked, ident=row["id"]: self.toggle_habit(ident, checked))
            self.habit_layout.addWidget(check)
        self.reason.setText(self.store.settings()["reason"] or "给自己一个开始的理由。你可以在设置里写下来。")

    def refresh_copy(self):
        rows = self.store.records()
        active = {row["id"] for row in self.store.habits()}
        completed = len(self.store.completed(date.today().isoformat()) & active)
        title, text = encouragement(rows, completed)
        self.hero_title.setText(title)
        self.hero_text.setText(text)
        self.home_date.setText(f"{date.today():%Y年%m月%d日}  ·  今天只需一小步")

    def refresh(self, reload_form=False):
        values = self.store.settings()
        rows = self.store.records()
        weights = [row for row in rows if row["weight_kg"] is not None]
        current = weights[-1]["weight_kg"] if weights else None
        unit = "斤" if values["unit"] == "jin" else "公斤"
        self.metric_labels["current"].setText(f"{display_weight(current, values['unit'])} {unit}")
        self.metric_labels["target"].setText(f"{display_weight(values['target_weight'], values['unit'])} {unit}")
        self.metric_labels["days"].setText(f"{len(rows)} 天")
        percent = progress(values["start_weight"], values["target_weight"], current)
        self.goal_bar.setValue(percent)
        self.goal_caption.setText(f"目标进度 {percent}% · 一步一步来" if current is not None and values["start_weight"] is not None else "记录体重、设置目标后，可以看到进度。")
        self.refresh_habits()
        self.refresh_copy()
        self.refresh_table()
        self.refresh_chart()
        self.refresh_week()
        self.refresh_nutrition()
        self.ai_page.refresh()
        if reload_form:
            self.today_form.load(date.today().isoformat())

    def refresh_nutrition(self):
        self.nutrition_summary.setText(summary_text(self.store.day_nutrition(date.today().isoformat())))
        self.diet_page.refresh()
        lines=[]
        for days in (7,30):
            stats=self.store.nutrition_stats(days)
            average='尚无完整日记录' if stats['average'] is None else fmt(stats['average'],' 千卡')
            lines.append(f"最近 {days} 天：有摄入记录 {stats['logged']} 天 · 全天完成 {stats['complete']} 天 · 完整日平均 {average} · 符合参考目标 {stats['within']} 天")
        self.nutrition_trend.setText('\n'.join(lines))
        self.nutrition_table.setRowCount(30)
        for index in range(30):
            day=(date.today()-timedelta(days=index)).isoformat()
            state=self.store.day_nutrition(day)
            status='全天完成' if state['complete'] else ('未记录' if state['kcal'] is None else '记录未完成')
            values=[day,('未记录' if state['kcal'] is None else fmt(state['kcal'])),('未设' if state['target'] is None else fmt(state['target'])),('明细计算' if state['source']=='details' else '手动全天'),status]
            for col,value in enumerate(values): self.nutrition_table.setItem(index,col,QTableWidgetItem(value))

    def refresh_table(self):
        rows = list(reversed(self.store.records()))
        unit = self.store.settings()["unit"]
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderItem(1, QTableWidgetItem("体重 / " + ("斤" if unit == "jin" else "公斤")))
        for index, row in enumerate(rows):
            values = [row["day"], display_weight(row["weight_kg"], unit), row["diet"] or "—", row["activity"] or "—",
                      "—" if row["minutes"] is None else str(row["minutes"]), "—" if row["steps"] is None else str(row["steps"]),
                      '—' if self.store.day_nutrition(row['day'])['kcal'] is None else fmt(self.store.day_nutrition(row['day'])['kcal'])]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value + ("\n今日回顾：" + row["reflection"] if column == 0 and row["reflection"] else ""))
                self.table.setItem(index, column, item)
            self.table.setRowHeight(index, 45)
        self.record_count.setText(f"共 {len(rows)} 天记录 · 双击一行可以编辑；回顾内容可在编辑窗口查看。" if rows else "还没有记录。点击「记录 / 补记一天」就可以开始。")

    def refresh_chart(self):
        values = self.store.settings()
        self.chart.set_data(self.store.records(), self.range.currentData(), values["unit"], values["target_weight"])

    def refresh_week(self):
        stats = weekly_stats(self.store.records())
        unit = self.store.settings()["unit"]
        suffix = "斤" if unit == "jin" else "公斤"
        if stats["average"] is None:
            first = "这周还没有体重记录。你可以在方便的时候留下第一次称重。"
        else:
            first = f"平均体重 {display_weight(stats['average'], unit)} {suffix}，来自 {stats['weight_days']} 天实际称重。"
            if stats["difference"] is not None:
                difference = stats["difference"] * (2 if unit == "jin" else 1)
                first += f" 与前 7 天平均值相比：{difference:+.1f} {suffix}。"
        self.week_text.setText(first + f"\n\n留下了 {stats['record_days']} 天日常记录，记录的运动时长合计 {stats['minutes']} 分钟。")
        first_day = (date.today() - timedelta(days=6)).isoformat()
        counts = []
        for habit in self.store.habits():
            count = self.store.connection.execute("SELECT COUNT(*) FROM completions WHERE habit_id=? AND day>=? AND day<=?", (habit["id"], first_day, date.today().isoformat())).fetchone()[0]
            counts.append(f"{habit['name']}：{count} 天")
        self.week_habits.setText("小目标完成情况\n" + "  ·  ".join(counts))

    def selected_day(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "选择一天", "请先选择一行记录。")
            return None
        return self.table.item(row, 0).text()

    def edit_record(self, day=None):
        dialog = RecordDialog(self.store, day, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh(reload_form=True)

    def edit_selected(self):
        day = self.selected_day()
        if day:
            self.edit_record(day)

    def delete_selected(self):
        day = self.selected_day()
        if day and QMessageBox.question(self, "删除这一天的记录", f"删除 {day} 的日常记录？当天的小目标打卡会保留。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.store.delete_record(day)
            self.refresh(reload_form=True)

    def export(self, kind):
        csv = kind in ('csv','meals')
        name = f"轻盈日记-{date.today():%Y%m%d}" + (".csv" if csv else ".sqlite3")
        if kind=='meals': name='餐食明细-'+name
        path, _ = QFileDialog.getSaveFileName(self, "导出记录" if csv else "保存完整备份", str(Path.home() / "Desktop" / name), "CSV (*.csv)" if csv else "轻盈日记备份 (*.sqlite3)")
        if not path:
            return
        try:
            (self.store.export_meals_csv if kind=='meals' else self.store.export_csv if csv else self.store.backup)(Path(path))
            QMessageBox.information(self, "已保存", f"文件已保存到：\n{path}")
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法导出", str(error))

    def restore(self):
        if self.ai_client.busy:
            QMessageBox.information(self, '请求进行中', '请等待 AI 请求结束或取消后，再恢复备份。')
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择完整备份", str(Path.home()), "轻盈日记备份 (*.sqlite3)")
        if not path:
            return
        if QMessageBox.question(self, "恢复备份", "这会用备份中的记录和设置替换当前数据。软件会先自动保留一份当前数据备份。继续恢复？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            safety = self.store.restore(Path(path))
            self.profile_form.load()
            self.nutrition_profile_form.load()
            self.api_settings.load()
            self.ai_page.question.clear()
            self.ai_page.reflection.setChecked(False)
            self.ai_page.refresh(reset=True)
            self.refresh(reload_form=True)
            QMessageBox.information(self, "恢复完成", f"记录和设置已恢复。API 密钥需要重新填写。恢复前的数据保存在：\n{safety}")
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "没有恢复数据", str(error))

    def tick(self, now=None):
        now = now or datetime.now()
        if now.date() != self.current_day:
            self.ai_page.date.setMaximumDate(QDate.currentDate())
            was_today=self.diet_page.day()==self.current_day.isoformat()
            self.diet_page.date.setMaximumDate(QDate.currentDate().addDays(6))
            if was_today:self.diet_page.date.setDate(QDate.currentDate())
            self.current_day = now.date()
            self.refresh(reload_form=True)
        settings = self.store.settings()
        day = now.date().isoformat()
        if reminder_due(settings, now, self.store.was_reminded(day), self.reminders_paused):
            if self.store.mark_reminded(day, now.isoformat()):
                self.tray.showMessage("给自己留一分钟", "记下一餐、一次活动，或者完成今天的小目标。轻盈日记陪你慢慢来。", QSystemTrayIcon.Information, 8000)

    def closeEvent(self, event):
        if not self._quitting and self.store.settings().get("reminder_enabled") and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            if not self._tray_notice:
                self.tray.showMessage("轻盈日记仍在陪你", "已收进系统托盘，提醒会继续。右键托盘图标可以彻底退出。", QSystemTrayIcon.Information, 4000)
                self._tray_notice = True
        else:
            self.ai_client.shutdown()
            self.timer.stop()
            self.tray.hide()
            self._quitting = True
            event.accept()
            QApplication.instance().quit()

    def quit_app(self):
        self._quitting = True
        self.close()

    def analyze_today(self):
        if not self.ai_client.busy:
            self.ai_page.date.setDate(QDate.currentDate())
        self.change_page('ai')

    def open_api_settings(self):
        self.change_page('settings')
        area = self.stack.currentWidget()
        QTimer.singleShot(0, lambda: area.verticalScrollBar().setValue(0))
