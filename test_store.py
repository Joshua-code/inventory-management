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

db_dir = os.path.join(d, "data")
os.mkdir(db_dir)
path = os.path.join(db_dir, "toko.rptdb")
s = Store(path)
assert not s.exists()
s.setup("admin", "rahasia")
assert s.role is None and s.login("admin", "salah") is None and s.login("nobody", "rahasia") is None
assert s.login("admin", "rahasia") == "admin"
assert s.import_excel(xlsx) == 2 and s.source == "barang.xlsx"
assert s.lookup("8998866200301") == ["Indomie Goreng", 3500]
assert s.lookup(" ABC-1 ") == ["Aqua 600ml", 4000]
s.add_user("kasir", "123", "scanner")
s.add_user("tmp", "456", "printer")
assert s.list_users() == [("admin", "admin"), ("kasir", "scanner"), ("tmp", "printer")]

bad = os.path.join(d, "bad.xlsx")
wb.active.append(["Teh", "mahal", "999"])
wb.save(bad)
try:
    s.import_excel(bad)
    raise AssertionError("bad excel accepted")
except ValueError as e:
    assert "Baris 5" in str(e)
assert s.lookup("ABC-1") and s.source == "barang.xlsx"  # old data kept after failed import

s.delete_user("tmp")
assert Store(path).login("tmp", "456") is None

# exactly one file, nothing readable inside it
assert os.listdir(db_dir) == ["toko.rptdb"]
raw = open(path, "rb").read()
for secret in [b"admin", b"kasir", b"scanner", b"Indomie", b"barang.xlsx", b"8998866200301"]:
    assert secret not in raw, secret

s.logout()
s2 = Store(path)
assert s2.login("kasir", "123") == "scanner"
assert s2.lookup("8998866200301") and s2.source == "barang.xlsx"
try:
    s2.add_user("x", "x", "admin")
    raise AssertionError("scanner added user")
except PermissionError:
    pass

# tampering with the encrypted data must not open
doc = json.loads(raw)
doc["data"] = doc["data"][:-2] + ("00" if doc["data"][-2:] != "00" else "11")
json.dump(doc, open(path, "w"))
try:
    Store(path).login("kasir", "123")
    raise AssertionError("tampered data opened")
except Exception as e:
    assert not isinstance(e, AssertionError)

# not a database
junk = os.path.join(d, "junk.rptdb")
open(junk, "w").write("hello")
try:
    Store(junk).login("admin", "x")
    raise AssertionError("junk accepted")
except ValueError as e:
    assert "valid" in str(e)

# header is optional: no header -> row 1 is data; any header text (Harga not a number) -> skipped
for first, n in [(["Teh Botol", 5000, "111"], 2), (["Nama", "Harga Jual", "Kode"], 1)]:
    wb = openpyxl.Workbook()
    wb.active.append(first)
    wb.active.append(["Kopi", 2000, "222"])
    p = os.path.join(d, "h.xlsx")
    wb.save(p)
    assert len(parse_excel(p)) == n, first

img = render_label("Indomie Goreng Rasa Ayam Bawang Special", 125000, "8998866200301")
lb = label_bytes(img)
assert img.width == 384 and lb.startswith(b"\x1b@") and b"\x1dv0\x00" in lb and lb.endswith(b"\x1bJ\xc8")  # 25mm
assert b"\x1dV" not in lb  # no cut command: printer has no cutter
print("OK")
