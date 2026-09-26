"""Developer tool (not bundled in the exe). Keep the private key safe and backed up.

  python keygen.py init                  # once: create private key, print public key for licensing.py
  python keygen.py XXXX-XXXX-XXXX-XXXX   # activation code for that Device ID
"""
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import format_code

KEY_FILE = os.path.join(os.path.expanduser("~"), ".rptm", "license_private.key")

if len(sys.argv) != 2:
    sys.exit(__doc__)

if sys.argv[1] == "init":
    if os.path.exists(KEY_FILE):
        sys.exit(f"Key already exists: {KEY_FILE}")
    key = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(KEY_FILE), mode=0o700, exist_ok=True)
    with open(os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()))
    print(f"Private key saved: {KEY_FILE}  (BACK IT UP)")
    print("PUBLIC_KEY =", key.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw).hex())
else:
    with open(KEY_FILE, "rb") as f:
        key = Ed25519PrivateKey.from_private_bytes(f.read())
    print(format_code(key.sign(sys.argv[1].strip().upper().encode())))
