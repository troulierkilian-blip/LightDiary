"""SQLite persistence. All user data lives outside the executable."""
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from .diet_storage import NutritionStore, TABLES, migrate_nutrition
from .nutrition import PROFILE_DEFAULT
from .ai_storage import AIStore, AI_TABLES, migrate_ai

APP_ID = 0x4C444952
SCHEMA_VERSION = 3
DEFAULT_HABITS = ["记下今天的饮食", "按自己的节奏活动", "留一分钟回顾今天"]
DEFAULTS = {
    "unit": "kg", "reason": "", "start_weight": None, "target_weight": None,
    "reminder_enabled": True, "reminder_time": "20:30", "onboarded": False,
    "nutrition_profile": PROFILE_DEFAULT,
    "ai_config": {"endpoint": "", "model": ""}, "ai_key_token": "",
}


def data_directory() -> Path:
    override = os.environ.get("LIGHTDIARY_DATA_DIR")
    if override:
        return Path(override).resolve()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return base / "LightDiary"


def valid_day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("请选择有效日期。") from None
    if parsed.isoformat() != value or parsed > date.today():
        raise ValueError("只能记录今天或过去的日期。")
    return value


def number(value, label, maximum, integer=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label}需要填写数字。")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}需要填写数字。") from None
    if not math.isfinite(parsed) or parsed < 0 or parsed > maximum:
        raise ValueError(f"{label}应在 0 到 {maximum:g} 之间。")
    if integer and not parsed.is_integer():
        raise ValueError(f"{label}请填写整数。")
    return int(parsed) if integer else parsed


class Store(NutritionStore, AIStore):
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "diary.sqlite3"
        self.connection = sqlite3.connect(self.path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        app_id = self.connection.execute("PRAGMA application_id").fetchone()[0]
        if version > SCHEMA_VERSION or app_id not in (0, APP_ID):
            self.connection.close()
            raise ValueError("数据文件版本不兼容，请保留文件并使用对应版本的软件。")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (
                day TEXT PRIMARY KEY, weight_kg REAL, diet TEXT NOT NULL DEFAULT '',
                activity TEXT NOT NULL DEFAULT '', minutes INTEGER, steps INTEGER,
                calories INTEGER, reflection TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1,
                position INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS completions (
                habit_id INTEGER NOT NULL REFERENCES habits(id), day TEXT NOT NULL,
                PRIMARY KEY(habit_id, day)
            );
            CREATE TABLE IF NOT EXISTS reminders (day TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
        """)
        try:
            if 0 < version < SCHEMA_VERSION:
                self.backup(self.directory / f"before-upgrade-v{version}-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
            with self.connection:
                # Explicit BEGIN makes SQLite DDL transactional too.
                self.connection.execute('BEGIN')
                self.connection.execute(f"PRAGMA application_id={APP_ID}")
                if version < 2:
                    migrate_nutrition(self.connection)
                if version < 3:
                    migrate_ai(self.connection)
                for key, value in DEFAULTS.items():
                    self.connection.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
                if not self.connection.execute("SELECT 1 FROM habits LIMIT 1").fetchone():
                    for index, name in enumerate(DEFAULT_HABITS):
                        self.connection.execute("INSERT INTO habits(name,position) VALUES (?,?)", (name, index))
                self.connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        except Exception:
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def settings(self) -> dict:
        return {row["key"]: json.loads(row["value"]) for row in self.connection.execute("SELECT * FROM settings")}

    def update_settings(self, values: dict):
        with self.connection:
            for key, value in values.items():
                self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_profile(self, start, target, reason, unit, names, enabled=True, reminder_time="20:30"):
        start = number(start, "起始体重", 500)
        target = number(target, "目标体重", 500)
        if not start or not target:
            raise ValueError("请填写大于 0 的起始体重和目标体重。")
        if target > start:
            raise ValueError("减重目标应小于或等于起始体重。")
        if unit not in ("kg", "jin"):
            raise ValueError("请选择公斤或斤。")
        names = [str(name).strip() for name in names if str(name).strip()]
        if not 1 <= len(names) <= 8 or len(set(names)) != len(names) or any(len(name) > 40 for name in names):
            raise ValueError("请设置 1～8 个不同的小目标，每个不超过 40 字。")
        try:
            if datetime.strptime(reminder_time, "%H:%M").strftime("%H:%M") != reminder_time:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("提醒时间应为 HH:MM 格式。") from None
        with self.connection:
            values = {"start_weight": start, "target_weight": target, "reason": str(reason).strip()[:1000],
                      "unit": unit, "reminder_enabled": bool(enabled), "reminder_time": reminder_time, "onboarded": True}
            for key, value in values.items():
                self.connection.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
            self.connection.execute("UPDATE habits SET active=0")
            for index, name in enumerate(names):
                self.connection.execute("""INSERT INTO habits(name,active,position) VALUES (?,1,?)
                    ON CONFLICT(name) DO UPDATE SET active=1,position=excluded.position""", (name, index))

    def habits(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM habits WHERE active=1 ORDER BY position,id")]

    def completed(self, day: str):
        return {row[0] for row in self.connection.execute("SELECT habit_id FROM completions WHERE day=?", (day,))}

    def set_completed(self, habit_id: int, day: str, checked: bool):
        valid_day(day)
        if not self.connection.execute("SELECT 1 FROM habits WHERE id=? AND active=1", (habit_id,)).fetchone():
            raise ValueError("这个小目标已被修改，请刷新后重试。")
        with self.connection:
            if checked:
                self.connection.execute("INSERT OR IGNORE INTO completions VALUES (?,?)", (habit_id, day))
            else:
                self.connection.execute("DELETE FROM completions WHERE habit_id=? AND day=?", (habit_id, day))

    def record(self, day: str):
        row = self.connection.execute("SELECT * FROM records WHERE day=?", (day,)).fetchone()
        return dict(row) if row else None

    def records(self, first: str | None = None, last: str | None = None):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM records WHERE (? IS NULL OR day>=?) AND (? IS NULL OR day<=?) ORDER BY day",
            (first, first, last, last))]

    def save_record(self, value: dict):
        day = valid_day(value.get("day", ""))
        weight = number(value.get("weight_kg"), "体重", 500)
        if weight == 0:
            raise ValueError("体重应大于 0，也可以留空。")
        minutes = number(value.get("minutes"), "运动时长", 1440, True)
        steps = number(value.get("steps"), "步数", 200000, True)
        calories = number(value.get("calories"), "热量", 30000, True)
        texts = [str(value.get(key) or "").strip() for key in ("diet", "activity", "reflection")]
        if any(len(text) > 4000 for text in texts):
            raise ValueError("每项文字记录请控制在 4000 字以内。")
        if all(item is None for item in (weight, minutes, steps, calories)) and not any(texts):
            raise ValueError("写下一项内容就可以保存，其他项目可以留空。")
        with self.connection:
            self.connection.execute("""INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET weight_kg=excluded.weight_kg,diet=excluded.diet,
                activity=excluded.activity,minutes=excluded.minutes,steps=excluded.steps,
                calories=excluded.calories,reflection=excluded.reflection,updated_at=excluded.updated_at""",
                (day, weight, texts[0], texts[1], minutes, steps, calories, texts[2], datetime.now().isoformat(timespec="seconds")))
            state = self.connection.execute('SELECT source FROM nutrition_days WHERE day=?', (day,)).fetchone()
            if state and state[0] == 'manual':
                self.connection.execute('UPDATE nutrition_days SET complete=0 WHERE day=?', (day,))

    def delete_record(self, day: str):
        with self.connection:
            self.connection.execute("DELETE FROM records WHERE day=?", (day,))
            self.connection.execute('UPDATE nutrition_days SET complete=0 WHERE day=? AND source=\'manual\'', (day,))

    def mark_reminded(self, day: str, when: str) -> bool:
        with self.connection:
            cursor = self.connection.execute("INSERT OR IGNORE INTO reminders VALUES (?,?)", (day, when))
        return cursor.rowcount == 1

    def was_reminded(self, day: str) -> bool:
        return self.connection.execute("SELECT 1 FROM reminders WHERE day=?", (day,)).fetchone() is not None

    def export_csv(self, destination: Path):
        unit = self.settings()["unit"]
        factor = 2 if unit == "jin" else 1
        with Path(destination).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["日期", f"体重（{'斤' if unit == 'jin' else '公斤'}）", "饮食备注", "运动项目", "运动分钟", "步数", "旧版手填热量（千卡）", "今日回顾", "完成的小目标", '当前摄入热量（千卡）','蛋白质（克）','脂肪（克）','碳水（克）','目标快照（千卡）','热量来源','饮食记录完整'])
            existing = {row['day']:row for row in self.records()}
            days = set(existing) | {row[0] for row in self.connection.execute('SELECT DISTINCT day FROM meal_entries')}
            for day in sorted(days):
                row = existing.get(day,dict(day=day,weight_kg=None,diet='',activity='',minutes=None,steps=None,calories=None,reflection=''))
                names = [entry[0] for entry in self.connection.execute("""SELECT habits.name FROM completions
                    JOIN habits ON habits.id=completions.habit_id WHERE day=? ORDER BY habits.position""", (row["day"],))]
                values = [row["day"], "" if row["weight_kg"] is None else round(row["weight_kg"] * factor, 2),
                          row["diet"], row["activity"], row["minutes"], row["steps"], row["calories"], row["reflection"], "；".join(names)]
                totals = self.day_nutrition(day)
                values += [totals[key] for key in ('kcal','protein','fat','carbs','target')] + [('餐食明细' if totals['source']=='details' else '手动全天总量'),('是' if totals['complete'] else '否')]
                writer.writerow([("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value) for value in values])

    def backup(self, destination: Path):
        destination = Path(destination).resolve()
        if destination == self.path.resolve():
            raise ValueError("备份位置不能是当前使用的数据文件。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".lightdiary-", suffix=".sqlite3", dir=destination.parent)
        os.close(handle)
        try:
            with closing(sqlite3.connect(temporary)) as target:
                self.connection.backup(target)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def restore(self, source: Path) -> Path:
        source = Path(source).resolve()
        if source == self.path.resolve():
            raise ValueError("请选择导出的备份文件。")
        candidate = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            if candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份文件损坏，当前数据未修改。")
            version = candidate.execute("PRAGMA user_version").fetchone()[0]
            if candidate.execute("PRAGMA application_id").fetchone()[0] != APP_ID or version not in (1, 2, 3):
                raise ValueError("这不是兼容的轻盈日记备份，当前数据未修改。")
            for table in (("settings", "records", "habits", "completions", "reminders")
                          + (TABLES if version >= 2 else ()) + (AI_TABLES if version >= 3 else ())):
                expected = [(row[1], row[2], row[3], row[5]) for row in self.connection.execute(f"PRAGMA table_info({table})")]
                actual = [(row[1], row[2], row[3], row[5]) for row in candidate.execute(f"PRAGMA table_info({table})")]
                if expected != actual:
                    raise ValueError("备份结构不兼容，当前数据未修改。")
            config = {row[0]: json.loads(row[1]) for row in candidate.execute("SELECT * FROM settings")}
            required = set(DEFAULTS) - ({'nutrition_profile'} if version == 1 else set()) - ({'ai_config','ai_key_token'} if version < 3 else set())
            if not required.issubset(config) or config.get("unit") not in ("kg", "jin"):
                raise ValueError("备份设置不完整，当前数据未修改。")
            if candidate.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("备份中的记录不完整，当前数据未修改。")
            safety = self.directory / f"before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
            # Upgrade a private copy first. Invalid old backups never touch live data.
            with tempfile.TemporaryDirectory(prefix='lightdiary-restore-') as staging:
                staged_path = Path(staging) / 'diary.sqlite3'
                with closing(sqlite3.connect(staged_path)) as staged:
                    candidate.backup(staged)
                staged_store = Store(Path(staging))
                try:
                    from .nutrition import validate_profile, KEYS, MEALS
                    validate_profile(staged_store.nutrition_profile())
                    def validate_values(values):
                        if not isinstance(values,dict) or not set(KEYS).issubset(values):
                            raise ValueError('备份的营养数据不完整，当前数据未修改。')
                        for key in KEYS:
                            value=values[key]
                            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                                raise ValueError('备份包含无效营养值，当前数据未修改。')
                    def validate_items(items):
                        if not isinstance(items,list) or not items:
                            raise ValueError('备份的食物记录不完整，当前数据未修改。')
                        for item in items:
                            if not isinstance(item,dict) or not item.get('name') or not item.get('source') or not number(item.get('grams'),'食物份量',10000):
                                raise ValueError('备份的食物记录不完整，当前数据未修改。')
                            validate_values(item.get('nutrients'))
                    for row in staged_store.connection.execute('SELECT day,meal,snapshot FROM meal_plans'):
                        plan=json.loads(row[2])
                        if plan['day']!=row[0] or plan['meal']!=row[1] or row[1] not in MEALS or not plan.get('template_id') or not plan.get('name'):
                            raise ValueError('备份的计划信息不完整。')
                        validate_items(plan['items'])
                        validate_values(plan['nutrients'])
                    for row in staged_store.connection.execute('SELECT meal,items FROM meal_entries'):
                        if row[0] not in MEALS:raise ValueError('备份包含无效餐次。')
                        validate_items(json.loads(row[1]))
                    for row in staged_store.connection.execute('SELECT snapshot FROM custom_foods'):
                        food=json.loads(row[0])
                        if not food.get('id') or not food.get('name') or not food.get('source') or food.get('unit') not in ('g','ml'):
                            raise ValueError('备份的自定义食物不完整。')
                        validate_values(food['nutrients'])
                        if not food.get('portions'):raise ValueError('备份缺少食物份量。')
                        for portion in food['portions']:
                            if not portion.get('label') or not number(portion.get('grams'),'默认份量',10000):raise ValueError('备份包含无效默认份量。')
                    staged_store.validate_ai_backup()
                    # A new binding invalidates any local secret even if deletion fails.
                    from uuid import uuid4
                    staged_store.update_settings({'ai_key_token': uuid4().hex})
                    self.backup(safety)
                    try:
                        staged_store.connection.backup(self.connection)
                    except sqlite3.Error:
                        with closing(sqlite3.connect(safety)) as original:
                            original.backup(self.connection)
                        raise
                    from .secrets import KeyVault
                    try:
                        KeyVault(self.directory).clear()
                    except OSError:
                        pass  # The restored binding cannot decrypt/use the old key.
                finally:
                    staged_store.close()
            return safety
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
            raise ValueError("无法读取这个备份，当前数据未修改。") from error
        finally:
            candidate.close()
