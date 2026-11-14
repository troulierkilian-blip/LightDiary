These self-signed certificate/key files are public test fixtures, not credentials.
They are used only by a 127.0.0.1 mock HTTPS service. The certificate is added to
the Qt test request trust configuration, never to the Windows certificate store.
They are included in the source ZIP, not in the delivered executable.
Generated with OpenSSL req -x509 -newkey rsa:2048 -nodes, valid for 3650 days from
2026-10-16, SAN IP:127.0.0.1,DNS:localhost. They do not authenticate a real service.
