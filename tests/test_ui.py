import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from lightdiary.storage import Store
from lightdiary.widgets import STYLE
from lightdiary.window import Window, SetupDialog
from lightdiary.application import SingleInstance


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.store.save_profile(80, 70, "想更有精神", "kg", ["散步", "回顾"])
        self.window = Window(self.store, show_onboarding=False)
        self.window.timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window._quitting = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()

    def test_quick_save_update_and_pages(self):
        form = self.window.today_form
        form.weight.setText("78.4")
        form.diet.setPlainText("午餐：米饭和蔬菜")
        QTest.mouseClick(form.save_button, Qt.LeftButton)
        self.assertEqual(self.store.record(date.today().isoformat())["weight_kg"], 78.4)
        self.assertEqual(self.window.table.rowCount(), 1)
        form.weight.setText("78.2")
        QTest.mouseClick(form.save_button, Qt.LeftButton)
        self.assertEqual(self.window.table.rowCount(), 1)
        for i, nav in enumerate(self.window.nav):
            QTest.mouseClick(nav, Qt.LeftButton)
            self.assertEqual(self.window.stack.currentIndex(), i)

    def test_units_preserve_saved_and_unsaved_inputs(self):
        form = self.window.today_form
        form.weight.setText("79")
        self.window.profile_form.unit.setCurrentIndex(1)
        self.assertEqual(self.window.profile_form.start.text(), "160")
        self.window.save_settings()
        self.assertEqual(form.weight.text(), "158")
        QTest.mouseClick(form.save_button, Qt.LeftButton)
        self.assertEqual(self.store.record(date.today().isoformat())["weight_kg"], 79)
        self.window.profile_form.unit.setCurrentIndex(0)
        self.window.save_settings()
        self.assertEqual(form.weight.text(), "79")

    def test_optional_saved_values_stay_collapsed_and_are_preserved(self):
        self.store.save_record({"day": date.today().isoformat(), "weight_kg": 78, "steps": 6500, "calories": 1800, "reflection": "今天很好"})
        self.window.today_form.more.setChecked(False)
        self.window.refresh(reload_form=True)
        form = self.window.today_form
        self.assertFalse(form.more.isChecked())
        self.assertEqual(form.steps.text(), "6500")
        form.weight.setText("77.9")
        QTest.mouseClick(form.save_button, Qt.LeftButton)
        self.assertEqual(self.store.record(date.today().isoformat())["steps"], 6500)
        self.assertEqual(self.store.record(date.today().isoformat())["reflection"], "今天很好")

    def test_invalid_save_and_habit_completion(self):
        form = self.window.today_form
        form.weight.setText("abc")
        QTest.mouseClick(form.save_button, Qt.LeftButton)
        self.assertEqual(self.store.records(), [])
        self.assertIn("数字", form.status.text())
        first = self.window.habit_layout.itemAt(0).widget()
        first.setChecked(True)
        self.assertEqual(len(self.store.completed(date.today().isoformat())), 1)
        self.assertIn("1 / 2", self.window.habit_count.text())

    def test_reminder_once_and_pause(self):
        now = datetime.now().replace(hour=20, minute=30, second=0, microsecond=0)
        with patch.object(self.window.tray, "showMessage") as notification:
            self.window.set_paused(True)
            self.window.tick(now)
            notification.assert_not_called()
            self.window.set_paused(False)
            self.window.tick(now)
            self.window.tick(now)
            self.assertEqual(notification.call_count, 1)

    def test_tray_close_restore_and_quit(self):
        with patch("lightdiary.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True), patch.object(self.window.tray, "showMessage"):
            self.window.close()
            self.assertFalse(self.window.isVisible())
            self.assertFalse(self.window._quitting)
            self.window.activate()
            self.assertTrue(self.window.isVisible())
            self.window.quit_app()
            self.assertTrue(self.window._quitting)
            self.assertFalse(self.window.timer.isActive())

    def test_setup_validation_and_start(self):
        dialog = SetupDialog(self.store)
        dialog.form.start.setText("")
        dialog.save()
        self.assertEqual(dialog.result(), 0)
        dialog.form.start.setText("80")
        dialog.save()
        self.assertEqual(dialog.result(), 1)

    def test_second_launch_activates_existing_window(self):
        first = SingleInstance(self.store.directory)
        self.assertTrue(first.acquire())
        first.window = self.window
        self.window.hide()
        second = SingleInstance(self.store.directory)
        self.assertFalse(second.acquire())
        QTest.qWait(100)
        self.assertTrue(self.window.isVisible())
        first.server.close()


if __name__ == "__main__":
    unittest.main()
