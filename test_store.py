import json
import os
import tempfile

import openpyxl

from app import label_bytes
from store import Store

d = tempfile.mkdtemp()
xlsx = os.path.join(d, "barang.xlsx")
wb = openpyxl.Workbook()
wb.active.append(["Nama Barang", "Harga", "Barcode"])
wb.active.append(["Indomie Goreng", 3500, 8998866200301])
wb.active.append(["Aqua 600ml", "Rp 4.000", "ABC-1"])
wb.active.append([None, None, None])
wb.save(xlsx)

s = Store(os.path.join(d, "data"))
assert not s.has_users()
s.setup("admin", "rahasia")
assert s.role is None and s.login("admin", "salah") is None
assert s.login("admin", "rahasia") == "admin"
assert s.import_excel(xlsx) == 2
assert s.lookup("8998866200301") == ["Indomie Goreng", 3500]
assert s.lookup(" ABC-1 ") == ["Aqua 600ml", 4000]
s.add_user("kasir", "123", "scanner")

bad = os.path.join(d, "bad.xlsx")
wb.active.append(["Teh", "mahal", "999"])
wb.save(bad)
try:
    s.import_excel(bad)
    raise AssertionError("bad excel accepted")
except ValueError as e:
    assert "Baris 5" in str(e)
assert s.lookup("ABC-1")  # old data kept after failed import

s.logout()
s2 = Store(s.users_path.rsplit(os.sep, 1)[0])
assert s2.login("kasir", "123") == "scanner"
assert s2.lookup("8998866200301")
try:
    s2.add_user("x", "x", "admin")
    raise AssertionError("scanner added user")
except PermissionError:
    pass

# tampering with role in users.json must break login
users = json.load(open(s.users_path))
users["kasir"]["role"] = "admin"
json.dump(users, open(s.users_path, "w"))
assert Store(os.path.dirname(s.users_path)).login("kasir", "123") is None

assert b"Indomie" not in open(s.items_path, "rb").read()

lb = label_bytes("Indomie Goreng", 3500, "8998866200301")
assert b"Rp 3.500" in lb and b"\x1dk\x49" in lb
print("OK")
