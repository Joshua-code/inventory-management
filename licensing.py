"""Offline device license: activation code = Ed25519 signature of the Device ID.
The same signature check also protects app updates (see updater.py).

Only the public key is here; codes are made with keygen.py and the private key,
which never leaves the developer's machine.
"""
import base64
import hashlib
import re
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PUBLIC_KEY = "b2589df4ab10b93fd2c343d0b77a76d0479788a9b084c92d4e856f7855cd79ff"


def device_id():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            guid = winreg.QueryValueEx(k, "MachineGuid")[0]
    except (ImportError, OSError):
        guid = str(uuid.getnode())  # non-Windows (dev machines)
    raw = base64.b32encode(hashlib.sha256(f"rptm:{guid}".encode()).digest()[:10]).decode()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def format_code(sig):
    raw = base64.b32encode(sig).decode().rstrip("=")
    return "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))


def verify_sig(sig_text, message):
    """True if sig_text (base32, any spacing/case) is the developer's signature of message (bytes)."""
    s = re.sub(r"[^A-Z2-7]", "", sig_text.upper().replace("0", "O").replace("1", "I"))
    try:
        sig = base64.b32decode(s + "=" * (-len(s) % 8))
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(sig, message)
        return True
    except (ValueError, InvalidSignature):
        return False


def verify(code, device):
    return verify_sig(code, device.encode())
