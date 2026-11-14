"""Frozen-build verification, always on temporary synthetic records."""
import os
import time
from PySide6.QtTest import QTest
from PySide6.QtNetwork import QSslSocket, QSslConfiguration, QSslCertificate
from .qa_api import StubServer
from .secrets import KeyVault


def check_ai(window):
    def wait():
        deadline = time.monotonic() + 12
        while window.ai_client.busy and time.monotonic() < deadline:
            QTest.qWait(10)
        assert not window.ai_client.busy, 'Synthetic API did not finish'

    assert QSslSocket.supportsSsl(), 'Packaged Qt has no TLS support'
    old_ssl = QSslConfiguration.defaultConfiguration()
    server = None
    tls_url = os.environ.get('LIGHTDIARY_QA_TLS_URL')
    if tls_url:
        assert tls_url.startswith('https://127.0.0.1:'), 'Only a loopback TLS test is allowed'
        config = QSslConfiguration(old_ssl)
        certs = QSslCertificate.fromPath(os.environ['LIGHTDIARY_QA_TLS_CA'])
        assert certs, 'Missing test certificate'
        config.setCaCertificates(config.caCertificates() + certs)
        QSslConfiguration.setDefaultConfiguration(config)
        endpoint = tls_url
    else:
        server = StubServer().start()
        endpoint = server.endpoint
    fake_key = 'synthetic-packaged-test-not-a-real-key'
    page, settings = window.ai_page, window.api_settings
    try:
        settings.base.setText(endpoint)
        settings.model.setText('本机模拟服务 · 展示用')
        settings.key.setText(fake_key)
        assert settings.save(), 'API settings failed to save'
        assert fake_key.encode() not in KeyVault(window.store.directory).path.read_bytes()
        original_confirm = page.confirm
        page.confirm = lambda config, messages: True
        try:
            page.analyze()
            wait()
            assert page.session, 'Report missing: ' + page.status.text()
            page.question.setPlainText('这是界面验证用追问：明天午餐怎么搭配？')
            page.followup()
            wait()
            ident = page.session['id']
            assert len(window.store.ai_messages(ident)) == 2, page.status.text()
            assert page.question.toPlainText() == ''
            assert '独立测试数据' in page.output.toPlainText()
        finally:
            page.confirm = original_confirm
        return dict(ai_report=True, ai_followup=True, ai_dpapi=True,
                    tls_supported=True, tls_backend=QSslSocket.activeBackend(),
                    ai_https_mock=bool(tls_url), ai_provider_live_tested=False)
    finally:
        QSslConfiguration.setDefaultConfiguration(old_ssl)
        if server:
            server.close()
