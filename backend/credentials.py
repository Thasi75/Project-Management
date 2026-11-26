"""API secrets remain outside business data. Windows encrypts with per-user DPAPI."""
import ctypes
import os
from ctypes import wintypes
from .config import LOCAL
from .service import fail


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def crypt(data, encrypt=True):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    function = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        fail('Windows 凭据加密或解密失败，请重新设置 API Key', 500)
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def read_key():
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY']
    path = LOCAL / 'openai.key'
    if path.exists() and os.name == 'nt':
        return crypt(path.read_bytes(), False).decode()
    return ''


def save_key(value):
    if os.name != 'nt':
        fail('此平台请通过 OPENAI_API_KEY 环境变量配置密钥')
    path = LOCAL / 'openai.key'
    if not value:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(crypt(value.encode()))
