"""Encrypted single-file database + users. No GUI, so it can be tested anywhere.

File (.rptdb, JSON):
  salt  - random, for username ids
  keys  - {HMAC(salt, username): master key wrapped with scrypt(password), AAD=username}
  data  - AES-256-GCM(master key, {"file", "items", "users": {username: role}})
Usernames, roles and items are unreadable without a valid password, even with
the source code; roles can't be edited because they live inside the encrypted data.
"""
import hmac
import json
import os

import openpyxl
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROLES = ("admin", "scanner", "printer")


def _kek(password, salt):
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def _id(doc, username):
    return hmac.new(bytes.fromhex(doc["salt"]), username.encode(), "sha256").hexdigest()


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _barcode(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() if v is not None else ""


def _price(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(v)
    s = str(v or "").replace("Rp", "").replace(" ", "").replace(".", "")
    if not s.isdigit():
        raise ValueError
    return int(s)


def parse_excel(path):
    """Columns A=Nama Barang, B=Harga, C=Barcode; row 1 is skipped as a header when
    its Harga isn't a number. Return {barcode: [name, price]}; raise ValueError
    with a readable message."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        items = {}
        for i, row in enumerate(wb.active.iter_rows(values_only=True), start=1):
            name, price, code = (list(row) + [None] * 3)[:3]
            name, code = str(name or "").strip(), _barcode(code)
            if not name and not code and price in (None, ""):
                continue
            try:
                price = _price(price)
            except ValueError:
                if i == 1:
                    continue  # header row
                raise ValueError(f"Baris {i}: Harga harus angka") from None
            if not name or not code:
                raise ValueError(f"Baris {i}: Nama Barang dan Barcode wajib diisi")
            if code in items:
                raise ValueError(f"Baris {i}: Barcode {code} duplikat")
            items[code] = [name, price]
    finally:
        wb.close()
    if not items:
        raise ValueError("File Excel tidak berisi barang")
    return items


class Store:
    def __init__(self, path):
        self.path = path
        self.logout()

    def logout(self):
        self.key = self.user = self.role = self.source = None
        self.items, self.users = {}, {}

    def exists(self):
        return os.path.exists(self.path)

    def _read(self):
        try:
            with open(self.path, "rb") as f:
                doc = json.load(f)
            if doc["app"] != "rptm" or not isinstance(doc["keys"], dict):
                raise ValueError
            _id(doc, ""), bytes.fromhex(doc["data"])
        except (ValueError, KeyError, TypeError):
            raise ValueError("Bukan file database yang valid") from None
        return doc

    def _decrypt(self, doc, key):
        blob = bytes.fromhex(doc["data"])
        return json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], None))

    def _save(self, doc, data):
        nonce = os.urandom(12)
        doc["data"] = (nonce + AESGCM(self.key).encrypt(nonce, json.dumps(data).encode(), None)).hex()
        _write(self.path, json.dumps(doc).encode())
        self.items, self.source, self.users = data["items"], data["file"], data["users"]

    def _wrap(self, doc, username, password):
        salt, nonce = os.urandom(16), os.urandom(12)
        wrapped = AESGCM(_kek(password, salt)).encrypt(nonce, self.key, username.encode())
        doc["keys"][_id(doc, username)] = {"salt": salt.hex(), "nonce": nonce.hex(), "key": wrapped.hex()}

    def setup(self, username, password):
        """New database file with a fresh master key and the first admin."""
        if self.exists():
            raise ValueError("Database sudah ada")
        self.key = AESGCM.generate_key(256)
        doc = {"app": "rptm", "v": 1, "salt": os.urandom(16).hex(), "keys": {}}
        self._wrap(doc, username, password)
        self._save(doc, {"file": None, "items": {}, "users": {username: "admin"}})
        self.logout()

    def login(self, username, password):
        doc = self._read()
        k = doc["keys"].get(_id(doc, username))
        if not k:
            return None
        try:
            kek = _kek(password, bytes.fromhex(k["salt"]))
            key = AESGCM(kek).decrypt(bytes.fromhex(k["nonce"]), bytes.fromhex(k["key"]), username.encode())
        except (InvalidTag, ValueError, KeyError):
            return None
        data = self._decrypt(doc, key)
        role = data["users"].get(username)
        if role not in ROLES:  # deleted user
            return None
        self.key, self.user, self.role = key, username, role
        self.items, self.source, self.users = data["items"], data["file"], data["users"]
        return role

    def _require_admin(self):
        if self.role != "admin" or not self.key:
            raise PermissionError("Hanya admin")

    def _update(self, change):
        """Re-read the file first so changes saved from another laptop aren't lost."""
        self._require_admin()
        doc = self._read()
        data = self._decrypt(doc, self.key)
        change(doc, data)
        self._save(doc, data)

    def add_user(self, username, password, role):
        self._require_admin()
        if not username or not password:
            raise ValueError("Username dan password wajib diisi")
        if role not in ROLES:
            raise ValueError("Role tidak valid")

        def change(doc, data):
            if username in data["users"]:
                raise ValueError("Username sudah dipakai")
            self._wrap(doc, username, password)
            data["users"][username] = role

        self._update(change)

    def delete_user(self, username):
        self._require_admin()
        if username == self.user:
            raise ValueError("Tidak bisa menghapus akun sendiri")

        def change(doc, data):
            data["users"].pop(username, None)
            doc["keys"].pop(_id(doc, username), None)

        self._update(change)

    def list_users(self):
        self._require_admin()
        return sorted(self.users.items())

    def import_excel(self, path):
        self._require_admin()
        items = parse_excel(path)  # raises before anything is replaced
        self._update(lambda doc, data: data.update(items=items, file=os.path.basename(path)))
        return len(items)

    def lookup(self, barcode):
        return self.items.get(barcode.strip())
