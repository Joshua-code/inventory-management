import json
import os
import tempfile

import openpyxl
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

import keygen
import licensing
from app import label_bytes, render_label
from store import PERMS, AccessRevoked, Store, _perms, parse_excel

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
assert s.perms == [] and s.login("admin", "salah") is None and s.login("nobody", "rahasia") is None
assert s.login("admin", "rahasia") == list(PERMS)
assert s.import_excel(xlsx) == 2 and s.source == "barang.xlsx"
assert s.lookup("8998866200301") == ["Indomie Goreng", 3500]
assert s.lookup(" ABC-1 ") == ["Aqua 600ml", 4000]
s.add_user("kasir", "123", ["scanner"])
s.add_user("tmp", "456", ["printer", "scanner"])
assert s.list_users() == [("admin", list(PERMS)), ("kasir", ["scanner"]), ("tmp", ["scanner", "printer"])]
for bad_args in [("x", "x", []), ("x", "x", ["nope"]), ("admin", "x", ["scanner"])]:
    try:
        s.add_user(*bad_args)
        raise AssertionError(bad_args)
    except ValueError:
        pass
s.set_perms("tmp", ["printer"])
assert dict(s.list_users())["tmp"] == ["printer"]
for bad_args in [("tmp", []), ("admin", ["scanner", "update"]), ("ghost", ["scanner"])]:
    try:
        s.set_perms(*bad_args)
        raise AssertionError(bad_args)
    except ValueError:
        pass
assert _perms("admin") == list(PERMS) and _perms("scanner") == ["scanner"] and _perms("printer") == ["printer"]
assert _perms(["users", "bogus", "scanner"]) == ["scanner", "users"] and _perms(None) == []

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
for secret in [b"admin", b"kasir", b"scanner", b"Indomie", b"8998866200301"]:
    assert secret not in raw, secret

file, when = Store(path).info()  # readable before login
assert file == "barang.xlsx" and when and Store(os.path.join(d, "none.rptdb")).info() == (None, None)

s.logout()
s2 = Store(path)
assert s2.login("kasir", "123") == ["scanner"]
assert s2.lookup("8998866200301") and s2.source == "barang.xlsx"
for fn, args in [(s2.add_user, ("x", "x", ["scanner"])), (s2.import_excel, (xlsx,)), (s2.list_users, ())]:
    try:
        fn(*args)
        raise AssertionError(f"{fn.__name__} without access")
    except PermissionError:
        pass

# sync: another laptop changes the file -> reload picks it up without logging out
assert s2.reload_if_changed() is False
admin = Store(path)
admin.login("admin", "rahasia")
wb2 = openpyxl.Workbook()
wb2.active.append(["Kopi Kapal Api", 1500, "555"])
x2 = os.path.join(d, "baru.xlsx")
wb2.save(x2)
os.utime(path, (0, 0))  # make sure mtime differs even on coarse filesystems
admin.import_excel(x2)
assert s2.reload_if_changed() is True and s2.lookup("555") == ["Kopi Kapal Api", 1500] and s2.source == "baru.xlsx"
assert s2.reload_if_changed() is False
os.utime(path, (1, 1))
admin.set_perms("kasir", ["scanner", "printer"])
assert s2.reload_if_changed() and s2.perms == ["scanner", "printer"]
os.utime(path, (2, 2))
admin.delete_user("kasir")
try:
    s2.reload_if_changed()
    raise AssertionError("deleted user kept access")
except AccessRevoked:
    assert s2.key is None
raw = open(path, "rb").read()

# tampering with the encrypted data must not open
doc = json.loads(raw)
doc["data"] = doc["data"][:-2] + ("00" if doc["data"][-2:] != "00" else "11")
json.dump(doc, open(path, "w"))
try:
    Store(path).login("admin", "rahasia")
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

# license: code signed for device A works only on A
k = Ed25519PrivateKey.generate()
licensing.PUBLIC_KEY = k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
code = licensing.format_code(k.sign(b"AAAA-BBBB-CCCC-DDDD"))
assert licensing.verify(code, "AAAA-BBBB-CCCC-DDDD")
assert licensing.verify(" " + code.lower().replace("-", " ") + "\n", "AAAA-BBBB-CCCC-DDDD")
assert not licensing.verify(code, "AAAA-BBBB-CCCC-DDDE")
assert not licensing.verify("garbage", "AAAA-BBBB-CCCC-DDDD") and not licensing.verify("", "AAAA-BBBB-CCCC-DDDD")
assert len(licensing.device_id()) == 19

# generator: only the matching key file is accepted; ID format is checked
raw = lambda key: key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())  # noqa: E731
for name, data in [("good.key", raw(k)), ("other.key", raw(Ed25519PrivateKey.generate())), ("junk.key", b"x")]:
    open(os.path.join(d, name), "wb").write(data)
gk = keygen.load_key(os.path.join(d, "good.key"))
for name in ["other.key", "junk.key"]:
    try:
        keygen.load_key(os.path.join(d, name))
        raise AssertionError(name)
    except ValueError:
        pass
assert licensing.verify(keygen.make_code(gk, "aaaabbbbccccdddd"), "AAAA-BBBB-CCCC-DDDD")
try:
    keygen.make_code(gk, "not-an-id")
    raise AssertionError("bad id accepted")
except ValueError:
    pass
print("OK")
