"""Self-signed loopback test service; no system trust-store changes."""
import ssl
from pathlib import Path
from lightdiary.qa_api import StubServer

FIXTURES = Path(__file__).parent / 'fixtures'


def tls_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(FIXTURES/'loopback-test-cert.pem'), str(FIXTURES/'loopback-test-key.pem'))
    class TLSServer(StubServer):
        def process_request_thread(self, request, client_address):
            # TLS handshakes must not block the server's accept/shutdown loop.
            try:
                request.settimeout(5)
                wrapped = context.wrap_socket(request, server_side=True)
                super().process_request_thread(wrapped, client_address)
            except (ssl.SSLError, OSError):
                request.close()
    server = TLSServer()
    return server.start()
