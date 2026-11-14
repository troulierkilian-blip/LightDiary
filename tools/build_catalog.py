"""Reproducibly extract CC0 USDA SR Legacy data and build Chinese meal estimates."""
import csv
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.qa' / 'food-source'
URL = 'https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip'
if not (CACHE / 'food_nutrient.csv').exists():
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL, timeout=60).read()))
    for name in archive.namelist():
        if Path(name).name in ('food.csv', 'food_nutrient.csv'):
            (CACHE / Path(name).name).write_bytes(archive.read(name))
source = list(csv.DictReader((CACHE / 'food.csv').open(encoding='utf8')))

# id, Chinese label, regex for original USDA description, category, tags, default portion
SPEC = [
 ('rice','米饭（熟）',r'^Rice, white, long-grain, regular, enriched, cooked$','staple',[],('一碗',150)),
 ('brownrice','糙米饭（熟）',r'^Rice, brown, long-grain, cooked','staple',[],('一碗',150)),
 ('oats','燕麦片（干重）',r'^Oats \(','staple',[],('一份',40)),
 ('bread','全麦面包',r'^Bread, whole-wheat, commercially prepared$','staple',['小麦','麸质'],('一片',30)),
 ('noodles','小麦面条（熟；按意面近似）',r'^Pasta, cooked, enriched, without added salt$','staple',['小麦','麸质'],('一碗',180)),
 ('corn','甜玉米粒（熟）',r'^Corn, sweet, yellow, cooked, boiled, drained, without salt$','staple',[],('一份',150)),
 ('potato','土豆（熟）',r'^Potatoes, boiled, cooked without skin, flesh, without salt$','staple',[],('一份',150)),
 ('sweetpotato','红薯（熟）',r'^Sweet potato, cooked, boiled, without skin$','staple',[],('一个',150)),
 ('quinoa','藜麦（熟）',r'^Quinoa, cooked$','staple',[],('一碗',150)),
 ('flour','小麦面粉（干重）',r'^Wheat flour, white, all-purpose, enriched, bleached$','staple',['小麦','麸质'],('一份',50)),
 ('riceflour','米粉（干粉）',r'^Rice flour, white, unenriched$','staple',[],('一份',50)),
 ('millet','小米（熟）',r'^Millet, cooked$','staple',[],('一碗',150)),
 ('egg','鸡蛋（水煮，去壳）',r'^Egg, whole, cooked, hard-boiled$','protein',['鸡蛋','蛋'],('一个',50)),
 ('chicken','鸡胸肉（熟，去皮）',r'^Chicken, broilers or fryers, breast, meat only, cooked, roasted$','protein',['鸡肉'],('一份',100)),
 ('pork','猪里脊（熟，瘦肉）',r'^Pork, fresh, loin, tenderloin, separable lean only, cooked, roasted$','protein',['猪肉'],('一份',100)),
 ('beef','牛肉（熟，瘦肉）',r'^Beef, round, full cut, separable lean only.*choice, cooked, broiled$','protein',['牛肉'],('一份',100)),
 ('cod','鱼肉（熟；鳕鱼参考）',r'^Fish, cod, Atlantic, cooked, dry heat$','protein',['鱼','海鲜'],('一份',100)),
 ('salmon','三文鱼（熟）',r'^Fish, salmon, Atlantic, farmed, cooked, dry heat$','protein',['鱼','海鲜'],('一份',100)),
 ('shrimp','虾（熟，去壳）',r'^Crustaceans, shrimp, mixed species, cooked, moist heat','protein',['虾','海鲜','甲壳类'],('一份',100)),
 ('tofu','豆腐（参考钙凝固普通豆腐）',r'^Tofu, raw, regular, prepared with calcium sulfate$','protein',['豆','大豆'],('一份',150)),
 ('edamame','毛豆仁（熟）',r'^Edamame, frozen, prepared$','protein',['豆','大豆'],('一份',100)),
 ('lentil','扁豆（熟）',r'^Lentils, mature seeds, cooked, boiled, without salt$','protein',['豆'],('一份',100)),
 ('chickpea','鹰嘴豆（熟）',r'^Chickpeas \(garbanzo beans, bengal gram\), mature seeds, cooked, boiled, without salt$','protein',['豆'],('一份',100)),
 ('broccoli','西兰花（熟）',r'^Broccoli, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('cabbage','大白菜（熟）',r'^Cabbage, chinese \(pe-tsai\), cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('bokchoy','小白菜（熟）',r'^Cabbage, chinese \(pak-choi\), cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('spinach','菠菜（熟）',r'^Spinach, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('carrot','胡萝卜（熟）',r'^Carrots, cooked, boiled, drained, without salt$','vegetable',[],('一份',100)),
 ('tomato','番茄（生）',r'^Tomatoes, red, ripe, raw, year round average$','vegetable',[],('一个',150)),
 ('cucumber','黄瓜（生）',r'^Cucumber, with peel, raw$','vegetable',[],('一份',150)),
 ('lettuce','生菜（生）',r'^Lettuce, green leaf, raw$','vegetable',[],('一份',100)),
 ('mushroom','香菇（熟）',r'^Mushrooms, shiitake, cooked, without salt$','vegetable',[],('一份',100)),
 ('cauliflower','菜花（熟）',r'^Cauliflower, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('greenbean','四季豆（熟）',r'^Beans, snap, green, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('eggplant','茄子（熟，未计油）',r'^Eggplant, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('pumpkin','南瓜（熟）',r'^Pumpkin, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('zucchini','西葫芦（熟）',r'^Squash, summer, zucchini, includes skin, cooked, boiled, drained, without salt$','vegetable',[],('一份',150)),
 ('pepper','青椒（生）',r'^Peppers, sweet, green, raw$','vegetable',[],('一份',100)),
 ('celery','芹菜（生）',r'^Celery, raw$','vegetable',[],('一份',100)),
 ('onion','洋葱（生）',r'^Onions, raw$','vegetable',[],('一份',100)),
 ('asparagus','芦笋（熟）',r'^Asparagus, cooked, boiled, drained$','vegetable',[],('一份',100)),
 ('apple','苹果（带皮）',r'^Apples, raw, with skin','fruit',[],('一个',180)),
 ('banana','香蕉（去皮）',r'^Bananas, raw$','fruit',[],('一根',100)),
 ('orange','橙子（去皮）',r'^Oranges, raw, all commercial varieties$','fruit',[],('一个',130)),
 ('pear','梨（带皮）',r'^Pears, raw$','fruit',[],('一个',180)),
 ('kiwi','猕猴桃（绿肉，去皮）',r'^Kiwifruit, green, raw$','fruit',[],('一个',80)),
 ('grape','葡萄',r'^Grapes, red or green \(European type, such as Thompson seedless\), raw$','fruit',[],('一份',100)),
 ('strawberry','草莓',r'^Strawberries, raw$','fruit',[],('一份',150)),
 ('watermelon','西瓜（去皮）',r'^Watermelon, raw$','fruit',[],('一份',200)),
 ('peach','桃（去核）',r'^Peaches, yellow, raw$','fruit',[],('一个',150)),
 ('blueberry','蓝莓',r'^Blueberries, raw$','fruit',[],('一份',100)),
 ('mango','芒果（去皮核）',r'^Mangos, raw$','fruit',[],('一份',100)),
 ('milk','低脂牛奶（2%脂肪）',r'^Milk, reduced fat, fluid, 2% milkfat, with added vitamin A and vitamin D$','dairy',['奶','乳'],('一杯',250)),
 ('skim','脱脂牛奶',r'^Milk, nonfat, fluid, with added vitamin A and vitamin D \(fat free or skim\)$','dairy',['奶','乳'],('一杯',250)),
 ('yogurt','原味低脂酸奶',r'^Yogurt, plain, low fat$','dairy',['奶','乳'],('一杯',150)),
 ('greek','原味脱脂希腊酸奶',r'^Yogurt, Greek, plain, nonfat','dairy',['奶','乳'],('一杯',150)),
 ('soymilk','无糖豆奶（参考值）',r'^Soymilk, original and vanilla, light, unsweetened, with added calcium, vitamins A and D$','protein',['豆','大豆'],('一杯',250)),
 ('almond','杏仁',r'^Nuts, almonds$','snack',['坚果','杏仁'],('一小把',15)),
 ('walnut','核桃仁',r'^Nuts, walnuts, english$','snack',['坚果','核桃'],('一小把',15)),
 ('peanut','花生（烤，无盐）',r'^Peanuts, all types, dry-roasted, without salt$','snack',['花生','坚果'],('一小把',15)),
 ('cashew','腰果（生）',r'^Nuts, cashew nuts, raw$','snack',['坚果','腰果'],('一小把',15)),
 ('oil','烹调油（大豆油参考）',r'^Oil, soybean, salad or cooking$','oil',['大豆油'],('一茶匙',5)),
 ('olive','橄榄油',r'^Oil, olive, salad or cooking$','oil',[],('一茶匙',5)),
 ('coffee','黑咖啡（不加糖奶）',r'^Beverages, coffee, brewed, prepared with tap water$','drink',[],('一杯',250)),
 ('tea','绿茶（不加糖）',r'^Beverages, tea, green, brewed, regular$','drink',[],('一杯',250)),
 ('cola','可乐（含糖）',r'^Beverages, carbonated, cola, regular$','drink',[],('一罐',330)),
 ('chocolate','黑巧克力（70–85%可可）',r'^Chocolate, dark, 70-85% cacao solids$','snack',[],('一小块',10)),
]
foods=[]
for ident, name, pattern, category, tags, portion in SPEC:
    matches=[x for x in source if re.search(pattern,x['description'],re.I)]
    if not matches:
        raise RuntimeError(f'No USDA match: {ident}: {pattern}')
    original=matches[0]
    foods.append(dict(id=ident,name=name,category=category,tags=tags,unit=('ml' if ident in ('milk','skim','soymilk','tea','coffee','cola') else 'g'),
                      portions=[dict(label=portion[0],grams=portion[1]),dict(label='半'+portion[0][1:],grams=portion[1]/2)],
                      fdc_id=original['fdc_id'],description=original['description'],source=f"USDA FoodData Central / SR Legacy / FDC {original['fdc_id']}；毫升按密度约 1 克/毫升估算" if ident in ('milk','skim','soymilk','tea','coffee','cola') else f"USDA FoodData Central / SR Legacy / FDC {original['fdc_id']}",nutrients={}))
selected={x['fdc_id']:x for x in foods}
nutrient_map={'1008':'kcal','1003':'protein','1004':'fat','1005':'carbs'}
for row in csv.DictReader((CACHE/'food_nutrient.csv').open(encoding='utf8')):
    if row['fdc_id'] in selected and row['nutrient_id'] in nutrient_map:
        selected[row['fdc_id']]['nutrients'][nutrient_map[row['nutrient_id']]]=float(row['amount'])
for food in foods:
    if set(food['nutrients'])!=set(nutrient_map.values()):
        raise RuntimeError(f'Incomplete nutrition: {food["id"]}')
by_id={f['id']:f for f in foods}
def composite(ident,name,components,portion,category,tags):
    foods.append(dict(id=ident,name=name,category=category,tags=tags,unit='g',portions=[dict(label=portion[0],grams=portion[1]),dict(label='半份',grams=portion[1]/2)],
                      source='食材模型估算；按 USDA SR Legacy 基础条目计算，非餐厅实测：'+', '.join(f'{key} {grams}g' for key,grams in components),
                      nutrients={key:round(sum(by_id[f]['nutrients'][key]*grams/100 for f,grams in components),3) for key in nutrient_map.values()}))
composite('bun','馒头（模型估算）',[('flour',60)],('一个',100),'staple',['小麦','麸质'])
composite('porridge','米粥（模型估算）',[('rice',35)],('一碗',250),'staple',[])
composite('dumpling','猪肉白菜水饺（模型估算）',[('flour',28),('pork',20),('cabbage',15),('oil',3)],('十个约',250),'staple',['小麦','麸质','猪肉'])
composite('rice_noodle','米粉（熟，模型估算）',[('riceflour',25)],('一碗',200),'staple',[])

templates=[]
def meal(name,items,breakfast=False,notes='主食和菜分开点；少油，酱汁另放。按实际份量修改记录，油量只是模型参考。'):
    templates.append(dict(id='meal-'+str(len(templates)+1),name=name,meals=['breakfast'] if breakfast else ['lunch','dinner'],items=[dict(food=f,grams=g) for f,g in items],notes=notes))
for name,items in [
 ('牛奶燕麦鸡蛋',[('oats',40),('milk',250),('egg',50),('apple',100)]),
 ('全麦面包鸡蛋套餐',[('bread',60),('egg',50),('milk',250),('tomato',100)]),
 ('豆奶馒头鸡蛋',[('soymilk',250),('bun',100),('egg',50),('cucumber',100)]),
 ('红薯酸奶早餐',[('sweetpotato',200),('yogurt',150),('egg',50),('kiwi',80)]),
 ('玉米牛奶早餐',[('corn',150),('milk',250),('egg',50),('banana',80)]),
 ('酸奶燕麦水果',[('greek',200),('oats',40),('banana',100),('walnut',15)]),
 ('小米鸡蛋早餐',[('millet',200),('egg',100),('skim',250),('orange',100)]),
 ('米粥馒头豆腐',[('porridge',250),('bun',80),('tofu',150),('cucumber',100)]),
 ('全麦豆奶坚果',[('bread',60),('soymilk',300),('almond',15),('apple',150)]),
 ('藜麦酸奶水果',[('quinoa',150),('yogurt',200),('strawberry',150),('cashew',15)]),
]: meal(name,items,True,'早餐保留主食与蛋白质食物；选择无糖饮品。食物克数与营养为参考估算。')
for name,protein in [('鸡胸','chicken'),('瘦猪肉','pork'),('牛肉','beef'),('蒸鱼','cod'),('虾仁','shrimp'),('三文鱼','salmon'),('豆腐','tofu')]:
    meal(name+'米饭蔬菜套餐',[('rice',180),(protein,150 if protein=='tofu' else 100),('broccoli',150),('bokchoy',150),('oil',10)])
for name,protein in [('鸡肉','chicken'),('牛肉','beef'),('豆腐','tofu')]:
    meal(name+'清汤面',[('noodles',230),(protein,150 if protein=='tofu' else 100),('bokchoy',150),('mushroom',80),('oil',5)],notes='清汤、少油；汤和酱汁不全部喝完。面条使用熟意面数据近似，餐馆实际值会变化。')
for name,items in [
 ('水饺蔬菜组合',[('dumpling',250),('cucumber',150),('bokchoy',150)]),
 ('鸡肉轻食碗',[('brownrice',180),('chicken',100),('lettuce',100),('tomato',150),('olive',10)]),
 ('三文鱼藜麦碗',[('quinoa',180),('salmon',100),('lettuce',100),('cucumber',100),('olive',5)]),
 ('豆腐毛豆轻食',[('brownrice',180),('tofu',150),('edamame',80),('broccoli',200),('oil',5)]),
 ('麻辣烫米粉豆腐虾',[('rice_noodle',220),('tofu',150),('shrimp',80),('bokchoy',200),('mushroom',80),('oil',10)]),
 ('麻辣烫面条鸡蛋',[('noodles',200),('egg',100),('tofu',100),('spinach',150),('cabbage',150),('oil',10)]),
 ('番茄鸡蛋饭',[('rice',180),('tomato',200),('egg',100),('broccoli',150),('oil',10)]),
 ('牛肉土豆套餐',[('potato',200),('beef',120),('carrot',100),('greenbean',150),('oil',10)]),
 ('豆腐茄子杂粮饭',[('brownrice',180),('tofu',200),('eggplant',150),('bokchoy',150),('oil',10)]),
 ('鸡肉玉米南瓜餐',[('corn',180),('chicken',120),('pumpkin',150),('broccoli',150),('oil',10)]),
 ('鹰嘴豆素食碗',[('quinoa',150),('chickpea',150),('tomato',150),('cucumber',150),('olive',10)]),
 ('鱼肉小米蔬菜餐',[('millet',180),('cod',130),('cauliflower',150),('spinach',150),('oil',10)]),
 ('虾仁西葫芦饭',[('rice',180),('shrimp',120),('zucchini',200),('carrot',100),('oil',10)]),
 ('瘦肉菜花饭',[('rice',180),('pork',100),('cauliflower',200),('cabbage',150),('oil',10)]),
 ('鸡肉红薯沙拉',[('sweetpotato',220),('chicken',120),('lettuce',100),('tomato',150),('olive',10)]),
 ('扁豆糙米套餐',[('brownrice',180),('lentil',150),('tofu',100),('bokchoy',200),('oil',10)]),
]: meal(name,items)
assert len(foods)>=60 and len(templates)>=30
output=ROOT/'lightdiary/data/catalog.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(dict(version=1,source_url=URL,license='USDA CC0 1.0',note='通用条目与份量模型估算，不代表具体品牌或餐厅实测；生熟状态见名称。',foods=foods,templates=templates),ensure_ascii=False,indent=2),encoding='utf8')
print(f'Built {len(foods)} foods and {len(templates)} templates: {output}')
