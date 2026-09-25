import json
import os
import tempfile

import openpyxl

from app import label_bytes, render_label
from store import Store, parse_excel

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
assert s.import_excel(xlsx) == 2 and s.source == "barang.xlsx"
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
assert s.lookup("ABC-1") and s.source == "barang.xlsx"  # old data kept after failed import

s.logout()
s2 = Store(s.users_path.rsplit(os.sep, 1)[0])
assert s2.login("kasir", "123") == "scanner"
assert s2.lookup("8998866200301") and s2.source == "barang.xlsx"
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

# header is optional: no header -> row 1 is data; any header text (Harga not a number) -> skipped
for first, n in [(["Teh Botol", 5000, "111"], 2), (["Nama", "Harga Jual", "Kode"], 1)]:
    wb = openpyxl.Workbook()
    wb.active.append(first)
    wb.active.append(["Kopi", 2000, "222"])
    p = os.path.join(d, "h.xlsx")
    wb.save(p)
    assert len(parse_excel(p)) == n, first

img = render_label("Indomie Goreng Rasa Ayam Bawang Special", 125000, "8998866200301")
lb = label_bytes(img, 12)
assert img.width == 384 and lb.startswith(b"\x1b@") and b"\x1dv0\x00" in lb and lb.endswith(b"\x1bJ\x60")
assert b"\x1dV" not in lb  # no cut command: printer has no cutter
print("OK")
