"""Entry point, single-instance guard and reproducible packaged smoke test."""
import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon, QFontDatabase
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox
from .storage import Store, data_directory
from .widgets import STYLE, app_pixmap
from .window import Window


class SingleInstance:
    def __init__(self, directory):
        fingerprint = hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:24]
        self.name = "LightDiary-" + fingerprint
        self.server = QLocalServer()
        self.window = None

    def acquire(self):
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(1000):
            socket.write(b"activate")
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return False
        if not self.server.listen(self.name):
            # Windows named pipes have no stale filesystem entry to remove.
            raise RuntimeError("另一份轻盈日记正在启动，请稍等后再打开。")
        self.server.newConnection.connect(self.activate)
        return True

    def activate(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if self.window:
                self.window.activate()
            socket.disconnectFromServer()
            socket.deleteLater()


def smoke(app, output):
    """Runs in isolated temporary data, including when frozen with PyInstaller."""
    from PySide6.QtTest import QTest
    output.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="lightdiary-smoke-")
    store = Store(Path(temporary.name))
    store.save_profile(75, 68, "想让身体更轻松，生活更有精神。", "kg", ["记下今天的饮食", "按自己的节奏活动", "留一分钟回顾今天"])
    store.save_nutrition_profile(dict(age=32,sex='male',height=172,weight=73.4,activity='sedentary',restrictions=''))
    for index in range(18):
        if index in (3, 9):
            continue
        day = date.today() - timedelta(days=17-index)
        store.save_record({"day": day.isoformat(), "weight_kg": round(75-index*.09 + (index%3)*.08, 2),
                           "diet": "早餐：鸡蛋、牛奶和面包；午餐：米饭、青菜和鱼。", "activity": "散步", "minutes": 25,
                           "steps": 6200+index*40, "reflection": "今天记得出门走走，为自己留了时间。"})
        if index%2 == 0:
            for habit in store.habits()[:2]:
                store.set_completed(habit["id"], day.isoformat(), True)
        if index>=8:
            for meal in ('breakfast','lunch','dinner'):
                store.record_plan(day.isoformat(),meal)
            if index%3!=0:
                store.set_nutrition_day(day.isoformat(),complete=True)
    window = Window(store, show_onboarding=False)
    window.resize(1240, 840)
    window.show()
    app.processEvents()
    QTest.qWait(200)
    from .ai_smoke import check_ai
    ai_result = check_ai(window)
    screenshots = []
    for name in ("today", "diet", "records", "trends", "ai", "settings"):
        window.change_page(name)
        app.processEvents()
        QTest.qWait(80)
        window.stack.currentWidget().verticalScrollBar().setValue(0)
        app.processEvents()
        target = output / f"{name}.png"
        assert window.grab().save(str(target)), "Screenshot failed"
        screenshots.append(str(target))
        if name == 'ai':
            area = window.stack.currentWidget()
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
            app.processEvents()
            assert window.grab().save(str(output/'ai-followup.png'))
    from .ai_ui import RequestPreview
    from .ai import daily_context, report_messages
    preview = RequestPreview(store.ai_config(), report_messages(daily_context(store, date.today().isoformat())), window)
    preview.show()
    app.processEvents()
    assert preview.grab().save(str(output/'ai-request-preview.png'))
    preview.close()
    window.change_page(0)
    window.today_form.weight.setText("73.2")
    window.today_form.diet.setPlainText("独立 EXE 冒烟测试：记录保存。")
    QTest.mouseClick(window.today_form.save_button, Qt.LeftButton)
    assert store.record(date.today().isoformat())["weight_kg"] == 73.2
    entry_count=len(store.entries(date.today().isoformat()))
    assert entry_count==3
    before_total=store.day_nutrition(date.today().isoformat())['kcal']
    # Clicking the plan twice must not create a duplicate real meal.
    store.record_plan(date.today().isoformat(),'lunch')
    assert len(store.entries(date.today().isoformat()))==entry_count
    assert len(store.ai_sessions(date.today().isoformat())) == 1
    assert len(store.ai_messages(store.ai_sessions(date.today().isoformat())[0]['id'])) == 2
    # Verify persisted reports with another database connection, not an in-memory cache.
    reopened = Store(store.directory)
    assert len(reopened.ai_sessions(date.today().isoformat())) == 1
    reopened.close()
    backup = output / "smoke-backup.sqlite3"
    store.backup(backup)
    store.delete_record(date.today().isoformat())
    store.restore(backup)
    assert not (store.directory / 'api-key.dpapi').exists()
    assert len(store.ai_sessions(date.today().isoformat())) == 1
    assert len(store.ai_messages(store.ai_sessions(date.today().isoformat())[0]['id'])) == 2
    assert store.record(date.today().isoformat())["weight_kg"] == 73.2
    assert store.day_nutrition(date.today().isoformat())['kcal']==before_total
    assert len(store.entries(date.today().isoformat()))==entry_count
    guard = SingleInstance(store.directory)
    assert guard.acquire()
    guard.window = window
    other = SingleInstance(store.directory)
    assert not other.acquire()
    app.processEvents()
    guard.server.close()
    report = {"ok": True, "frozen": bool(getattr(sys, "frozen", False)), "python": sys.version,
              "screenshots": screenshots, "record_save": True, "backup_restore": True, "single_instance": True,
              "network_required": False, "data_isolated": True,"version":"1.2.0",
              "food_count":len(store.foods()),"meal_template_count":len(__import__('lightdiary.nutrition',fromlist=['catalog']).catalog()['templates']),
              "nutrition_record":True,"plan_idempotent":True,"nutrition_backup_restore":True,
              "ai_backup_restore":True,"ai_restart_persistence":True, **ai_result}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    window.timer.stop()
    window.tray.hide()
    window._quitting = True
    window.close()
    store.close()
    temporary.cleanup()
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", type=Path)
    parser.add_argument("--generate-icon", type=Path)
    parser.add_argument("--test-exit-after", type=int, default=0)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    if app.platformName() == "offscreen":
        # The offscreen Windows plugin does not discover system fonts itself.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            if (fonts / name).exists():
                QFontDatabase.addApplicationFont(str(fonts / name))
    app.setApplicationName("轻盈日记")
    app.setOrganizationName("LightDiary")
    app.setApplicationVersion("1.2.0")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(app_pixmap()))
    if args.generate_icon:
        args.generate_icon.parent.mkdir(parents=True, exist_ok=True)
        if not app_pixmap(256).save(str(args.generate_icon), "ICO"):
            raise RuntimeError("Icon export failed")
        return 0
    if args.smoke_test:
        return smoke(app, args.smoke_test)
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=directory / "application.log", encoding="utf-8", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    guard = SingleInstance(directory)
    try:
        if not guard.acquire():
            return 0
        store = Store(directory)
        window = Window(store)
    except Exception as error:
        logging.error("Startup failed (%s)", type(error).__name__)
        QMessageBox.critical(None, "轻盈日记暂时无法启动", str(error) + f"\n\n数据目录：{directory}")
        return 1
    guard.window = window

    def exception_hook(kind, value, traceback):
        # Exception values can contain user text; log only code locations and type.
        import traceback as traceback_module
        locations = [(Path(frame.filename).name, frame.lineno, frame.name)
                     for frame in traceback_module.extract_tb(traceback)]
        logging.error("Application error %s at %s", kind.__name__, locations)
        QMessageBox.warning(window, "这个操作暂时没有完成", "请重试。详细信息已写入本机日志，已有记录会保留。")

    sys.excepthook = exception_hook
    window.show()
    if args.test_exit_after:
        QTimer.singleShot(args.test_exit_after * 1000, window.quit_app)
    result = app.exec()
    guard.server.close()
    store.close()
    return result
