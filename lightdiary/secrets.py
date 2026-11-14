"""Windows current-user DPAPI; no plaintext fallback and no secrets in SQLite."""
import ctypes
import json
import os
import tempfile
from pathlib import Path
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('API 密钥加密仅支持 Windows。')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    func = library.CryptUnprotectData if decrypt else library.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('Windows 无法加密或解密密钥，请在当前账户重新填写。')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def checked_key(key):
    key = key.strip()
    if not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('请填写有效的 API Key，不要包含空格或换行。')
    return key


class KeyVault:
    def __init__(self, directory):
        self.path = Path(directory) / 'api-key.dpapi'

    def save(self, endpoint, token, key):
        payload = json.dumps(dict(endpoint=endpoint, token=token, key=checked_key(key))).encode('utf-8')
        encrypted = dpapi(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix='.api-key-', dir=self.path.parent)
        try:
            with os.fdopen(handle, 'wb') as stream:
                stream.write(encrypted)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def get(self, endpoint, token):
        if not self.path.exists() or not token:
            return ''
        try:
            value = json.loads(dpapi(self.path.read_bytes(), decrypt=True).decode('utf-8'))
            if value['endpoint'] != endpoint or value['token'] != token:
                return ''
            return checked_key(value['key'])
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError('无法读取已保存的密钥，请在设置中重新填写。') from None

    def clear(self):
        self.path.unlink(missing_ok=True)
