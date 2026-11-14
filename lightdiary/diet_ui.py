"""Native offline meal planning, portion recording and label entry."""
from __future__ import annotations
import copy
import sqlite3
from datetime import date, timedelta
from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QComboBox,
    QLineEdit,QCheckBox,QDateEdit,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,
    QMessageBox,QDialogButtonBox,QInputDialog,QScrollArea,QCompleter)
from .widgets import Card,label,button
from .nutrition import (MEALS,KEYS,PROFILE_DEFAULT,food_item,nutrients_sum,positive,estimate_target,fmt)


def summary_text(state):
    target = '尚未设置' if state['target'] is None else fmt(state['target'],' 千卡')
    energy = '尚未记录' if state['kcal'] is None else fmt(state['kcal'],' 千卡')
    if state['remaining'] is None:
        balance = '记录后可查看与目标的差距'
    elif state['remaining'] >= 0:
        balance = '与目标还差 ' + fmt(state['remaining'],' 千卡')
    else:
        balance = '已超过参考目标 ' + fmt(-state['remaining'],' 千卡') + '，下一餐照常规律进食'
    status = '全天记录完成' if state['complete'] else '记录未完成，数值只代表已记内容'
    macros = '  ·  '.join(name+' '+fmt(state[key],' g') for key,name in [('protein','蛋白质'),('fat','脂肪'),('carbs','碳水')])
    return f'目标 {target}    ·    已记录 {energy}\n{macros}\n{status}  ·  {balance}'


class NutritionProfile(QWidget):
    saved = Signal()
    def __init__(self,store):
        super().__init__()
        self.store=store
        root=QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        self.mode=QComboBox()
        self.mode.addItem('软件参考估算','auto')
        self.mode.addItem('我填写每日目标','manual')
        root.addWidget(self.mode)
        grid=QGridLayout()
        self.fields={}
        for index,(key,title,placeholder) in enumerate([
            ('age','年龄（岁）','例如 30'),('height','身高（厘米）','例如 170'),('weight','当前体重（公斤）','例如 75'),('manual','手动热量目标（千卡）','选填，例如 1800')]):
            edit=QLineEdit()
            edit.setPlaceholderText(placeholder)
            self.fields[key]=edit
            grid.addWidget(label(title,'muted'),index//2*2,index%2)
            grid.addWidget(edit,index//2*2+1,index%2)
        root.addLayout(grid)
        row=QHBoxLayout()
        self.sex=QComboBox()
        self.sex.addItem('公式按男性计算','male')
        self.sex.addItem('公式按女性计算','female')
        self.activity=QComboBox()
        for title,key in [('久坐为主','sedentary'),('轻度活动','light'),('中等活动','moderate'),('较多活动','active')]:
            self.activity.addItem(title,key)
        row.addWidget(self.sex)
        row.addWidget(self.activity)
        row.addWidget(button('使用最近体重',self.latest,'secondary'))
        root.addLayout(row)
        self.special=QCheckBox('孕哺期或需要治疗饮食：关闭自动减脂目标')
        root.addWidget(self.special)
        self.excluded=QLineEdit()
        self.excluded.setPlaceholderText('例如：海鲜, 花生, 奶；用逗号分隔')
        root.addWidget(label('忌口 · 按食物名称与食材标签筛选','muted'))
        root.addWidget(self.excluded)
        root.addWidget(label('推荐只能筛选模型中的已知食材。食堂或外卖存在隐藏食材，过敏时请向商家确认。','caption',True))
        self.status=label('','muted',True)
        root.addWidget(self.status)
        root.addWidget(button('保存饮食设置 / 重新估算',self.save))
        references=label('参考：<a href="https://pubmed.ncbi.nlm.nih.gov/2305711/">能量估算公式</a> · <a href="https://dg.cnsoc.org/">膳食指南</a> · <a href="https://fdc.nal.usda.gov/">食物数据</a>','caption',True)
        references.setOpenExternalLinks(True)
        root.addWidget(references)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.load()

    def mode_changed(self):
        self.fields['manual'].setEnabled(self.mode.currentData()=='manual')

    def latest(self):
        weights=[r for r in self.store.records() if r['weight_kg'] is not None]
        value=weights[-1]['weight_kg'] if weights else self.store.settings().get('start_weight')
        if value:
            self.fields['weight'].setText(f'{value:g}')

    def load(self):
        value=self.store.nutrition_profile()
        for key,edit in self.fields.items():
            edit.setText('' if value[key] is None else f'{value[key]:g}')
        for box,key in [(self.mode,'mode'),(self.sex,'sex'),(self.activity,'activity')]:
            box.setCurrentIndex(box.findData(value[key]))
        self.special.setChecked(value['special'])
        self.excluded.setText(value['restrictions'])
        self.mode_changed()
        result=estimate_target(value)
        self.status.setText(('每日参考目标 '+fmt(result['target'],' 千卡')+'。' if result['target'] is not None else '')+result['reason'])

    def save(self):
        try:
            value=self.value()
            result=self.store.save_nutrition_profile(value)
            self.status.setText(('已保存。参考目标 '+fmt(result['target'],' 千卡')+'。' if result['target'] is not None else '已保存。')+result['reason']+' 历史目标保持不变。')
            self.saved.emit()
        except (ValueError,sqlite3.Error) as error:
            self.status.setText(str(error))

    def value(self):
        value={key:edit.text().strip() for key,edit in self.fields.items()}
        value.update(mode=self.mode.currentData(),sex=self.sex.currentData(),activity=self.activity.currentData(),
                     restrictions=self.excluded.text(),special=self.special.isChecked())
        return value


class LabelDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store
        self.food=None
        self.setWindowTitle('添加营养标签 / 自定义食物')
        self.setMinimumWidth(460)
        root=QVBoxLayout(self)
        self.name=QLineEdit()
        self.name.setPlaceholderText('食品或常吃餐食名称')
        root.addWidget(self.name)
        row=QHBoxLayout()
        self.basis=QLineEdit('100')
        self.unit=QComboBox()
        self.unit.addItem('克','g')
        self.unit.addItem('毫升','ml')
        row.addWidget(label('以下数值对应'))
        row.addWidget(self.basis)
        row.addWidget(self.unit)
        root.addLayout(row)
        self.energy_unit=QComboBox()
        self.energy_unit.addItem('热量单位：千卡 kcal','kcal')
        self.energy_unit.addItem('热量单位：千焦 kJ','kj')
        root.addWidget(self.energy_unit)
        self.values={}
        for key,title in [('kcal','热量（必填）'),('protein','蛋白质（克）'),('fat','脂肪（克）'),('carbs','碳水化合物（克）')]:
            edit=QLineEdit()
            edit.setPlaceholderText('未提供可留空，显示未知' if key!='kcal' else '标签上的数值')
            self.values[key]=edit
            row=QHBoxLayout()
            row.addWidget(label(title))
            row.addWidget(edit)
            root.addLayout(row)
        self.status=label('','muted',True)
        root.addWidget(self.status)
        actions=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        actions.accepted.connect(self.save)
        actions.rejected.connect(self.reject)
        root.addWidget(actions)

    def save(self):
        try:
            values={key:edit.text().strip() for key,edit in self.values.items()}
            if self.energy_unit.currentData()=='kj':
                values['kcal']=positive(values['kcal'],'热量（千焦）',100000)/4.184
            self.food=self.store.save_custom_food(self.name.text(),values,self.basis.text(),self.unit.currentData())
            self.accept()
        except (ValueError,sqlite3.Error) as error:
            self.status.setText(str(error))


class MealEditor(QDialog):
    def __init__(self,store,day,entry=None,parent=None):
        super().__init__(parent)
        self.store,self.day,self.entry=store,day,entry
        self.rows=[]
        self.setWindowTitle('编辑实际餐食' if entry else '记录实际吃下的食物')
        self.resize(800,620)
        root=QVBoxLayout(self)
        self.title=QLineEdit(entry['title'] if entry else '')
        self.title.setPlaceholderText('餐食名称，可留空按食物命名')
        self.meal=QComboBox()
        for key,name in MEALS.items(): self.meal.addItem(name,key)
        if entry: self.meal.setCurrentIndex(self.meal.findData(entry['meal']))
        row=QHBoxLayout()
        row.addWidget(self.meal)
        row.addWidget(self.title,1)
        root.addLayout(row)
        self.food=QComboBox()
        self.food.setEditable(True)
        self.food.setInsertPolicy(QComboBox.NoInsert)
        self.portion=QComboBox()
        self.quantity=QLineEdit('1')
        self.quantity.setMaximumWidth(80)
        self.quantity.setPlaceholderText('数量')
        row=QHBoxLayout()
        row.addWidget(self.food,3)
        row.addWidget(self.portion,1)
        row.addWidget(self.quantity)
        row.addWidget(button('添加',self.add_food))
        root.addLayout(row)
        self.source=label('','caption',True)
        root.addWidget(self.source)
        row=QHBoxLayout()
        row.addWidget(button('添加营养标签 / 新食物',self.custom_food,'secondary'))
        row.addWidget(button('存为常吃餐食',self.favorite,'secondary'))
        row.addWidget(button('移除所选食物',self.remove,'danger'))
        root.addLayout(row)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['食物','克数 / 毫升','估算千卡','数据来源'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for col in range(4):
            self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.Stretch if col in (0,3) else QHeaderView.ResizeToContents)
        root.addWidget(self.table,1)
        self.status=label('按实际吃下的份量修改；食堂和外卖的食材、油量可能与模型不同。','muted',True)
        root.addWidget(self.status)
        self.total=label('','section',True)
        root.addWidget(self.total)
        row=QHBoxLayout()
        row.addStretch()
        row.addWidget(button('取消',self.reject,'secondary'))
        self.save_button=button('保存实际摄入',self.save)
        row.addWidget(self.save_button)
        root.addLayout(row)
        self.food.currentIndexChanged.connect(self.food_changed)
        self.portion.currentIndexChanged.connect(self.portion_changed)
        self.load_foods()
        if entry:
            for item in entry['items']: self.append_item(item)

    def load_foods(self,select=None):
        self.food.blockSignals(True)
        self.food.clear()
        self.foods=self.store.foods()
        for food in self.foods: self.food.addItem(food['name'],food['id'])
        completer=QCompleter([f['name'] for f in self.foods],self.food)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.food.setCompleter(completer)
        if select: self.food.setCurrentIndex(self.food.findData(select))
        self.food.blockSignals(False)
        self.food_changed()

    def food_changed(self):
        food=self.foods[max(0,self.food.currentIndex())]
        self.portion.blockSignals(True)
        self.portion.clear()
        for portion in food['portions']:
            self.portion.addItem(f"{portion['label']} ≈ {portion['grams']:g} {food['unit']}",portion)
        self.portion.addItem('直接输入克数 / 毫升',None)
        self.portion.blockSignals(False)
        self.quantity.setText('1')
        self.source.setText(food['source']+'；'+str(food.get('description','估算 / 用户录入')))

    def portion_changed(self):
        self.quantity.setText('100' if self.portion.currentData() is None else '1')

    def add_food(self):
        try:
            # Editable search must resolve an actual catalog name.
            selected=next((f for f in self.foods if f['name']==self.food.currentText()),None)
            if not selected: raise ValueError('请从搜索结果中选择一种食物。')
            self.append_item(food_item(selected,self.quantity.text(),self.portion.currentData()))
        except ValueError as error: self.status.setText(str(error))

    def append_item(self,item):
        base=copy.deepcopy(item)
        row=self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row,0,QTableWidgetItem(base['name']))
        grams=QLineEdit(f"{base['grams']:g}")
        grams.setToolTip('实际吃下的克数或毫升；修改后按原快照比例换算')
        self.table.setCellWidget(row,1,grams)
        self.table.setItem(row,2,QTableWidgetItem(fmt(base['nutrients']['kcal'])))
        source=QTableWidgetItem('USDA / 食材估算' if 'USDA' in base['source'] else '用户录入 / 估算')
        source.setToolTip(base['source'])
        self.table.setItem(row,3,source)
        self.table.setRowHeight(row,42)
        self.rows.append((base,grams))
        grams.textChanged.connect(self.update_total)
        self.update_total()

    def items(self):
        result=[]
        for base,edit in self.rows:
            grams=positive(edit.text(),'食物份量',10000)
            scale=grams/base['grams']
            result.append({**base,'grams':grams,'portion':base.get('portion','') if grams==base['grams'] else '调整克数 / 毫升',
                           'nutrients':{key:None if base['nutrients'].get(key) is None else base['nutrients'][key]*scale for key in KEYS}})
        return result

    def update_total(self):
        try:
            items=self.items()
            totals=nutrients_sum(items)
            self.total.setText('本次 '+fmt(totals['kcal'],' 千卡')+'   ·   蛋白质 '+fmt(totals['protein'],' g')+'   ·   脂肪 '+fmt(totals['fat'],' g')+'   ·   碳水 '+fmt(totals['carbs'],' g'))
            for row,item in enumerate(items): self.table.item(row,2).setText(fmt(item['nutrients']['kcal']))
        except ValueError as error: self.total.setText(str(error))

    def remove(self):
        row=self.table.currentRow()
        if row>=0:
            self.table.removeRow(row)
            self.rows.pop(row)
            self.update_total()

    def custom_food(self):
        dialog=LabelDialog(self.store,self)
        if dialog.exec()==QDialog.Accepted: self.load_foods(dialog.food['id'])

    def favorite(self):
        try:
            items=self.items()
            if not items: raise ValueError('先添加食物，再保存常吃餐食。')
            name,ok=QInputDialog.getText(self,'常吃餐食','餐食名称：',text=self.title.text())
            if ok:
                food=self.store.save_custom_food(name,nutrients_sum(items),sum(i['grams'] for i in items),source='用户保存的常吃餐食；来源为食物快照营养之和，非餐厅实测')
                self.load_foods(food['id'])
                self.status.setText('已保存到食物库，下次可直接搜索。')
        except (ValueError,sqlite3.Error) as error: self.status.setText(str(error))

    def save(self):
        try:
            items=self.items()
            title=self.title.text().strip() or '、'.join(i['name'] for i in items)[:200]
            self.store.save_entry(self.day,self.meal.currentData(),title,items,self.entry['id'] if self.entry else None)
            self.accept()
        except (ValueError,sqlite3.Error) as error: self.status.setText(str(error))


class DietPage(QWidget):
    changed=Signal()
    manual_saved=Signal(str,int)
    def __init__(self,store):
        super().__init__()
        self.store=store
        root=QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        row=QHBoxLayout()
        self.date=QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setMaximumDate(QDate.currentDate().addDays(6))
        row.addWidget(label('查看日期','muted'))
        row.addWidget(self.date)
        row.addWidget(button('回到今天',lambda:self.date.setDate(QDate.currentDate()),'secondary'))
        row.addWidget(button('未来七天安排',self.week,'secondary'))
        row.addStretch()
        root.addLayout(row)
        summary=Card('这一天的实际摄入')
        self.summary=label('','muted',True)
        summary.body.addWidget(self.summary)
        row=QHBoxLayout()
        self.source=QComboBox()
        self.source.addItem('使用餐食明细计算','details')
        self.source.addItem('使用手动全天总量','manual')
        row.addWidget(self.source)
        self.manual=button('填写全天热量',self.manual_total,'secondary')
        row.addWidget(self.manual)
        self.complete=QCheckBox('全天已记录完成')
        row.addWidget(self.complete)
        row.addStretch()
        summary.body.addLayout(row)
        root.addWidget(summary)
        self.plan_cards={}
        plans=QHBoxLayout()
        for meal in ('breakfast','lunch','dinner'):
            card=Card(MEALS[meal]+' · 建议')
            text=label('','muted',True)
            card.body.addWidget(text)
            card.body.addStretch()
            swap=button('换一餐',lambda checked=False,m=meal:self.swap(m),'secondary')
            record=button('按这餐记录',lambda checked=False,m=meal:self.record_plan(m))
            card.body.addWidget(swap)
            card.body.addWidget(record)
            self.plan_cards[meal]=(text,swap,record)
            plans.addWidget(card,1)
        root.addLayout(plans)
        root.addWidget(label('计划不计入摄入。食材、熟重和油量为模型估算；没有目标时仍可自行添加食物。','caption',True))
        actual=Card('已经吃下的餐食')
        row=QHBoxLayout()
        self.add=button('＋ 食物 / 加餐 / 饮料',self.add_entry)
        self.edit=button('编辑所选',self.edit_entry,'secondary')
        self.delete=button('删除所选',self.delete_entry,'danger')
        for action in (self.add,self.edit,self.delete): row.addWidget(action)
        row.addStretch()
        actual.body.addLayout(row)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['餐次','餐食与份量','估算千卡','蛋白质（克）'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(180)
        for col in range(4): self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.Stretch if col==1 else QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda r,c:self.edit_entry())
        actual.body.addWidget(self.table)
        root.addWidget(actual)
        self.date.dateChanged.connect(lambda:self.refresh())
        self.source.currentIndexChanged.connect(self.source_changed)
        self.complete.toggled.connect(self.completed)
        self.refresh()

    def day(self): return self.date.date().toString('yyyy-MM-dd')

    def error(self,error): QMessageBox.warning(self,'请检查饮食记录',str(error))

    def refresh(self):
        day=self.day()
        future=day>date.today().isoformat()
        state=self.store.ensure_nutrition_day(day)
        totals=self.store.day_nutrition(day)
        self.summary.setText(summary_text(totals))
        for box in (self.source,self.complete): box.blockSignals(True)
        self.source.setCurrentIndex(self.source.findData(state['source']))
        self.complete.setChecked(bool(state['complete']))
        for box in (self.source,self.complete): box.blockSignals(False)
        for widget in (self.source,self.manual,self.complete,self.add,self.edit,self.delete): widget.setEnabled(not future)
        for meal,(text,swap,record) in self.plan_cards.items():
            try:
                plan=self.store.plan(day,meal)
                lines=[plan['name'],fmt(plan['nutrients']['kcal'],' 千卡（估算）')]+[f"{i['name']} {i['grams']:g}{i.get('unit','g')}" for i in plan['items']]
                lines += [plan['notes']]
                text.setText('\n'.join(lines))
                text.setToolTip('\n'.join(i['source'] for i in plan['items']))
                swap.setEnabled(day>=date.today().isoformat())
                record.setEnabled(not future)
                exists=any(e.get('plan_key')==day+':'+meal for e in self.store.entries(day))
                record.setText('已记录 · 编辑' if exists else '按这餐记录')
            except ValueError as error:
                text.setText(str(error))
                swap.setEnabled(False)
                record.setEnabled(False)
        self.current_entries=self.store.entries(day)
        self.table.setRowCount(len(self.current_entries))
        for row,entry in enumerate(self.current_entries):
            nutrients=nutrients_sum(entry['items'])
            names='；'.join(f"{i['name']} {i['grams']:g}{i.get('unit','g')}" for i in entry['items'])
            values=[MEALS[entry['meal']],entry['title']+' · '+names,fmt(nutrients['kcal']),fmt(nutrients['protein'])]
            for col,value in enumerate(values):
                item=QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row,col,item)
            self.table.setRowHeight(row,45)

    def swap(self,meal):
        try:
            self.store.plan(self.day(),meal,replace=True)
            self.refresh()
        except (ValueError,sqlite3.Error) as error: self.error(error)

    def record_plan(self,meal):
        try:
            before=self.store.entries(self.day())
            ident=self.store.record_plan(self.day(),meal)
            existing=next((e for e in before if e['id']==ident),None)
            if existing:
                self.open_editor(existing)
            else:
                self.changed.emit()
        except (ValueError,sqlite3.Error) as error: self.error(error)

    def open_editor(self,entry=None):
        dialog=MealEditor(self.store,self.day(),entry,self)
        if dialog.exec()==QDialog.Accepted: self.changed.emit()
        # Custom foods can be saved even when the meal dialog is cancelled.
        self.refresh()

    def add_entry(self): self.open_editor()

    def edit_entry(self):
        row=self.table.currentRow()
        if row>=0: self.open_editor(self.current_entries[row])

    def delete_entry(self):
        row=self.table.currentRow()
        if row>=0 and QMessageBox.question(self,'删除餐食','删除选中的实际摄入记录？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.store.delete_entry(self.current_entries[row]['id'])
            self.changed.emit()

    def source_changed(self):
        try:
            self.store.set_nutrition_day(self.day(),source=self.source.currentData())
            self.changed.emit()
        except (ValueError,sqlite3.Error) as error: self.error(error)

    def completed(self,value):
        try:
            self.store.set_nutrition_day(self.day(),complete=value)
            self.changed.emit()
        except (ValueError,sqlite3.Error) as error:
            self.error(error)
            self.refresh()

    def manual_total(self):
        old=self.store.record(self.day()) or {'day':self.day()}
        value,ok=QInputDialog.getInt(self,'手动全天热量','填写全天实际摄入（千卡）。不会与餐食明细相加：',old.get('calories') or 0,0,30000)
        if ok:
            try:
                self.store.save_record({**old,'calories':value})
                self.store.set_nutrition_day(self.day(),source='manual')
                self.manual_saved.emit(self.day(),value)
                self.changed.emit()
            except (ValueError,sqlite3.Error) as error: self.error(error)

    def week(self):
        dialog=QDialog(self)
        dialog.setWindowTitle('未来七天 · 食堂与外卖建议')
        dialog.resize(820,640)
        root=QVBoxLayout(dialog)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        contents=QWidget()
        layout=QVBoxLayout(contents)
        for offset in range(7):
            day=(date.today()+timedelta(days=offset)).isoformat()
            card=Card(day)
            for meal in ('breakfast','lunch','dinner'):
                try:
                    plan=self.store.plan(day,meal)
                    foods='；'.join(f"{i['name']} {i['grams']:g}{i.get('unit','g')}" for i in plan['items'])
                    card.body.addWidget(label(MEALS[meal]+'：'+plan['name']+' · '+fmt(plan['nutrients']['kcal'],' 千卡（估算）')+'\n'+foods,'muted',True))
                except ValueError as error: card.body.addWidget(label(str(error),'muted',True))
            layout.addWidget(card)
        scroll.setWidget(contents)
        root.addWidget(scroll)
        root.addWidget(button('关闭',dialog.accept))
        dialog.exec()
