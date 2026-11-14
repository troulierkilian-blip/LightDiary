"""Nutrition persistence mixed into the existing Store."""
from __future__ import annotations
import csv
import json
from datetime import date, datetime, timedelta
from .nutrition import (KEYS, MEALS, PROFILE_DEFAULT, catalog, estimate_target, validate_profile,
                        make_plan, nutrients_sum, positive)

TABLES = ('nutrition_days', 'meal_plans', 'meal_entries', 'custom_foods')
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS nutrition_days (
 day TEXT PRIMARY KEY, target REAL, target_reason TEXT NOT NULL,
 source TEXT NOT NULL DEFAULT 'details' CHECK(source IN ('details','manual')),
 complete INTEGER NOT NULL DEFAULT 0 CHECK(complete IN (0,1))
);
CREATE TABLE IF NOT EXISTS meal_plans (
 day TEXT NOT NULL, meal TEXT NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(day,meal)
);
CREATE TABLE IF NOT EXISTS meal_entries (
 id INTEGER PRIMARY KEY, day TEXT NOT NULL, meal TEXT NOT NULL,
 title TEXT NOT NULL, items TEXT NOT NULL, plan_key TEXT UNIQUE, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS meal_entries_day ON meal_entries(day);
CREATE TABLE IF NOT EXISTS custom_foods (
 id INTEGER PRIMARY KEY, snapshot TEXT NOT NULL
);
'''


def checked_day(day, future=False):
    try:
        parsed = date.fromisoformat(day)
    except (ValueError, TypeError):
        raise ValueError('请选择有效日期。') from None
    if parsed.isoformat() != day or (not future and parsed > date.today()):
        raise ValueError('实际摄入只能记录今天或过去的日期。')
    return day


def migrate_nutrition(connection):
    """Caller owns one transaction so DDL, defaults and version commit together."""
    for statement in SCHEMA_SQL.split(';'):
        if statement.strip():
            connection.execute(statement)
    connection.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',
                       ('nutrition_profile', json.dumps(PROFILE_DEFAULT, ensure_ascii=False)))


class NutritionStore:
    def nutrition_profile(self):
        return {**PROFILE_DEFAULT, **self.settings().get('nutrition_profile', {})}

    def save_nutrition_profile(self, value):
        profile = validate_profile(value)
        estimate = estimate_target(profile)
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                    ('nutrition_profile', json.dumps(profile, ensure_ascii=False)))
            self.connection.execute('UPDATE nutrition_days SET target=?,target_reason=? WHERE day>=?',
                                    (estimate['target'], estimate['reason'], date.today().isoformat()))
            self.connection.execute('DELETE FROM meal_plans WHERE day>=?', (date.today().isoformat(),))
        return estimate

    def ensure_nutrition_day(self, day):
        checked_day(day, future=True)
        found = self.connection.execute('SELECT * FROM nutrition_days WHERE day=?', (day,)).fetchone()
        if not found:
            estimate = estimate_target(self.nutrition_profile())
            record = self.record(day)
            source = 'manual' if record and record['calories'] is not None else 'details'
            with self.connection:
                self.connection.execute('INSERT INTO nutrition_days(day,target,target_reason,source) VALUES (?,?,?,?)',
                                        (day, estimate['target'], estimate['reason'], source))
            found = self.connection.execute('SELECT * FROM nutrition_days WHERE day=?', (day,)).fetchone()
        return dict(found)

    def set_nutrition_day(self, day, source=None, complete=None):
        checked_day(day)
        self.ensure_nutrition_day(day)
        if source is not None and source not in ('details', 'manual'):
            raise ValueError('请选择餐食明细计算或手动全天总量。')
        if complete and self.day_nutrition(day)['kcal'] is None:
            raise ValueError('先记录餐食，或在日常记录中填写全天热量，再完成当天记录。')
        with self.connection:
            if source is not None:
                self.connection.execute('UPDATE nutrition_days SET source=?,complete=0 WHERE day=?', (source, day))
            if complete is not None:
                self.connection.execute('UPDATE nutrition_days SET complete=? WHERE day=?', (int(bool(complete)), day))

    def foods(self):
        custom = [json.loads(row[0]) for row in self.connection.execute('SELECT snapshot FROM custom_foods ORDER BY id')]
        return catalog()['foods'] + custom

    def save_custom_food(self, name, values, basis=100, unit='g', source=None):
        name = str(name).strip()
        if not name or len(name) > 100 or unit not in ('g', 'ml'):
            raise ValueError('填写 1–100 字的食物名称，并选择克或毫升。')
        basis = positive(basis, '标签对应份量', 10000)
        nutrients = {}
        for key in KEYS:
            raw = values.get(key)
            if raw is None or raw == '':
                nutrients[key] = None
                continue
            if isinstance(raw, bool):
                raise ValueError('营养值需要填写数字。')
            try:
                numeric = float(raw)
            except (TypeError, ValueError):
                raise ValueError('营养值需要填写数字。') from None
            import math
            if not math.isfinite(numeric) or numeric < 0 or numeric > 10000:
                raise ValueError('营养值需要是 0–10000 之间的数字。')
            nutrients[key] = numeric * 100 / basis
        if nutrients['kcal'] is None:
            raise ValueError('请填写标签热量；其余营养素可留空，软件会显示未知。')
        food = dict(name=name,category='custom',tags=[],unit=unit,nutrients=nutrients,
                    source=source or f'用户录入营养标签 / 每 {basis:g} {unit}；未经软件核验',
                    portions=[dict(label='标签一份',grams=basis),dict(label='半份',grams=basis/2)])
        with self.connection:
            cursor = self.connection.execute('INSERT INTO custom_foods(snapshot) VALUES (?)', ('{}',))
            food['id'] = f'custom-{cursor.lastrowid}'
            self.connection.execute('UPDATE custom_foods SET snapshot=? WHERE id=?', (json.dumps(food, ensure_ascii=False), cursor.lastrowid))
        return food

    def plan(self, day, meal, replace=False):
        checked_day(day, future=True)
        state = self.ensure_nutrition_day(day)
        if state['target'] is None:
            raise ValueError(state['target_reason'])
        previous = self.connection.execute('SELECT snapshot FROM meal_plans WHERE day=? AND meal=?', (day, meal)).fetchone()
        if previous and not replace:
            return json.loads(previous[0])
        result = make_plan(day, meal, state['target'], self.nutrition_profile()['restrictions'],
                           json.loads(previous[0])['template_id'] if previous else None)
        with self.connection:
            self.connection.execute('INSERT OR REPLACE INTO meal_plans VALUES (?,?,?)', (day, meal, json.dumps(result, ensure_ascii=False)))
        return result

    def entries(self, day):
        rows = self.connection.execute('SELECT * FROM meal_entries WHERE day=? ORDER BY id', (day,))
        return [{**dict(row), 'items': json.loads(row['items'])} for row in rows]

    def save_entry(self, day, meal, title, items, ident=None, plan_key=None):
        checked_day(day)
        if meal not in MEALS or not str(title).strip() or len(str(title)) > 200 or not items:
            raise ValueError('请选择餐次并至少添加一种食物。')
        for item in items:
            positive(item['grams'], '食物份量', 10000)
            if not item.get('name') or not item.get('source'):
                raise ValueError('食物快照缺少名称或来源。')
            import math
            for key in KEYS:
                value = item['nutrients'].get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0):
                    raise ValueError('营养值应为有限的非负数字。')
        self.ensure_nutrition_day(day)
        stamp = datetime.now().isoformat(timespec='seconds')
        encoded = json.dumps(items, ensure_ascii=False)
        with self.connection:
            if ident is None:
                cursor = self.connection.execute('INSERT INTO meal_entries(day,meal,title,items,plan_key,updated_at) VALUES (?,?,?,?,?,?)',
                                                (day,meal,str(title).strip(),encoded,plan_key,stamp))
                ident = cursor.lastrowid
            else:
                cursor = self.connection.execute('UPDATE meal_entries SET meal=?,title=?,items=?,updated_at=? WHERE id=? AND day=?',
                                                (meal,str(title).strip(),encoded,stamp,ident,day))
                if not cursor.rowcount:
                    raise ValueError('这条餐食已被删除，请刷新后重试。')
            self.connection.execute('UPDATE nutrition_days SET complete=0 WHERE day=?', (day,))
        return ident

    def record_plan(self, day, meal):
        checked_day(day)
        key = day + ':' + meal
        existing = self.connection.execute('SELECT id FROM meal_entries WHERE plan_key=?', (key,)).fetchone()
        if existing:
            return existing[0]
        plan = self.plan(day,meal)
        return self.save_entry(day,meal,plan['name'],plan['items'],plan_key=key)

    def delete_entry(self, ident):
        row = self.connection.execute('SELECT day FROM meal_entries WHERE id=?', (ident,)).fetchone()
        if row:
            with self.connection:
                self.connection.execute('DELETE FROM meal_entries WHERE id=?', (ident,))
                self.connection.execute('UPDATE nutrition_days SET complete=0 WHERE day=?', (row[0],))

    def day_nutrition(self, day):
        row = self.connection.execute('SELECT * FROM nutrition_days WHERE day=?', (day,)).fetchone()
        record = self.record(day)
        if row:
            state = dict(row)
        else:
            estimate = estimate_target(self.nutrition_profile())
            # Old days have no invented historical target.
            state = dict(day=day,target=estimate['target'] if day>=date.today().isoformat() else None,
                         target_reason=estimate['reason'],source='manual' if record and record['calories'] is not None else 'details',complete=0)
        entries = self.entries(day)
        if state['source'] == 'manual':
            totals = dict(kcal=record['calories'] if record else None,protein=None,fat=None,carbs=None)
        else:
            totals = nutrients_sum([item for entry in entries for item in entry['items']])
        return {**state, **totals, 'entry_count':len(entries),
                'remaining': state['target']-totals['kcal'] if state['target'] is not None and totals['kcal'] is not None else None}

    def nutrition_stats(self, days, end=None):
        end = end or date.today()
        states = [self.day_nutrition((end-timedelta(days=i)).isoformat()) for i in range(days)]
        logged = [s for s in states if s['kcal'] is not None]
        completed = [s for s in logged if s['complete']]
        return {'days':days,'logged':len(logged),'complete':len(completed),
                'average':round(sum(s['kcal'] for s in completed)/len(completed)) if completed else None,
                'within':sum(s['target'] is not None and abs(s['kcal']-s['target'])<=s['target']*.1 for s in completed)}

    def export_meals_csv(self, destination):
        with open(destination,'w',encoding='utf-8-sig',newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['日期','餐次','餐食','食物','克数或毫升','单位','份量选择','估算热量（千卡）','蛋白质（克）','脂肪（克）','碳水（克）','来源'])
            for row in self.connection.execute('SELECT * FROM meal_entries ORDER BY day,id'):
                for item in json.loads(row['items']):
                    values=[row['day'],MEALS[row['meal']],row['title'],item['name'],item['grams'],item.get('unit','g'),item.get('portion',''),
                            *[item['nutrients'].get(k) for k in KEYS],item['source']]
                    writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in values])
