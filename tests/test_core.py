import csv
import json
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from lightdiary.storage import Store, APP_ID, DEFAULT_HABITS
from lightdiary.logic import weekly_stats, display_weight, progress, encouragement, reminder_due


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "中文 数据")
        self.today = date.today().isoformat()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def record(self, **values):
        return {"day": self.today, "weight_kg": 70.5, **values}

    def test_create_update_persist_delete_and_missing_numbers(self):
        self.assertFalse(self.store.settings()["onboarded"])
        self.store.save_record(self.record())
        self.store.save_record(self.record(weight_kg=69.8, diet="午餐：青菜"))
        self.assertEqual(len(self.store.records()), 1)
        self.assertEqual(self.store.record(self.today)["weight_kg"], 69.8)
        self.assertIsNone(self.store.record(self.today)["steps"])
        self.store.close()
        self.store = Store(self.root / "中文 数据")
        self.assertEqual(self.store.record(self.today)["diet"], "午餐：青菜")
        self.store.delete_record(self.today)
        self.assertEqual(self.store.records(), [])

    def test_text_only_and_zero_steps_are_valid(self):
        self.store.save_record({"day": self.today, "diet": "只记了一餐", "steps": 0})
        self.assertIsNone(self.store.record(self.today)["weight_kg"])
        self.assertEqual(self.store.record(self.today)["steps"], 0)

    def test_bad_records_do_not_mutate(self):
        for values in [{"weight_kg": 0}, {"weight_kg": math.nan}, {"weight_kg": math.inf},
                       {"weight_kg": -1}, {"steps": "4.5"}, {"minutes": 1441},
                       {"day": "2025-02-30"}, {"day": (date.today()+timedelta(days=1)).isoformat()}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.store.save_record(self.record(**values))
        with self.assertRaises(ValueError):
            self.store.save_record({"day": self.today})
        self.assertEqual(self.store.records(), [])

    def test_backdated_records_are_ordered(self):
        self.store.save_record(self.record())
        before = (date.today()-timedelta(days=12)).isoformat()
        self.store.save_record(self.record(day=before))
        self.assertEqual([row["day"] for row in self.store.records()], [before, self.today])

    def test_profile_habit_changes_preserve_history(self):
        ident = self.store.habits()[0]["id"]
        self.store.set_completed(ident, self.today, True)
        self.store.save_profile(80, 65, "更有精神", "jin", [DEFAULT_HABITS[0], "睡前放松"], False, "19:45")
        self.assertIn(ident, self.store.completed(self.today))
        self.assertEqual(len(self.store.habits()), 2)
        self.assertFalse(self.store.settings()["reminder_enabled"])
        self.store.set_completed(ident, self.today, False)
        self.assertEqual(self.store.completed(self.today), set())

    def test_invalid_profile_keeps_settings(self):
        original = self.store.settings()
        for target, names in [(90, ["散步"]), (70, []), (70, ["重复", "重复"])]:
            with self.assertRaises(ValueError):
                self.store.save_profile(80, target, "", "kg", names)
        self.assertEqual(self.store.settings(), original)

    def test_full_backup_restore_and_safety_copy(self):
        self.store.save_profile(75, 68, "想更轻松", "jin", ["散步"])
        self.store.save_record(self.record())
        self.store.set_completed(self.store.habits()[0]["id"], self.today, True)
        self.store.mark_reminded(self.today, "test")
        backup = self.root / "备份 文件.sqlite3"
        self.store.backup(backup)
        self.store.delete_record(self.today)
        self.store.update_settings({"unit": "kg"})
        safety = self.store.restore(backup)
        self.assertTrue(safety.exists())
        self.assertEqual(self.store.settings()["unit"], "jin")
        self.assertEqual(self.store.record(self.today)["weight_kg"], 70.5)
        self.assertTrue(self.store.completed(self.today))
        self.assertTrue(self.store.was_reminded(self.today))
        with closing(sqlite3.connect(safety)) as saved:
            self.assertEqual(saved.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0)

    def test_rejects_invalid_foreign_and_incompatible_backup(self):
        self.store.save_record(self.record())
        bad = self.root / "bad.sqlite3"
        bad.write_bytes(b"not a database")
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        bad.unlink()
        with closing(sqlite3.connect(bad)) as other:
            other.execute("CREATE TABLE unrelated(value)")
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        bad.unlink()
        self.store.backup(bad)
        with closing(sqlite3.connect(bad)) as other:
            other.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        self.assertEqual(self.store.record(self.today)["weight_kg"], 70.5)
        with self.assertRaises(ValueError):
            self.store.backup(self.store.path)
        with self.assertRaises(ValueError):
            self.store.restore(self.store.path)

    def test_csv_chinese_units_optional_and_formula_safety(self):
        self.store.update_settings({"unit": "jin"})
        self.store.save_record(self.record(diet="=危险公式", activity="散步", reflection="很好"))
        destination = self.root / "日常.csv"
        self.store.export_csv(destination)
        with destination.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertIn("斤", rows[0][1])
        self.assertEqual(rows[1][1], "141.0")
        self.assertEqual(rows[1][2], "'=危险公式")
        self.assertEqual(rows[1][5], "")

    def test_reminder_survives_restart(self):
        self.assertTrue(self.store.mark_reminded(self.today, "first"))
        self.assertFalse(self.store.mark_reminded(self.today, "second"))
        self.store.close()
        self.store = Store(self.root / "中文 数据")
        self.assertTrue(self.store.was_reminded(self.today))


class LogicTests(unittest.TestCase):
    def test_units_and_target_progress(self):
        self.assertEqual(display_weight(70.5, "jin"), "141.0")
        self.assertEqual(display_weight(None), "—")
        self.assertEqual(progress(80, 70, 75), 50)
        self.assertEqual(progress(80, 70, 83), 0)
        self.assertEqual(progress(80, 70, 68), 100)
        self.assertEqual(progress(70, 70, 70), 100)

    def test_sparse_average_never_counts_missing_as_zero(self):
        today = date.today()
        rows = [{"day": today.isoformat(), "weight_kg": 70, "minutes": None, "activity": ""},
                {"day": (today-timedelta(days=3)).isoformat(), "weight_kg": None, "minutes": 20, "activity": "散步"},
                {"day": (today-timedelta(days=6)).isoformat(), "weight_kg": 72, "minutes": None, "activity": ""}]
        stats = weekly_stats(rows)
        self.assertEqual(stats["average"], 71)
        self.assertEqual(stats["weight_days"], 2)
        self.assertEqual(stats["record_days"], 3)
        self.assertEqual(stats["minutes"], 20)
        self.assertIsNone(stats["difference"])
        self.assertIsNone(weekly_stats([])["average"])

    def test_week_comparison_requires_two_each(self):
        today = date.today()
        rows = [{"day": (today-timedelta(days=i)).isoformat(), "weight_kg": weight, "minutes": None, "activity": ""}
                for i, weight in [(0, 70), (6, 72), (7, 73), (13, 75)]]
        self.assertEqual(weekly_stats(rows)["difference"], -3)
        self.assertIsNone(weekly_stats(rows[:-1])["difference"])

    def test_supportive_copy_first_return_and_completion(self):
        self.assertIn("一小步", encouragement([])[0])
        old = [{"day": (date.today()-timedelta(days=5)).isoformat()}]
        self.assertIn("欢迎回来", encouragement(old)[0])
        current = [{"day": date.today().isoformat()}]
        self.assertIn("2", encouragement(current, 2)[0])

    def test_reminder_time_pause_resume_and_missed_window(self):
        settings = {"onboarded": True, "reminder_enabled": True, "reminder_time": "20:30"}
        base = datetime.now().replace(hour=20, minute=30, second=0, microsecond=0)
        self.assertTrue(reminder_due(settings, base))
        self.assertFalse(reminder_due(settings, base-timedelta(seconds=1)))
        self.assertTrue(reminder_due(settings, base+timedelta(minutes=9)))
        self.assertFalse(reminder_due(settings, base+timedelta(minutes=10)))
        self.assertFalse(reminder_due(settings, base, already_sent=True))
        self.assertFalse(reminder_due(settings, base, paused=True))
        self.assertFalse(reminder_due({**settings, "reminder_enabled": False}, base))


if __name__ == "__main__":
    unittest.main()
