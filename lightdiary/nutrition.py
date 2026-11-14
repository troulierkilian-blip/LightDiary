"""Offline nutrition calculations. Values are estimates, not clinical prescriptions."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

KEYS = ('kcal', 'protein', 'fat', 'carbs')
MEALS = {'breakfast': '早餐', 'lunch': '午餐', 'dinner': '晚餐', 'snack': '加餐 / 饮料'}
ACTIVITIES = {'sedentary': 1.2, 'light': 1.375, 'moderate': 1.55, 'active': 1.725}
PROFILE_DEFAULT = dict(mode='auto', age=None, sex='male', height=None, weight=None,
                       activity='sedentary', restrictions='', special=False, manual=None)


def positive(value, label, maximum=10000, optional=False):
    if value is None or value == '':
        if optional:
            return None
        raise ValueError(f'请填写{label}。')
    if isinstance(value, bool):
        raise ValueError(f'{label}需要填写数字。')
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}需要填写数字。') from None
    if not math.isfinite(parsed) or not 0 < parsed <= maximum:
        raise ValueError(f'{label}应大于 0 且不超过 {maximum:g}。')
    return parsed


def validate_profile(value):
    profile = {**PROFILE_DEFAULT, **value}
    if profile['mode'] not in ('auto', 'manual') or profile['sex'] not in ('male', 'female') or profile['activity'] not in ACTIVITIES:
        raise ValueError('请选择有效的目标方式、计算所需性别与活动量。')
    for key, name, maximum in [('age', '年龄', 120), ('height', '身高（厘米）', 250), ('weight', '体重（公斤）', 500), ('manual', '每日热量目标', 10000)]:
        profile[key] = positive(profile[key], name, maximum, optional=True)
    if profile['age'] is not None and not profile['age'].is_integer():
        raise ValueError('年龄请填写整数。')
    if profile['mode'] == 'manual' and profile['manual'] is None:
        raise ValueError('请填写手动每日热量目标。')
    profile['restrictions'] = str(profile['restrictions']).strip()[:500]
    profile['special'] = bool(profile['special'])
    return profile


def estimate_target(profile):
    p = validate_profile(profile)
    if p['mode'] == 'manual':
        return {'target': round(p['manual']), 'maintenance': None, 'reason': '用户手动目标'}
    if any(p[k] is None for k in ('age', 'height', 'weight')):
        return {'target': None, 'maintenance': None, 'reason': '在饮食设置中补充年龄、身高和当前体重，或填写手动目标。'}
    bmi = p['weight'] / (p['height'] / 100) ** 2
    if p['age'] < 18 or p['special'] or bmi < 18.5:
        return {'target': None, 'maintenance': None, 'reason': '当前资料不适合自动减脂目标。可以继续记录，或使用专业人员提供的手动目标。'}
    resting = 10 * p['weight'] + 6.25 * p['height'] - 5 * p['age'] + (5 if p['sex'] == 'male' else -161)
    if resting <= 0:
        return {'target': None, 'maintenance': None, 'reason': '请检查身高、体重和年龄。'}
    maintenance = resting * ACTIVITIES[p['activity']]
    floor = 1500 if p['sex'] == 'male' else 1200
    return {'target': int(round(max(maintenance * .85, floor) / 10) * 10),
            'maintenance': round(maintenance), 'reason': 'Mifflin–St Jeor 估算 × 活动系数；85% 与下限为软件默认规则，仅供参考。'}


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'data' / 'catalog.json').read_text(encoding='utf-8'))


def nutrients_sum(items):
    return {key: (round(sum(item['nutrients'][key] for item in items), 2)
                  if items and all(item['nutrients'].get(key) is not None for item in items) else None)
            for key in KEYS}


def food_item(food, quantity, portion=None):
    quantity = positive(quantity, '份量', 10000)
    grams = quantity * portion['grams'] if portion else quantity
    if grams > 10000:
        raise ValueError('单项食物份量不能超过 10000 克 / 毫升。')
    return {'food_id': str(food['id']), 'name': food['name'], 'grams': round(grams, 2),
            'unit': food.get('unit', 'g'), 'portion': (f"{quantity:g} × {portion['label']}" if portion else '按克数 / 毫升'),
            'source': food['source'], 'nutrients': {key: (None if food['nutrients'].get(key) is None else round(food['nutrients'][key] * grams / 100, 3)) for key in KEYS}}


def restrictions(text):
    for sep in ('，', '；', ';', '\n', '、'):
        text = text.replace(sep, ',')
    return [x.strip().casefold() for x in text.split(',') if x.strip()]


def make_plan(day, meal, target, excluded='', skip=None):
    if meal not in ('breakfast', 'lunch', 'dinner'):
        raise ValueError('请选择早餐、午餐或晚餐。')
    foods = {f['id']: f for f in catalog()['foods']}
    blocked = restrictions(excluded)
    choices = []
    for template in catalog()['templates']:
        if meal not in template['meals'] or template['id'] == skip:
            continue
        haystack = ' '.join([template['name']] + [foods[i['food']]['name'] + ' ' + ' '.join(foods[i['food']].get('tags', [])) for i in template['items']]).casefold()
        if any(token in haystack for token in blocked):
            continue
        choices.append(template)
    if not choices:
        raise ValueError('没有符合当前忌口的餐食组合。请调整限制或自行添加合适的食物；软件不会忽略忌口。')
    fraction = {'breakfast': .3, 'lunch': .4, 'dinner': .3}[meal]
    budget = target * fraction
    evaluated = []
    for template in choices:
        base = sum(foods[i['food']]['nutrients']['kcal'] * i['grams'] / 100 for i in template['items'])
        scale = max(.65, min(1.8, budget / base))
        items = [food_item(foods[i['food']], max(5, round(i['grams'] * scale / 5) * 5)) for i in template['items']]
        total = nutrients_sum(items)
        categories = {foods[i['food']]['category'] for i in template['items']}
        penalty = (0 if 'staple' in categories else .2) + (0 if 'protein' in categories or 'dairy' in categories else .2)
        if meal != 'breakfast' and 'vegetable' not in categories:
            penalty += .3
        evaluated.append((abs(total['kcal'] - budget) / budget + penalty, template, items, total))
    evaluated.sort(key=lambda x: (x[0], x[1]['id']))
    best_score = evaluated[0][0]
    pool = [x for x in evaluated if x[0] <= best_score + .08]
    ordinal = sum(int(x) for x in day.split('-')) + {'breakfast': 0, 'lunch': 3, 'dinner': 7}[meal]
    _, template, items, total = pool[ordinal % len(pool)]
    return {'day': day, 'meal': meal, 'template_id': template['id'], 'name': template['name'],
            'notes': template['notes'], 'items': items, 'nutrients': total, 'target': target,
            'budget': round(budget), 'estimated': True}


def fmt(value, suffix=''):
    return '未知' if value is None else f'{value:.0f}{suffix}'
