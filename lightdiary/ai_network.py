"""One cancellable, bounded request shared by settings and the analysis page."""
import json
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply, QSslSocket
from .ai import checked_config
from .secrets import checked_key


class AIClient(QObject):
    succeeded = Signal(object, str)
    failed = Signal(object, str)
    busy_changed = Signal(bool)
    MAX_BYTES = 2 * 1024 * 1024

    def __init__(self, parent=None, timeout_ms=90000):
        super().__init__(parent)
        # Windows Schannel uses the system trust store and needs no OpenSSL installation.
        if 'schannel' in QSslSocket.availableBackends():
            QSslSocket.setActiveBackend('schannel')
        self.manager = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.cancel('请求超过 90 秒，已停止等待。可稍后手动重试。'))
        self.timeout_ms = timeout_ms
        self.reply = None
        self.context = None
        self.buffer = bytearray()
        self._key = ''
        self._abort_reason = ''

    @property
    def busy(self):
        return self.reply is not None

    def send(self, config, key, messages, context):
        if self.busy:
            raise ValueError('已有请求正在进行，请等待完成或先取消。')
        config, key = checked_config(config), checked_key(key)
        body = json.dumps(dict(model=config['model'], messages=messages, stream=False), ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(body) > self.MAX_BYTES:
            raise ValueError('本次记录或对话过长，请新建分析或缩短追问。')
        request = QNetworkRequest(QUrl(config['endpoint']))
        request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        request.setRawHeader(b'Authorization', ('Bearer ' + key).encode('ascii'))
        request.setRawHeader(b'Accept', b'application/json')
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setAttribute(QNetworkRequest.CookieLoadControlAttribute, QNetworkRequest.Manual)
        request.setAttribute(QNetworkRequest.CookieSaveControlAttribute, QNetworkRequest.Manual)
        request.setAttribute(QNetworkRequest.AuthenticationReuseAttribute, QNetworkRequest.Manual)
        self.context, self._key = context, key
        self.buffer, self._abort_reason = bytearray(), ''
        self.reply = self.manager.post(request, body)
        self.reply.setReadBufferSize(self.MAX_BYTES + 1)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.timer.start(self.timeout_ms)
        self.busy_changed.emit(True)

    def _read(self):
        if not self.reply:
            return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer) > self.MAX_BYTES:
            self.cancel('服务返回内容过大，已停止接收。请使用简短回答的模型。')

    def cancel(self, reason='已取消等待。服务商可能已处理请求并计费，软件不会自动重试。'):
        if self.reply:
            self._abort_reason = reason
            self.reply.abort()

    def shutdown(self):
        if self.reply:
            self.reply.finished.disconnect(self._finished)
            self.reply.readyRead.disconnect(self._read)
            self.reply.abort()
            self.reply.deleteLater()
            self.reply = None
        self.timer.stop()
        self.context, self._key, self.buffer = None, '', bytearray()

    def _finished(self):
        reply = self.reply
        if not reply:
            return
        self.timer.stop()
        self.buffer.extend(bytes(reply.readAll()))
        raw = bytes(self.buffer)
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        network_error = reply.error()
        error, result = self._abort_reason, ''
        if not error:
            if len(raw) > self.MAX_BYTES:
                error = '服务返回内容过大。'
            elif status and 300 <= status < 400:
                error = '接口要求重定向。为保护密钥，请在设置中填写服务商的最终接口地址。'
            elif status and status >= 400:
                error = {401: '认证失败，请检查 API Key。', 403: '无访问权限，请检查密钥、模型权限或账户状态。',
                         404: '接口或模型不存在，请检查最终地址和模型名称。',
                         429: '请求受限或额度不足，请检查账户额度并稍后手动重试。'}.get(status,
                         '服务暂时异常，请稍后手动重试。' if status >= 500 else '服务拒绝了请求，请检查地址、模型及接口兼容性。')
            elif network_error == QNetworkReply.SslHandshakeFailedError:
                error = 'HTTPS 证书或加密连接失败，请检查系统时间及服务证书。'
            elif network_error != QNetworkReply.NoError:
                error = '网络连接失败，请检查网络、服务地址或代理设置。'
            else:
                try:
                    choice = json.loads(raw)['choices'][0]
                    content = choice['message'].get('content')
                    if isinstance(content, list):
                        content = '\n'.join(p['text'] for p in content if p.get('type') == 'text' and isinstance(p.get('text'), str))
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError
                    if choice.get('finish_reason') == 'length':
                        error = '服务返回的回答被长度限制截断，请调整服务模型后手动重试。'
                    else:
                        # Never persist an echoed credential, even from a broken proxy.
                        result = content.strip().replace(self._key, '[密钥已隐藏]')
                except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                    error = '未收到有效的文字回答，请检查服务是否支持 Chat Completions 非流式接口。'
        context = self.context
        self.reply, self.context, self._key, self.buffer = None, None, '', bytearray()
        reply.deleteLater()
        self.busy_changed.emit(False)
        if error:
            self.failed.emit(context, error)
        else:
            self.succeeded.emit(context, result)
