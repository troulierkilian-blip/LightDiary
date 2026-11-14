import csv
import json
import math
import sqlite3
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt,QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from lightdiary.storage import Store,APP_ID
from lightdiary.nutrition import catalog,estimate_target,food_item,nutrients_sum,make_plan
from lightdiary.diet_ui import MealEditor,LabelDialog
from lightdiary.window import Window

class NutritionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'data')
        self.day=date.today().isoformat()
        self.profile=dict(age=30,sex='male',height=170,weight=75,activity='sedentary')
        self.store.save_nutrition_profile(self.profile)
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
    def test_formula_floor_manual_and_ineligible(self):
        self.assertEqual(estimate_target(self.profile)['target'],1700)
        self.assertEqual(estimate_target({**self.profile,'sex':'female'})['target'],1530)
        self.assertEqual(estimate_target({**self.profile,'age':75,'height':160,'weight':55})['target'],1500)
        for values in [dict(age=17),dict(special=True),dict(weight=40),dict(height=None)]:
            self.assertIsNone(estimate_target({**self.profile,**values})['target'])
        self.assertEqual(estimate_target(dict(mode='manual',manual=1850))['target'],1850)
        for values in [dict(weight=math.nan),dict(height=-1),dict(age=30.2),dict(manual=math.inf)]:
            with self.assertRaises(ValueError): estimate_target({**self.profile,**values})
    def test_catalog_and_meal_balance(self):
        self.assertGreaterEqual(len(catalog()['foods']),60)
        self.assertGreaterEqual(len(catalog()['templates']),30)
        for meal,fraction in [('breakfast',.3),('lunch',.4),('dinner',.3)]:
            plan=make_plan(self.day,meal,1800)
            self.assertLess(abs(plan['nutrients']['kcal']-1800*fraction),180)
            self.assertTrue(all(i['source'] for i in plan['items']))
    def test_portions_labels_and_unknown_nutrients(self):
        rice=next(f for f in self.store.foods() if f['id']=='rice')
        item=food_item(rice,1,rice['portions'][0])
        self.assertEqual(item['grams'],150)
        self.assertAlmostEqual(item['nutrients']['kcal'],195)
        custom=self.store.save_custom_food('试用食品',{'kcal':200},basis=50)
        item=food_item(custom,25)
        self.assertEqual(item['nutrients']['kcal'],100)
        self.assertIsNone(nutrients_sum([item])['protein'])
        self.store.save_entry(self.day,'snack','标签',[item])
        self.assertIsNone(self.store.day_nutrition(self.day)['protein'])
        with self.assertRaises(ValueError): food_item(rice,0)
    def test_plan_separation_idempotence_swap_and_future(self):
        original=self.store.plan(self.day,'lunch')
        self.assertIsNone(self.store.day_nutrition(self.day)['kcal'])
        ident=self.store.record_plan(self.day,'lunch')
        self.assertEqual(self.store.record_plan(self.day,'lunch'),ident)
        self.assertEqual(len(self.store.entries(self.day)),1)
        replacement=self.store.plan(self.day,'lunch',replace=True)
        self.assertNotEqual(original['template_id'],replacement['template_id'])
        self.assertEqual(self.store.entries(self.day)[0]['title'],original['name'])
        future=(date.today()+timedelta(days=1)).isoformat()
        self.store.plan(future,'dinner')
        with self.assertRaises(ValueError):self.store.record_plan(future,'dinner')
    def test_restrictions_never_silently_fall_back(self):
        plan=make_plan(self.day,'lunch',1800,'海鲜,鸡肉,牛肉,猪肉,蛋')
        self.assertNotIn('虾',' '.join(i['name'] for i in plan['items']))
        with self.assertRaises(ValueError): make_plan(self.day,'lunch',1800,'米,面,土豆,红薯,玉米,藜麦,小米,小麦')
    def test_target_and_nutrition_snapshots(self):
        past=(date.today()-timedelta(days=2)).isoformat()
        self.store.plan(past,'lunch')
        target=self.store.day_nutrition(past)['target']
        self.store.record_plan(past,'lunch')
        saved=self.store.day_nutrition(past)['kcal']
        self.store.save_nutrition_profile(dict(mode='manual',manual=2100))
        self.assertEqual(self.store.day_nutrition(past)['target'],target)
        self.assertEqual(self.store.day_nutrition(past)['kcal'],saved)
        self.assertEqual(self.store.ensure_nutrition_day(self.day)['target'],2100)
    def test_manual_source_never_double_counts_and_completion(self):
        self.store.record_plan(self.day,'breakfast')
        details=self.store.day_nutrition(self.day)['kcal']
        self.store.save_record(dict(day=self.day,calories=1800))
        self.assertAlmostEqual(self.store.day_nutrition(self.day)['kcal'],details)
        self.store.set_nutrition_day(self.day,source='manual')
        self.assertEqual(self.store.day_nutrition(self.day)['kcal'],1800)
        self.assertIsNone(self.store.day_nutrition(self.day)['protein'])
        self.store.set_nutrition_day(self.day,complete=True)
        self.assertEqual(self.store.nutrition_stats(7)['complete'],1)
        self.store.save_record(dict(day=self.day,calories=1790))
        self.assertFalse(self.store.day_nutrition(self.day)['complete'])
    def test_edit_delete_invalidate_complete_and_missing_not_zero(self):
        ident=self.store.record_plan(self.day,'lunch')
        self.store.set_nutrition_day(self.day,complete=True)
        entry=self.store.entries(self.day)[0]
        self.store.save_entry(self.day,'lunch','更新',entry['items'],ident)
        self.assertFalse(self.store.day_nutrition(self.day)['complete'])
        self.assertEqual(self.store.nutrition_stats(30)['logged'],1)
        self.assertIsNone(self.store.nutrition_stats(30)['average'])
        self.store.delete_entry(ident)
        self.assertIsNone(self.store.day_nutrition(self.day)['kcal'])
        self.assertEqual(self.store.nutrition_stats(30)['logged'],0)
        with self.assertRaises(ValueError): self.store.set_nutrition_day(self.day,complete=True)
    def test_backup_restart_and_exports(self):
        self.store.record_plan(self.day,'lunch')
        custom=self.store.save_custom_food('=自定义',dict(kcal=100,protein=3,fat=2,carbs=15))
        self.store.save_entry(self.day,'snack','=标签',[food_item(custom,100)])
        self.store.set_nutrition_day(self.day,complete=True)
        backup=self.root/'full.sqlite3'
        self.store.backup(backup)
        self.store.delete_entry(self.store.entries(self.day)[0]['id'])
        self.store.restore(backup)
        self.assertEqual(len(self.store.entries(self.day)),2)
        self.assertTrue(self.store.day_nutrition(self.day)['complete'])
        self.store.close()
        self.store=Store(self.root/'data')
        self.assertEqual(len(self.store.entries(self.day)),2)
        self.store.export_csv(self.root/'daily.csv')
        self.store.export_meals_csv(self.root/'meals.csv')
        with (self.root/'meals.csv').open(encoding='utf-8-sig') as stream:
            rows=list(csv.reader(stream))
        self.assertTrue(any("'=自定义" in row for row in rows))
        self.assertIn('当前摄入热量',(self.root/'daily.csv').read_text(encoding='utf-8-sig'))
    def make_v1(self):
        folder=self.root/'v1'
        old=Store(folder)
        old.save_record(dict(day=self.day,weight_kg=71,calories=1800,diet='旧记录'))
        old.close()
        connection=sqlite3.connect(folder/'diary.sqlite3')
        with connection:
            for table in ('nutrition_days','meal_plans','meal_entries','custom_foods'):connection.execute('DROP TABLE '+table)
            connection.execute("DELETE FROM settings WHERE key='nutrition_profile'")
            connection.execute('PRAGMA user_version=1')
        connection.close()
        return folder
    def test_v1_upgrade_backup_and_old_restore(self):
        folder=self.make_v1()
        old_backup=self.root/'v1-backup.sqlite3'
        old_backup.write_bytes((folder/'diary.sqlite3').read_bytes())
        migrated=Store(folder)
        self.assertEqual(migrated.record(self.day)['diet'],'旧记录')
        self.assertEqual(migrated.connection.execute('PRAGMA user_version').fetchone()[0],3)
        self.assertTrue(list(folder.glob('before-upgrade-v1-*.sqlite3')))
        self.assertEqual(migrated.day_nutrition(self.day)['source'],'manual')
        migrated.close()
        self.store.restore(old_backup)
        self.assertEqual(self.store.record(self.day)['weight_kg'],71)
        self.assertEqual(self.store.connection.execute('PRAGMA user_version').fetchone()[0],3)
    def test_migration_failure_rolls_back(self):
        folder=self.make_v1()
        def failed(connection):
            connection.execute('CREATE TABLE should_rollback(x)')
            connection.execute('PRAGMA user_version=2')
            raise sqlite3.OperationalError('injected migration failure')
        with patch('lightdiary.storage.migrate_nutrition',failed),self.assertRaises(sqlite3.Error):Store(folder)
        connection=sqlite3.connect(folder/'diary.sqlite3')
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],1)
        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='should_rollback'").fetchone())
        self.assertEqual(connection.execute('SELECT diet FROM records').fetchone()[0],'旧记录')
        connection.close()

    def test_corrupt_nutrition_snapshot_does_not_replace_current_data(self):
        self.store.record_plan(self.day,'lunch')
        original=self.store.day_nutrition(self.day)['kcal']
        backup=self.root/'corrupt.sqlite3'
        self.store.backup(backup)
        connection=sqlite3.connect(backup)
        with connection:connection.execute("UPDATE meal_entries SET items='[{}]'")
        connection.close()
        with self.assertRaises(ValueError):self.store.restore(backup)
        self.assertEqual(self.store.day_nutrition(self.day)['kcal'],original)

class NutritionInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name))
        self.store.save_nutrition_profile(dict(mode='manual',manual=1800))
        self.window=Window(self.store,show_onboarding=False)
        self.window.timer.stop()
    def tearDown(self):
        self.window._quitting=True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.store.close()
        self.temp.cleanup()
    def test_diet_page_record_repeat_and_stable_navigation(self):
        self.window.change_page('diet')
        page=self.window.diet_page
        page.record_plan('lunch')
        self.assertEqual(page.table.rowCount(),1)
        with patch.object(page,'open_editor') as edit:page.record_plan('lunch');edit.assert_called_once()
        self.assertEqual(len(self.store.entries(page.day())),1)
        self.window.change_page('settings')
        self.assertEqual(self.window.stack.currentIndex(),self.window.page_ids['settings'])
        self.assertIn('千卡',self.window.nutrition_summary.text())
    def test_editor_portions_edit_and_favorite_unknown(self):
        editor=MealEditor(self.store,date.today().isoformat(),parent=self.window)
        editor.food.setCurrentIndex(editor.food.findData('rice'))
        editor.add_food()
        self.assertEqual(editor.items()[0]['grams'],150)
        editor.rows[0][1].setText('75')
        self.assertAlmostEqual(editor.items()[0]['nutrients']['kcal'],97.5)
        editor.save()
        self.assertEqual(len(self.store.entries(date.today().isoformat())),1)
        editor.deleteLater()
    def test_label_kj_optional_macro_and_future_disabled(self):
        dialog=LabelDialog(self.store,self.window)
        dialog.name.setText('饮料标签')
        dialog.energy_unit.setCurrentIndex(1)
        dialog.values['kcal'].setText('418.4')
        dialog.save()
        self.assertAlmostEqual(dialog.food['nutrients']['kcal'],100)
        self.assertIsNone(dialog.food['nutrients']['protein'])
        dialog.deleteLater()
        self.window.diet_page.date.setDate(QDate.currentDate().addDays(1))
        self.assertFalse(self.window.diet_page.add.isEnabled())
        self.assertFalse(self.window.diet_page.plan_cards['lunch'][2].isEnabled())
