"""Immutable report snapshots and atomic follow-up pairs."""
import json
from datetime import datetime
from .ai import PROMPT_VERSION, checked_config, encode, fingerprint

AI_TABLES = ('ai_sessions', 'ai_messages')


def migrate_ai(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS ai_sessions (
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, created_at TEXT NOT NULL,
        endpoint TEXT NOT NULL, model TEXT NOT NULL, include_reflection INTEGER NOT NULL,
        snapshot TEXT NOT NULL, input_hash TEXT NOT NULL, prompt_version TEXT NOT NULL, report TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS ai_sessions_day ON ai_sessions(day)')
    connection.execute('CREATE INDEX IF NOT EXISTS ai_messages_session ON ai_messages(session_id)')


class AIStore:
    def ai_config(self):
        return checked_config(self.settings().get('ai_config', {}), allow_empty=True)

    def ai_sessions(self, day):
        return [dict(row) for row in self.connection.execute(
            'SELECT id,day,created_at,endpoint,model FROM ai_sessions WHERE day=? ORDER BY id DESC', (day,))]

    def ai_session(self, ident):
        row = self.connection.execute('SELECT * FROM ai_sessions WHERE id=?', (ident,)).fetchone()
        return {**dict(row), 'snapshot': json.loads(row['snapshot'])} if row else None

    def ai_messages(self, ident):
        return [dict(row) for row in self.connection.execute('SELECT * FROM ai_messages WHERE session_id=? ORDER BY id', (ident,))]

    def save_ai_report(self, snapshot, config, include_reflection, report):
        from .storage import valid_day
        valid_day(snapshot['分析日期'])
        config = checked_config(config)
        if not isinstance(report, str) or not report.strip():
            raise ValueError('分析结果为空。')
        with self.connection:
            cursor = self.connection.execute('''INSERT INTO ai_sessions
                (day,created_at,endpoint,model,include_reflection,snapshot,input_hash,prompt_version,report)
                VALUES (?,?,?,?,?,?,?,?,?)''', (snapshot['分析日期'], datetime.now().isoformat(timespec='seconds'),
                config['endpoint'], config['model'], int(bool(include_reflection)), encode(snapshot), fingerprint(snapshot), PROMPT_VERSION, report))
        return cursor.lastrowid

    def save_ai_followup(self, ident, question, answer):
        if not question.strip() or not answer.strip():
            raise ValueError('追问或回答为空。')
        with self.connection:
            self.connection.executemany('INSERT INTO ai_messages(session_id,role,content,created_at) VALUES (?,?,?,?)',
                [(ident, role, content, datetime.now().isoformat(timespec='seconds')) for role, content in [('user', question), ('assistant', answer)]])

    def validate_ai_backup(self):
        self.ai_config()
        for row in self.connection.execute('SELECT id FROM ai_sessions'):
            session = self.ai_session(row[0])
            checked_config(session)
            if (not isinstance(session['snapshot'], dict) or session['snapshot'].get('分析日期') != session['day']
                    or fingerprint(session['snapshot']) != session['input_hash'] or not session['report'].strip()
                    or session['include_reflection'] not in (0, 1) or session['prompt_version'] != PROMPT_VERSION):
                raise ValueError('备份中的 AI 报告不完整，当前数据未修改。')
            history = self.ai_messages(session['id'])
            if len(history) % 2 or any(m['role'] != ('user' if i % 2 == 0 else 'assistant') or not m['content'].strip() for i, m in enumerate(history)):
                raise ValueError('备份中的 AI 对话不完整，当前数据未修改。')
