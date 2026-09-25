"""Encrypted item store + users. No GUI, so it can be tested anywhere.

The master key that encrypts items.enc is never stored in plain form: each user
entry in users.json holds a copy wrapped with a key derived from that user's
password (scrypt). username+role are the AES-GCM associated data, so editing a
role in the file makes the login fail. Without a valid password the data is
unreadable, even with the source code.
"""
import json
import os

import openpyxl
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROLES = ("admin", "scanner", "printer")


def _kek(password, salt):
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def _aad(username, role):
    return f"{username}\0{role}".encode()


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
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.users_path = os.path.join(folder, "users.json")
        self.items_path = os.path.join(folder, "items.enc")
        self.logout()

    def logout(self):
        self.key = self.user = self.role = self.source = None
        self.items = {}

    def has_users(self):
        return os.path.exists(self.users_path)

    def _users(self):
        if not self.has_users():
            return {}
        with open(self.users_path, encoding="utf-8") as f:
            return json.load(f)

    def _save_users(self, users):
        _write(self.users_path, json.dumps(users, indent=1).encode())

    def _save_items(self, items, source):
        """source = name of the imported Excel file, kept encrypted with the items."""
        data = json.dumps({"file": source, "items": items}).encode()
        nonce = os.urandom(12)
        _write(self.items_path, nonce + AESGCM(self.key).encrypt(nonce, data, None))

    def setup(self, username, password):
        """First run: new master key, first admin. Any old data becomes garbage."""
        if self.has_users():
            raise ValueError("Sudah ada user")
        self.key, self.role = AESGCM.generate_key(256), "admin"
        self._save_items({}, None)
        self._put_user({}, username, password, "admin")
        self.logout()

    def login(self, username, password):
        u = self._users().get(username)
        if not u:
            return None
        try:
            kek = _kek(password, bytes.fromhex(u["salt"]))
            key = AESGCM(kek).decrypt(bytes.fromhex(u["nonce"]), bytes.fromhex(u["key"]), _aad(username, u["role"]))
        except (InvalidTag, ValueError, KeyError):
            return None
        self.key, self.user, self.role = key, username, u["role"]
        if os.path.exists(self.items_path):
            with open(self.items_path, "rb") as f:
                blob = f.read()
            data = json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], None))
            self.items, self.source = data.get("items", data), data.get("file")  # old files: bare items dict
        return self.role

    def _put_user(self, users, username, password, role):
        salt, nonce = os.urandom(16), os.urandom(12)
        wrapped = AESGCM(_kek(password, salt)).encrypt(nonce, self.key, _aad(username, role))
        users[username] = {"role": role, "salt": salt.hex(), "nonce": nonce.hex(), "key": wrapped.hex()}
        self._save_users(users)

    def _require_admin(self):
        if self.role != "admin" or not self.key:
            raise PermissionError("Hanya admin")

    def add_user(self, username, password, role):
        self._require_admin()
        users = self._users()
        if not username or not password:
            raise ValueError("Username dan password wajib diisi")
        if role not in ROLES:
            raise ValueError("Role tidak valid")
        if username in users:
            raise ValueError("Username sudah dipakai")
        self._put_user(users, username, password, role)

    def delete_user(self, username):
        self._require_admin()
        if username == self.user:
            raise ValueError("Tidak bisa menghapus akun sendiri")
        users = self._users()
        users.pop(username, None)
        self._save_users(users)

    def list_users(self):
        self._require_admin()
        return sorted((name, u["role"]) for name, u in self._users().items())

    def import_excel(self, path):
        self._require_admin()
        items = parse_excel(path)  # raises before anything is replaced
        source = os.path.basename(path)
        self._save_items(items, source)
        self.items, self.source = items, source
        return len(items)

    def lookup(self, barcode):
        return self.items.get(barcode.strip())
