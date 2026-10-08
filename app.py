import errno
import json
import os
import struct
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from barcode import Code128
from cryptography.exceptions import InvalidTag
from PIL import Image, ImageDraw, ImageFont, ImageTk

import licensing
import ui
from store import PERM_LABELS, PERMS, AccessRevoked, Store

APP_NAME = "Retail Price Tag Management"
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "RetailPriceTagManagement")
CONFIG = os.path.join(DATA_DIR, "config.json")
LICENSE = os.path.join(DATA_DIR, "license.txt")


def rupiah(n):
    return "Rp " + f"{n:,}".replace(",", ".")


FILE_MAX = 30  # longer Excel names are shortened in the footer so the bar never overflows


def db_info_text(file, when):
    """Footer text for the open database; long names keep their start and extension."""
    if not file:
        return ""
    if len(file) > FILE_MAX:
        file = file[:FILE_MAX - 16] + "…" + file[-15:]
    return f"File: {file}  ·  Diimpor {when}"


# ---------- printing (ESC/POS raw, 58mm = 384 dots) ----------

def list_printers():
    try:
        import win32print
    except ImportError:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def default_printer():
    try:
        import win32print
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


# Label layout in printer dots (8 dots = 1 mm). Tweak here if the print looks off.
LABEL_W = 384
NAME_PX, PRICE_PX, CODE_PX = 30, 56, 22
GAP_NAME_PRICE, GAP_PRICE_BARS, BARS_H = 16, 16, 80
FEED_MM = 25  # blank paper fed after the label so it clears the tear bar


def _font(size, bold=False):
    for name in (("arialbd.ttf", "Arial Bold.ttf") if bold else ("arial.ttf", "Arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _wrap(draw, text, font):
    lines = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= LABEL_W:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def render_label(name, price, barcode):
    """The label exactly as printed; also used as the on-screen preview."""
    img = Image.new("L", (LABEL_W, 1000), 255)
    d = ImageDraw.Draw(img)
    mid, y = LABEL_W // 2, 0
    font = _font(NAME_PX, bold=True)
    for line in _wrap(d, name, font):
        d.text((mid, y), line, font=font, fill=0, anchor="mt")
        y += NAME_PX + 4
    y += GAP_NAME_PRICE
    d.text((mid, y), rupiah(price), font=_font(PRICE_PX, bold=True), fill=0, anchor="mt")
    y += PRICE_PX + GAP_PRICE_BARS
    modules = Code128(barcode).build()[0]
    w = max(1, min(3, LABEL_W // (len(modules) + 20)))  # keep ~10 modules quiet zone each side
    x = (LABEL_W - w * len(modules)) // 2
    for i, m in enumerate(modules):
        if m == "1":
            d.rectangle([x + i * w, y, x + (i + 1) * w - 1, y + BARS_H - 1], fill=0)
    y += BARS_H + 4
    d.text((mid, y), barcode, font=_font(CODE_PX), fill=0, anchor="mt")
    return img.crop((0, 0, LABEL_W, y + CODE_PX))


def label_bytes(img):
    """ESC/POS raster (GS v 0) in 128-row bands, then feed past the tear bar. No cut: no cutter."""
    bw = img.convert("L").point(lambda p: 255 if p < 128 else 0, "1")  # bit 1 = black dot
    out = [b"\x1b@"]
    for top in range(0, bw.height, 128):
        band = bw.crop((0, top, LABEL_W, min(top + 128, bw.height)))
        out += [b"\x1dv0\x00", struct.pack("<HH", LABEL_W // 8, band.height), band.tobytes()]
    out.append(b"\x1bJ" + bytes([FEED_MM * 8]))
    return b"".join(out)


def print_label(printer, data):
    import win32print
    h = win32print.OpenPrinter(printer)
    try:
        win32print.StartDocPrinter(h, 1, ("Label Harga", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


LOGO_H = 40  # footer logo height in px; any size of assets/babelmart.png is scaled to this


def logo_image(name, height):
    img = Image.open(ui.asset(name))
    return ImageTk.PhotoImage(img.resize((round(img.width * height / img.height), height), Image.LANCZOS))


def activated():
    try:
        with open(LICENSE, encoding="utf-8") as f:
            return licensing.verify(f.read(), licensing.device_id())
    except OSError:
        return False


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


# ---------- GUI ----------

SYNC_MS = 30_000  # how often to look for a newer database file (e.g. synced by Google Drive)
NAV = [("scanner", "search"), ("printer", "print"), ("update", "upload"), ("users", "people")]
LANDING = ("update", "scanner", "printer", "users")


def error_text(e):
    if isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return "Database hanya-baca (dikelola pusat)"
    return str(e)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ui.setup(self, APP_NAME, "app.ico")
        self.geometry("1000x640")
        try:
            self.state("zoomed")  # maximized on Windows
        except tk.TclError:
            pass
        ui.header(self, APP_NAME, "app_28.png")
        self.db_info = tk.StringVar()
        ui.footer(self, logo_image("babelmart.png", LOGO_H), self.db_info)
        self.store, self.alias, self.body = Store(""), None, None
        self.updated = tk.StringVar()
        self.after(SYNC_MS, self.poll)
        self.start() if activated() else self.show_license()

    def start(self):
        """Straight to login for the last database (auto-open), else the picker."""
        cfg = load_config()
        dbs, last = cfg.get("databases", {}), cfg.get("last")
        if cfg.get("auto_open", True) and last in dbs and os.path.exists(dbs[last]):
            self.open_db(cfg, last)
        else:
            self.show_databases()

    def poll(self):
        self.after(SYNC_MS, self.poll)
        before = self.store.perms
        try:
            if not self.store.reload_if_changed():
                return
        except (InvalidTag, AccessRevoked) as e:
            self.store.logout()
            messagebox.showwarning("Database berubah", str(e) or "Database telah diganti. Silakan login lagi.")
            return self.show_login()
        except (OSError, ValueError):
            return  # file is mid-sync (e.g. Drive still writing it): try again next round
        self.updated.set(f"Diperbarui {datetime.now():%H:%M}")
        self.show_db_info()
        if self.store.perms != before:
            self.route()

    # ----- layout -----

    def show_db_info(self):
        """Footer, bottom right: source Excel file and import date of the open database."""
        try:
            file, when = self.store.info()
        except (OSError, ValueError):
            return  # file is mid-sync: keep what's shown
        self.db_info.set(db_info_text(file, when))

    def clear(self, page=None):
        """New page. With `page`, adds the sidebar and returns the content area."""
        self.show_db_info()
        if self.body:
            self.body.destroy()
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        if not page:
            return self.body
        side = ttk.Frame(self.body, style="Side.TFrame", width=240, padding=12)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        for key, icon in NAV:
            if key in self.store.perms:
                ui.Button(side, PERM_LABELS[key], icon, getattr(self, f"show_{key}"),
                          kind="nav_on" if key == page else "nav").pack(fill="x", pady=2)
        info = ttk.Frame(side, style="Side.TFrame")
        info.pack(side="bottom", fill="x")
        ttk.Label(info, text=self.store.user, style="SideUser.TLabel").pack(anchor="w")
        ttk.Label(info, text=", ".join(PERM_LABELS[p] for p in self.store.perms), style="Side.TLabel",
                  wraplength=210).pack(anchor="w", pady=(0, 8))
        for kw in ({"text": f"Database: {self.alias}"}, {"textvariable": self.updated}):
            ttk.Label(info, style="Side.TLabel", wraplength=210, **kw).pack(anchor="w")
        ui.Button(info, "Logout", "logout", self.logout).pack(fill="x", pady=(10, 0))
        content = ttk.Frame(self.body, padding=28)
        content.pack(side="left", fill="both", expand=True)
        return content

    def card(self):
        box = ttk.Frame(self.clear(), style="Card.TFrame", padding=36)
        box.place(relx=0.5, rely=0.45, anchor="center")
        return box

    def route(self):
        for p in LANDING:
            if p in self.store.perms:
                return getattr(self, f"show_{p}")()

    def logout(self):
        self.store.logout()
        self.show_login()

    # ----- before login -----

    def show_license(self):
        box = self.card()
        dev = licensing.device_id()
        ttk.Label(box, text="Aktivasi Lisensi", style="Title.TLabel").pack()
        ttk.Label(box, text="Kirim Device ID ini ke penyedia aplikasi untuk mendapatkan kode aktivasi.",
                  style="Muted.TLabel").pack(pady=(6, 16))
        row = ttk.Frame(box)
        row.pack()
        e = ttk.Entry(row, font=(ui.FONT, 16), justify="center", width=22)
        e.insert(0, dev)
        e.configure(state="readonly")
        e.pack(side="left")

        def copy():
            self.clipboard_clear()
            self.clipboard_append(dev)

        ui.Button(row, "Salin", "copy", copy).pack(side="left", padx=8)
        ttk.Label(box, text="Kode Aktivasi").pack(pady=(20, 4))
        code = tk.Text(box, width=60, height=3, wrap="char", font=(ui.FONT, 11), relief="solid",
                       borderwidth=1, highlightthickness=0)
        code.pack()
        code.focus_set()
        err = ttk.Label(box, style="Error.TLabel")
        err.pack(pady=8)

        def activate():
            c = code.get("1.0", "end").strip()
            if not licensing.verify(c, dev):
                return err.config(text="Kode aktivasi tidak valid untuk perangkat ini")
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(LICENSE, "w", encoding="utf-8") as fh:
                fh.write(c)
            self.start()

        ui.Button(box, "Aktivasi", "key", activate, kind="primary").pack()

    def show_databases(self):
        """Pick (or create) the database file, saved under an alias."""
        self.store, self.alias = Store(""), None
        f = ttk.Frame(self.clear(), padding=(48, 32))
        f.pack(fill="both", expand=True)
        cfg = load_config()
        dbs = cfg.setdefault("databases", {})
        ttk.Label(f, text="Pilih Database", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Pilih database tersimpan, atau tambahkan lokasi file baru "
                          "(misalnya folder Google Drive yang dibagikan pusat).",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 16))
        tree = ttk.Treeview(f, columns=("path",), height=8)
        tree.heading("#0", text="Alias")
        tree.heading("path", text="Lokasi File")
        tree.column("#0", width=220)
        tree.column("path", width=640)
        tree.pack(fill="x")
        for a, p in sorted(dbs.items()):
            tree.insert("", "end", iid=a, text=a, values=(p,))
        if cfg.get("last") in dbs:
            tree.selection_set(cfg["last"])
            tree.focus(cfg["last"])
        tree.focus_set()

        def open_selected(_=None):
            if tree.selection():
                self.open_db(cfg, tree.selection()[0])

        def remove():
            if tree.selection() and messagebox.askyesno(
                    "Konfirmasi", "Hapus dari daftar? (File database tidak ikut dihapus)"):
                dbs.pop(tree.selection()[0])
                save_config(cfg)
                self.show_databases()

        btns = ttk.Frame(f)
        btns.pack(anchor="w", pady=10)
        ui.Button(btns, "Buka", "open", open_selected, kind="primary").pack(side="left")
        ui.Button(btns, "Hapus dari daftar", "delete", remove).pack(side="left", padx=8)
        tree.bind("<Return>", open_selected)
        tree.bind("<Double-1>", open_selected)

        ttk.Label(f, text="Tambah Database", style="H2.TLabel").pack(anchor="w", pady=(24, 8))
        form = ttk.Frame(f)
        form.pack(anchor="w")
        alias, path = ttk.Entry(form, width=20), ttk.Entry(form, width=56)
        for label, w in [("Alias", alias), ("Lokasi File", path)]:
            ttk.Label(form, text=label).pack(side="left", padx=(0, 6))
            w.pack(side="left", padx=(0, 12))

        def browse():
            p = filedialog.asksaveasfilename(title="Pilih file database lama atau nama file baru",
                                             defaultextension=".rptdb", confirmoverwrite=False,
                                             filetypes=[("Database", "*.rptdb")])
            if p:
                path.delete(0, "end")
                path.insert(0, p)

        def add():
            a, p = alias.get().strip(), path.get().strip()
            if not a or not p:
                return messagebox.showerror("Gagal", "Alias dan lokasi file wajib diisi")
            if a in dbs:
                return messagebox.showerror("Gagal", "Alias sudah dipakai")
            dbs[a] = os.path.abspath(p)
            save_config(cfg)
            self.open_db(cfg, a)

        ui.Button(form, "Browse", "folder", browse).pack(side="left")
        ui.Button(form, "Simpan & Buka", "save", add, kind="primary").pack(side="left", padx=8)

    def open_db(self, cfg, alias):
        path = cfg["databases"][alias]
        if not os.path.exists(path):
            if not os.path.isdir(os.path.dirname(path)):
                return messagebox.showerror("Gagal", f"Folder tidak ditemukan:\n{os.path.dirname(path)}")
            if not messagebox.askyesno("Database baru", f"File belum ada. Buat database baru di:\n{path}?"):
                return
        cfg["last"] = alias
        save_config(cfg)
        self.store, self.alias = Store(path), alias
        self.show_login()

    def form(self, title, fields, submit_text, submit_icon, on_submit):
        box = self.card()
        ttk.Label(box, text=title, style="Title.TLabel").grid(columnspan=2)
        ttk.Label(box, text=f"Database: {self.alias}", style="Muted.TLabel").grid(columnspan=2)
        try:
            file, when = self.store.info()
        except ValueError:
            file = when = None
        info = f"{file} (diimpor {when})" if file else "-"
        ttk.Label(box, text=f"File yg digunakan: {info}", style="Muted.TLabel").grid(columnspan=2, pady=(0, 20))
        entries = []
        for label, show in fields:
            ttk.Label(box, text=label).grid(column=0, sticky="w", pady=5, padx=(0, 12))
            e = ttk.Entry(box, show=show, width=30)
            e.grid(row=len(entries) + 3, column=1, pady=5)
            entries.append(e)
        err = ttk.Label(box, style="Error.TLabel")
        err.grid(columnspan=2, pady=8)

        def go(_=None):
            msg = on_submit(*[e.get() for e in entries])
            if msg and err.winfo_exists():
                err.config(text=msg)

        ui.Button(box, submit_text, submit_icon, go, kind="primary").grid(columnspan=2, sticky="ew")
        cfg = load_config()
        auto = tk.BooleanVar(value=cfg.get("auto_open", True))

        def save_auto():
            cfg["auto_open"] = auto.get()
            save_config(cfg)

        ttk.Checkbutton(box, text="Langsung buka database ini saat aplikasi dibuka", variable=auto,
                        command=save_auto).grid(columnspan=2, pady=(16, 0))
        ui.Button(box, "Ganti Database", "switch", self.show_databases).grid(columnspan=2, pady=(10, 0))
        for e in entries:
            e.bind("<Return>", go)
        entries[0].focus_set()

    def show_login(self):
        if not self.store.exists():
            return self.form("Buat Akun Admin",
                             [("Username", ""), ("Password", "*"), ("Ulangi Password", "*")],
                             "Buat", "add", self.do_setup)
        self.form("Login", [("Username", ""), ("Password", "*")], "Masuk", "login", self.do_login)

    def do_setup(self, user, pw, pw2):
        user = user.strip()
        if not user or not pw:
            return "Username dan password wajib diisi"
        if pw != pw2:
            return "Password tidak sama"
        try:
            self.store.setup(user, pw)
        except (OSError, ValueError) as e:
            return f"Gagal membuat database: {error_text(e)}"
        return self.do_login(user, pw)

    def do_login(self, user, pw):
        try:
            perms = self.store.login(user.strip(), pw)
        except Exception:
            return "Database rusak atau tidak valid"
        if not perms:
            return "Username atau password salah"
        self.updated.set("")
        self.route()

    # ----- pages -----

    def scan_page(self, page, title, on_scan, extra=None):
        f = self.clear(page)
        ttk.Label(f, text=title, style="H2.TLabel").pack(anchor="w")
        if extra:
            extra(f)
        entry = ttk.Entry(f, font=(ui.FONT, 18), justify="center")
        entry.pack(fill="x", pady=12)
        entry.focus_set()

        def scan(_=None):
            code = entry.get().strip()
            entry.delete(0, "end")
            if code:
                on_scan(code, self.store.lookup(code))
            entry.focus_set()

        entry.bind("<Return>", scan)
        return f

    def show_scanner(self):
        name = tk.StringVar(value="Silakan scan barcode")
        price, code = tk.StringVar(), tk.StringVar()
        name_font, price_font = tkfont.Font(family=ui.FONT, weight="bold"), tkfont.Font(family=ui.FONT, weight="bold")
        code_font = tkfont.Font(family=ui.FONT)

        def fit(_=None):
            """Scale text and barcode to the space left under the scan box."""
            W, H = info.winfo_width(), info.winfo_height()
            if W < 50 or H < 50:
                return
            # ponytail: ~0.6em per char estimate, good enough for Segoe UI; name may wrap to 2 lines
            name_font.configure(size=-int(min(H * 0.15, 2 * W / (max(len(name.get()), 1) * 0.6))))
            price_font.configure(size=-int(min(H * 0.25, W / (max(len(price.get()), 1) * 0.62))))
            code_font.configure(size=-int(H * 0.06))
            name_lbl.configure(wraplength=W)
            cw, ch = int(W * 0.7), int(H * 0.2)
            bars.configure(width=cw, height=ch)
            bars.delete("all")
            if not price.get():
                return
            modules = Code128(code.get()).build()[0]
            w = max(1, cw // len(modules))
            x = (cw - w * len(modules)) // 2
            for i, m in enumerate(modules):
                if m == "1":
                    bars.create_rectangle(x + i * w, 0, x + (i + 1) * w, ch, fill="black", width=0)

        def on_scan(barcode, item):
            if item:
                name.set(item[0]), price.set(rupiah(item[1])), code.set(barcode)
            else:
                name.set("Barang tidak ditemukan"), price.set(""), code.set(barcode)
            fit()

        f = self.scan_page("scanner", "Cek Harga", on_scan)
        info = ttk.Frame(f)
        info.pack(fill="both", expand=True)
        info.pack_propagate(False)  # children resize to the frame, not the other way round
        info.bind("<Configure>", fit)
        name_lbl = ttk.Label(info, textvariable=name, font=name_font, justify="center")
        name_lbl.pack(expand=True)
        ttk.Label(info, textvariable=price, font=price_font, foreground=ui.RED).pack(expand=True)
        bars = tk.Canvas(info, bg="white", highlightthickness=0)
        bars.pack()
        ttk.Label(info, textvariable=code, font=code_font).pack(expand=True)

    def show_printer(self):
        cfg = load_config()
        printer = tk.StringVar(value=cfg.get("printer") or default_printer())
        status = tk.StringVar(value="Silakan scan barcode untuk mencetak")

        def save(_=None):
            cfg["printer"] = printer.get()
            save_config(cfg)

        def pick(f):
            row = ttk.Frame(f)
            row.pack(anchor="w", pady=(10, 0))
            ttk.Label(row, text="Printer").pack(side="left")
            cb = ttk.Combobox(row, textvariable=printer, values=list_printers(), state="readonly", width=40)
            cb.pack(side="left", padx=8)
            cb.bind("<<ComboboxSelected>>", save)

        def on_scan(barcode, item):
            if not item:
                preview.configure(image="")
                return status.set(f"Barang tidak ditemukan: {barcode}")
            img = render_label(item[0], item[1], barcode)
            preview.image = ImageTk.PhotoImage(img)  # keep a reference or Tk drops it
            preview.configure(image=preview.image)
            try:
                print_label(printer.get(), label_bytes(img))
                status.set(f"Tercetak: {item[0]}")
            except Exception as e:
                status.set(f"Gagal cetak: {e}")

        f = self.scan_page("printer", "Cetak Label Harga", on_scan, pick)
        ttk.Label(f, textvariable=status, font=(ui.FONT, 14), wraplength=820).pack(pady=(4, 12))
        preview = tk.Label(f, bg="white", padx=12, pady=12, relief="solid", borderwidth=1)
        preview.pack()

    def show_update(self):
        f = self.clear("update")
        ttk.Label(f, text="Update Daftar Barang", style="H2.TLabel").pack(anchor="w")
        ttk.Label(f, text="Kolom Excel: Nama Barang | Harga | Barcode (header opsional).\n"
                          "Impor akan MENGGANTI seluruh daftar barang lama.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 16))

        def do_import():
            path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
            if not path or not messagebox.askyesno("Konfirmasi", "Ganti seluruh daftar barang?"):
                return
            try:
                n = self.store.import_excel(path)
            except Exception as e:
                return messagebox.showerror("Impor gagal", error_text(e))
            messagebox.showinfo("Berhasil", f"{n} barang diimpor")
            self.show_update()  # refresh footer file info + count

        ui.Button(f, "Impor Excel", "upload", do_import, kind="primary").pack(anchor="w")
        ttk.Label(f, text=f"Jumlah barang saat ini: {len(self.store.items)}",
                  font=(ui.FONT, 13)).pack(anchor="w", pady=16)

    def show_users(self):
        f = self.clear("users")
        ttk.Label(f, text="Kelola User", style="H2.TLabel").pack(anchor="w")
        tree = ttk.Treeview(f, columns=("perms",), height=9, selectmode="browse")
        tree.heading("#0", text="Username")
        tree.heading("perms", text="Akses")
        tree.column("#0", width=200)
        tree.column("perms", width=560)
        tree.pack(fill="x", pady=12)
        users = dict(self.store.list_users())
        for name, perms in users.items():
            tree.insert("", "end", iid=name, text=name, values=(", ".join(PERM_LABELS[p] for p in perms),))

        form = ttk.Frame(f)
        form.pack(anchor="w", pady=4)
        user, pw = ttk.Entry(form, width=20), ttk.Entry(form, width=20, show="*")
        for label, w in [("Username", user), ("Password", pw)]:
            ttk.Label(form, text=label).pack(side="left", padx=(0, 6))
            w.pack(side="left", padx=(0, 14))
        checks = ttk.Frame(f)
        checks.pack(anchor="w", pady=6)
        ttk.Label(checks, text="Akses").pack(side="left", padx=(0, 8))
        allowed = {p: tk.BooleanVar(value=p == "scanner") for p in PERMS}
        for p in PERMS:
            ttk.Checkbutton(checks, text=PERM_LABELS[p], variable=allowed[p]).pack(side="left", padx=(0, 10))

        def chosen():
            return [p for p in PERMS if allowed[p].get()]

        def selected():
            return tree.selection()[0] if tree.selection() else None

        def on_select(_=None):
            for p, v in allowed.items():
                v.set(p in users.get(selected(), []))

        tree.bind("<<TreeviewSelect>>", on_select)

        def act(fn, *args):
            try:
                fn(*args)
            except Exception as e:
                return messagebox.showerror("Gagal", error_text(e))
            self.show_users()

        def delete():
            name = selected()
            if name and messagebox.askyesno("Konfirmasi", f"Hapus user {name}?"):
                act(self.store.delete_user, name)

        btns = ttk.Frame(f)
        btns.pack(anchor="w", pady=10)
        ui.Button(btns, "Tambah User", "adduser", lambda: act(
            self.store.add_user, user.get().strip(), pw.get(), chosen()), kind="primary").pack(side="left")
        ui.Button(btns, "Simpan Akses", "save",
                  lambda: selected() and act(self.store.set_perms, selected(), chosen())).pack(side="left", padx=8)
        ui.Button(btns, "Hapus User", "delete", delete).pack(side="left")
        ttk.Label(f, text="Pilih user di tabel untuk mengubah akses atau menghapusnya.",
                  style="Muted.TLabel").pack(anchor="w")


if __name__ == "__main__":
    App().mainloop()
