"""Synthetic loopback API used only by --smoke-test and automated tests."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEMO_REPORT = '''记录完整程度
这份报告来自独立测试数据，用于展示界面，不是对个人情况的实际分析。

今天的饮食
已记录三餐。食物份量和营养为参考估算；可结合实际吃下的油、酱料及饮料补充记录。

活动与七天趋势
记录中包含散步和步数。关注连续一段时间的变化；一次体重波动不足以说明减脂效果。

下一步
1. 吃完再记录实际份量，确认零食和饮料没有遗漏。
2. 午餐按自己的忌口搭配主食、蛋白质食物和蔬菜。
3. 保持适合自己的活动节奏。超过目标时继续正常吃饭，不跳餐补偿。'''


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.calls = []
        self.status = 200
        self.body = None
        self.delay = 0
        self.headers_extra = {}
        self.thread = None

    @property
    def endpoint(self):
        return f'http://127.0.0.1:{self.server_port}/v1/chat/completions'

    def start(self):
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.shutdown()
        self.server_close()
        if self.thread:
            self.thread.join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.calls.append((self.path, dict(self.headers), json.loads(body)))
        time.sleep(self.server.delay)
        response = self.server.body
        if response is None:
            response = json.dumps({'choices': [{'message': {'content': DEMO_REPORT}, 'finish_reason': 'stop'}]}, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(self.server.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            for key, value in self.server.headers_extra.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response)
        except (OSError, ConnectionError):
            pass
