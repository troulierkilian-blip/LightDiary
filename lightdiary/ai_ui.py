"""Manual, reviewable AI requests; remote text is never interpreted as HTML."""
import sqlite3
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
                              QCheckBox, QPlainTextEdit, QComboBox, QDateEdit, QDialog,
                              QApplication, QFileDialog)
from .widgets import Card, label, button
from .ai import checked_config, endpoint_url, daily_context, encode, fingerprint, report_messages, followup_messages
from .secrets import KeyVault


def plain_label(text='', role='muted'):
    widget = label(text, role, True)
    widget.setTextFormat(Qt.PlainText)
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


class RequestPreview(QDialog):
    def __init__(self, config, messages, parent=None, scope_text=''):
        super().__init__(parent)
        self.setWindowTitle('发送前预览 · AI 分析')
        self.resize(760, 620)
        root = QVBoxLayout(self)
        root.addWidget(plain_label('即将发送给：' + config['endpoint'] + '\n模型：' + config['model'], 'section'))
        if scope_text:
            root.addWidget(plain_label(scope_text, 'caption'))
        root.addWidget(plain_label('下方是本次实际发送的全部消息。API Key 仅用于认证，不在消息中。服务商可能计费，请确认内容后发送。'))
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        roles = {'system': '软件分析规则', 'user': '本次记录或我的追问', 'assistant': '已有 AI 回答'}
        self.content.setPlainText('\n\n'.join('【' + roles.get(m['role'], m['role']) + '】\n' + m['content'] for m in messages))
        root.addWidget(self.content, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button('返回', self.reject, 'secondary'))
        row.addWidget(button('发送并等待分析', self.accept))
        root.addLayout(row)


class APISettings(QWidget):
    saved = Signal()

    def __init__(self, store, client, parent=None):
        super().__init__(parent)
        self.store, self.client = store, client
        self.vault = KeyVault(store.directory)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(plain_label('可选功能。只有主动分析、追问或测试连接时才联网。健康记录会发送给你配置的服务商；未配置时仍可离线记录。'))
        form = QFormLayout()
        self.base, self.model, self.key = QLineEdit(), QLineEdit(), QLineEdit()
        self.base.setPlaceholderText('服务商给出的 HTTPS Base URL，保留其 /v1 等路径')
        self.model.setPlaceholderText('服务商提供的模型名称')
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setMaxLength(4096)
        form.addRow('Base URL', self.base)
        form.addRow('模型名称', self.model)
        form.addRow('API Key', self.key)
        root.addLayout(form)
        self.show_key = QCheckBox('显示本次输入的密钥')
        self.show_key.toggled.connect(lambda checked: self.key.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        root.addWidget(self.show_key)
        self.endpoint = plain_label('', 'caption')
        root.addWidget(self.endpoint)
        self.base.textChanged.connect(self.update_endpoint)
        row = QHBoxLayout()
        self.save_button = button('保存 API 设置', self.save)
        self.test_button = button('保存并测试连接', self.test, 'secondary')
        self.clear_button = button('清除密钥', self.clear, 'secondary')
        self.cancel_button = button('取消请求', lambda: client.cancel(), 'secondary')
        for control in (self.save_button, self.test_button, self.clear_button, self.cancel_button):
            row.addWidget(control)
        root.addLayout(row)
        self.status = plain_label('', 'caption')
        root.addWidget(self.status)
        root.addWidget(plain_label('密钥按当前 Windows 用户加密，备份不包含密钥。更换服务地址或恢复备份后需重新填写。测试连接只发送测试文本，也可能产生少量费用。', 'caption'))
        client.busy_changed.connect(self.set_busy)
        client.succeeded.connect(self.on_success)
        client.failed.connect(self.on_failure)
        self.load()
        self.set_busy(False)

    def update_endpoint(self):
        try:
            text = '最终接口：' + endpoint_url(self.base.text())
        except ValueError:
            text = '不自动补充 /v1；支持 API 根地址或完整 /chat/completions 地址。'
        self.endpoint.setText(text)

    def load(self):
        config = self.store.ai_config()
        self.base.setText(config['endpoint'])
        self.model.setText(config['model'])
        self.key.clear()
        self.show_key.setChecked(False)
        try:
            present = bool(self.vault.get(config['endpoint'], self.store.settings()['ai_key_token']))
            self.key.setPlaceholderText('已加密保存；留空保留现有密钥' if present else '在这里填写，不要发到聊天中')
            self.status.setText('密钥已加密保存。' if present else '尚未设置可用密钥。')
        except ValueError as error:
            self.status.setText(str(error))
        self.update_endpoint()

    def save(self):
        if self.client.busy:
            return None
        try:
            config = checked_config(dict(endpoint=self.base.text(), model=self.model.text()))
            old = self.store.ai_config()
            token = self.store.settings()['ai_key_token']
            changed = config['endpoint'] != old['endpoint']
            if changed or not token:
                token = uuid4().hex
            if self.key.text().strip():
                self.vault.save(config['endpoint'], token, self.key.text())
            elif changed:
                self.vault.clear()
            self.store.update_settings({'ai_config': config, 'ai_key_token': token})
            self.load()
            self.saved.emit()
            return config
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status.setText(str(error) if isinstance(error, ValueError) else '保存失败，请检查数据目录是否可写。')
            return None

    def clear(self):
        if self.client.busy:
            return
        try:
            self.store.update_settings({'ai_key_token': uuid4().hex})
            self.vault.clear()
            self.key.clear()
            self.key.setPlaceholderText('密钥已清除，请重新填写')
            self.status.setText('密钥已清除。地址和模型设置仍保留。')
        except (OSError, sqlite3.Error):
            self.status.setText('清除失败，请检查数据目录。')

    def test(self):
        config = self.save()
        if config is None:
            return
        try:
            key = self.vault.get(config['endpoint'], self.store.settings()['ai_key_token'])
            self.client.send(config, key, [{'role': 'user', 'content': '连接测试，请只回复：连接成功。'}], {'kind': 'test'})
            self.status.setText('正在测试连接，仅发送测试文本……')
        except ValueError as error:
            self.status.setText(str(error))

    def set_busy(self, busy):
        for widget in (self.base, self.model, self.key, self.save_button, self.test_button, self.clear_button, self.show_key):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def on_success(self, context, answer):
        if context['kind'] == 'test':
            self.status.setText('连接成功，已收到有效文字回答。可以到「AI 分析」生成日报。')

    def on_failure(self, context, error):
        if context['kind'] == 'test':
            self.status.setText(error)


class AIPage(QWidget):
    def __init__(self, store, client, open_settings, parent=None):
        super().__init__(parent)
        self.store, self.client = store, client
        self.vault = KeyVault(store.directory)
        self.session = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        start = Card('从记录里，找到适合自己的下一步')
        row = QHBoxLayout()
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        self.date.setMaximumDate(QDate.currentDate())
        row.addWidget(self.date)
        row.addStretch()
        row.addWidget(button('配置 API →', open_settings, 'link'))
        start.body.addLayout(row)
        self.reflection = QCheckBox('本次分析包含这一天的「今日回顾」')
        start.body.addWidget(self.reflection)
        self.destination = plain_label('', 'caption')
        start.body.addWidget(self.destination)
        start.body.addWidget(plain_label('只分析已保存的记录。默认发送当天饮食备注及近七天统计；发送前可查看全部内容。分析结果供参考，不能替代诊疗。', 'caption'))
        row = QHBoxLayout()
        self.analyze_button = button('预览并生成日报', self.analyze)
        self.cancel_button = button('取消请求', lambda: client.cancel(), 'secondary')
        row.addWidget(self.analyze_button)
        row.addWidget(self.cancel_button)
        row.addStretch()
        start.body.addLayout(row)
        self.status = plain_label('', 'muted')
        start.body.addWidget(self.status)
        root.addWidget(start)

        report = Card('每日回顾与对话')
        row = QHBoxLayout()
        self.history = QComboBox()
        self.history.setMinimumWidth(190)
        self.history.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.history.setMinimumContentsLength(18)
        row.addWidget(self.history, 1)
        self.copy_button = button('复制', self.copy, 'secondary')
        self.export_button = button('导出文本', self.export, 'secondary')
        row.addWidget(self.copy_button)
        row.addWidget(self.export_button)
        report.body.addLayout(row)
        self.meta = plain_label('', 'caption')
        report.body.addWidget(self.meta)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(300)
        self.output.setPlaceholderText('生成第一份日报后，可以在这里回看、追问。每次重新分析都会保留旧报告。')
        report.body.addWidget(self.output)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText('继续追问，例如：结合今天的记录，明天午餐可以怎么搭配？')
        self.question.setFixedHeight(90)
        report.body.addWidget(self.question)
        row = QHBoxLayout()
        row.addWidget(plain_label('追问沿用选中报告的数据快照，并附带最近六轮问答。', 'caption'), 1)
        self.follow_button = button('预览并发送追问', self.followup)
        row.addWidget(self.follow_button)
        report.body.addLayout(row)
        root.addWidget(report)
        self.date.dateChanged.connect(lambda: self.refresh(reset=True))
        self.history.currentIndexChanged.connect(self.select_session)
        client.busy_changed.connect(self.set_busy)
        client.succeeded.connect(self.on_success)
        client.failed.connect(self.on_failure)
        self.refresh()

    def day(self):
        return self.date.date().toString('yyyy-MM-dd')

    def refresh(self, reset=False, selected=None):
        config = self.store.ai_config()
        self.destination.setText(('服务：' + config['endpoint'] + '\n模型：' + config['model']) if config['endpoint'] else '尚未配置 API。点击右上角「配置 API」开始。')
        old = selected if selected is not None else (None if reset else self.history.currentData())
        self.history.blockSignals(True)
        self.history.clear()
        for item in self.store.ai_sessions(self.day()):
            self.history.addItem(f"{item['created_at'].replace('T',' ')} · {item['model']} · #{item['id']}", item['id'])
        if old is not None and self.history.findData(old) >= 0:
            self.history.setCurrentIndex(self.history.findData(old))
        self.history.blockSignals(False)
        self.select_session()

    def select_session(self):
        self.session = self.store.ai_session(self.history.currentData()) if self.history.currentData() is not None else None
        if self.session:
            session = self.session
            self.output.setPlainText(self.transcript())
            meta = f"分析日期：{session['day']} · {session['endpoint']}\n模型：{session['model']} · "
            try:
                changed = fingerprint(daily_context(self.store, session['day'], bool(session['include_reflection']))) != session['input_hash']
            except ValueError:
                changed = True
            meta += '记录已更新；追问仍使用旧快照，可重新生成日报。' if changed else '使用生成时的数据快照。'
            config = self.store.ai_config()
            if any(session[k] != config[k] for k in ('endpoint', 'model')):
                meta += '\nAPI 配置已改变，请生成新报告后再追问。'
            self.meta.setText(meta)
        else:
            self.output.clear()
            self.meta.setText('这一天还没有 AI 报告。')
        self.set_busy(self.client.busy)

    def transcript(self):
        if not self.session:
            return ''
        s = self.session
        text = f"{s['day']} 每日回顾\n生成于 {s['created_at']} · 模型 {s['model']}\n\n{s['report']}"
        for message in self.store.ai_messages(s['id']):
            text += '\n\n' + ('我：' if message['role'] == 'user' else 'AI：') + '\n' + message['content']
        return text

    def set_busy(self, busy):
        for widget in (self.date, self.reflection, self.history, self.analyze_button):
            widget.setEnabled(not busy)
        self.question.setReadOnly(busy)
        self.follow_button.setEnabled(not busy and self.session is not None)
        self.cancel_button.setEnabled(busy)
        self.copy_button.setEnabled(self.session is not None)
        self.export_button.setEnabled(self.session is not None)

    def credentials(self):
        config = checked_config(self.store.ai_config())
        key = self.vault.get(config['endpoint'], self.store.settings()['ai_key_token'])
        if not key:
            raise ValueError('请先在设置中填写并保存 API Key。')
        return config, key

    def confirm(self, config, messages):
        scope = f"分析日期：{self.day()} · 参考范围：{self.date.date().addDays(-6).toString('yyyy-MM-dd')} 至 {self.day()}"
        return RequestPreview(config, messages, self, scope).exec() == QDialog.Accepted

    def analyze(self):
        if self.client.busy:
            return
        try:
            snapshot = daily_context(self.store, self.day(), self.reflection.isChecked())
            config, key = self.credentials()
            messages = report_messages(snapshot)
            if not self.confirm(config, messages):
                return
            self.client.send(config, key, messages, dict(kind='report', snapshot=snapshot, config=config, reflection=self.reflection.isChecked()))
            self.status.setText('正在分析这一天和近七天趋势……可以取消等待。')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status.setText(str(error) if isinstance(error, ValueError) else '读取本机记录失败，请重试。')

    def followup(self):
        if self.client.busy or not self.session:
            return
        try:
            config, key = self.credentials()
            if any(self.session[k] != config[k] for k in ('endpoint', 'model')):
                raise ValueError('服务地址或模型已改变，请重新生成日报后追问。')
            question = self.question.toPlainText().strip()
            messages = followup_messages(self.session, self.store.ai_messages(self.session['id']), question)
            if not self.confirm(config, messages):
                return
            self.client.send(config, key, messages, dict(kind='followup', ident=self.session['id'], question=question))
            self.status.setText('正在等待追问回答……')
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status.setText(str(error) if isinstance(error, ValueError) else '读取本机报告失败，请重试。')

    def on_success(self, context, answer):
        if context['kind'] == 'test':
            return
        try:
            if context['kind'] == 'report':
                ident = self.store.save_ai_report(context['snapshot'], context['config'], context['reflection'], answer)
            else:
                ident = context['ident']
                self.store.save_ai_followup(ident, context['question'], answer)
                self.question.clear()
            self.refresh(selected=ident)
            self.status.setText('已保存到本机。建议仅供参考；可以继续追问或回看历史报告。')
        except (ValueError, sqlite3.Error):
            self.output.setPlainText(answer)
            self.status.setText('收到回答，但本机保存失败。请先选中并复制回答，再检查磁盘空间。')

    def on_failure(self, context, error):
        if context['kind'] != 'test':
            self.status.setText(error + ' 已有报告和追问草稿保留。')

    def copy(self):
        QApplication.clipboard().setText(self.transcript())
        self.status.setText('报告与对话已复制。')

    def export(self):
        if not self.session:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出 AI 报告与对话', f"轻盈日记-AI-{self.day()}.txt", '文本文件 (*.txt)')
        if path:
            try:
                Path(path).write_text(self.transcript(), encoding='utf-8-sig')
                self.status.setText('报告与对话已导出。')
            except OSError:
                self.status.setText('导出失败，请选择可写的目录。')
