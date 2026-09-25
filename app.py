import json
import os
import struct
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from barcode import Code128
from PIL import Image, ImageDraw, ImageFont, ImageTk

from store import ROLES, Store

DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "CekHarga")
CONFIG = os.path.join(DATA_DIR, "config.json")
FONT = "Segoe UI"


def rupiah(n):
    return "Rp " + f"{n:,}".replace(",", ".")


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


def label_bytes(img, feed_mm):
    """ESC/POS raster (GS v 0) in 128-row bands, then feed past the tear bar. No cut: no cutter."""
    bw = img.convert("L").point(lambda p: 255 if p < 128 else 0, "1")  # bit 1 = black dot
    out = [b"\x1b@"]
    for top in range(0, bw.height, 128):
        band = bw.crop((0, top, LABEL_W, min(top + 128, bw.height)))
        out += [b"\x1dv0\x00", struct.pack("<HH", LABEL_W // 8, band.height), band.tobytes()]
    out.append(b"\x1bJ" + bytes([min(255, feed_mm * 8)]))
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


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


# ---------- GUI ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cek Harga")
        self.geometry("900x560")
        try:
            self.state("zoomed")  # maximized on Windows
        except tk.TclError:
            pass
        self.store = Store(DATA_DIR)
        self.body = None
        self.show_login()

    def clear(self, nav=True):
        if self.body:
            self.body.destroy()
        self.body = ttk.Frame(self, padding=20)
        self.body.pack(fill="both", expand=True)
        if nav and self.store.role:
            bar = ttk.Frame(self.body)
            bar.pack(fill="x", pady=(0, 20))
            who = ttk.Frame(bar)
            who.pack(side="left")
            ttk.Label(who, text=f"{self.store.user} ({self.store.role})").pack(anchor="w")
            ttk.Label(who, text=f"File yg digunakan: {self.store.source or '-'}").pack(anchor="w")
            ttk.Button(bar, text="Logout", command=self.logout).pack(side="right")
            if self.store.role == "admin":
                for text, cmd in [("User", self.show_users), ("Update", self.show_update),
                                  ("Printer", self.show_printer), ("Scanner", self.show_scanner)]:
                    ttk.Button(bar, text=text, command=cmd).pack(side="right", padx=4)
        return self.body

    def logout(self):
        self.store.logout()
        self.show_login()

    def form(self, title, fields, submit_text, on_submit):
        f = self.clear(nav=False)
        box = ttk.Frame(f)
        box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(box, text=title, font=(FONT, 20, "bold")).grid(columnspan=2, pady=(0, 16))
        entries = []
        for label, show in fields:
            ttk.Label(box, text=label).grid(column=0, sticky="w", pady=4)
            e = ttk.Entry(box, show=show, width=28)
            e.grid(row=len(entries) + 1, column=1, pady=4)
            entries.append(e)
        err = ttk.Label(box, foreground="red")
        err.grid(columnspan=2, pady=8)

        def go(_=None):
            msg = on_submit(*[e.get() for e in entries])
            err.config(text=msg or "")

        ttk.Button(box, text=submit_text, command=go).grid(columnspan=2)
        for e in entries:
            e.bind("<Return>", go)
        entries[0].focus_set()

    def show_login(self):
        if not self.store.has_users():
            return self.form("Buat Akun Admin",
                             [("Username", ""), ("Password", "*"), ("Ulangi Password", "*")],
                             "Buat", self.do_setup)
        self.form("Login", [("Username", ""), ("Password", "*")], "Login", self.do_login)

    def do_setup(self, user, pw, pw2):
        user = user.strip()
        if not user or not pw:
            return "Username dan password wajib diisi"
        if pw != pw2:
            return "Password tidak sama"
        self.store.setup(user, pw)
        self.do_login(user, pw)

    def do_login(self, user, pw):
        try:
            role = self.store.login(user.strip(), pw)
        except Exception:
            return "Database rusak atau tidak valid"
        if not role:
            return "Username atau password salah"
        {"admin": self.show_update, "scanner": self.show_scanner, "printer": self.show_printer}[role]()

    def scan_page(self, title, on_scan, extra=None):
        f = self.clear()
        ttk.Label(f, text=title, font=(FONT, 16, "bold")).pack()
        if extra:
            extra(f)
        entry = ttk.Entry(f, font=(FONT, 18), justify="center")
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
        name_font, price_font = tkfont.Font(family=FONT, weight="bold"), tkfont.Font(family=FONT, weight="bold")
        code_font = tkfont.Font(family=FONT)

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

        f = self.scan_page("Cek Harga", on_scan)
        info = ttk.Frame(f)
        info.pack(fill="both", expand=True)
        info.pack_propagate(False)  # children resize to the frame, not the other way round
        info.bind("<Configure>", fit)
        name_lbl = ttk.Label(info, textvariable=name, font=name_font, justify="center")
        name_lbl.pack(expand=True)
        ttk.Label(info, textvariable=price, font=price_font, foreground="#0a6").pack(expand=True)
        bars = tk.Canvas(info, bg="white", highlightthickness=0)
        bars.pack()
        ttk.Label(info, textvariable=code, font=code_font).pack(expand=True)

    def show_printer(self):
        cfg = load_config()
        printer = tk.StringVar(value=cfg.get("printer") or default_printer())
        feed = tk.StringVar(value=str(cfg.get("feed_mm", 12)))
        status = tk.StringVar(value="Silakan scan barcode untuk mencetak")

        def feed_mm():
            try:
                return max(0, min(30, int(feed.get())))
            except ValueError:
                return 12

        def save(*_):
            cfg.update(printer=printer.get(), feed_mm=feed_mm())
            save_config(cfg)

        def pick(f):
            row = ttk.Frame(f)
            row.pack(pady=8)
            ttk.Label(row, text="Printer:").pack(side="left")
            cb = ttk.Combobox(row, textvariable=printer, values=list_printers(), state="readonly", width=40)
            cb.pack(side="left", padx=6)
            cb.bind("<<ComboboxSelected>>", save)
            # ponytail: calibration knob, tear-bar distance differs per printer model
            ttk.Label(row, text="Jarak bawah (mm):").pack(side="left", padx=(16, 0))
            sp = ttk.Spinbox(row, textvariable=feed, from_=0, to=30, width=4, command=save)
            sp.pack(side="left", padx=6)
            sp.bind("<FocusOut>", save)

        def on_scan(barcode, item):
            if not item:
                preview.configure(image="")
                return status.set(f"Barang tidak ditemukan: {barcode}")
            img = render_label(item[0], item[1], barcode)
            preview.image = ImageTk.PhotoImage(img)  # keep a reference or Tk drops it
            preview.configure(image=preview.image)
            try:
                print_label(printer.get(), label_bytes(img, feed_mm()))
                status.set(f"Tercetak: {item[0]}")
            except Exception as e:
                status.set(f"Gagal cetak: {e}")

        f = self.scan_page("Cetak Label Harga", on_scan, pick)
        ttk.Label(f, textvariable=status, font=(FONT, 16), wraplength=820).pack(pady=(4, 10))
        preview = tk.Label(f, bg="white", padx=12, pady=12, relief="solid", borderwidth=1)
        preview.pack()

    def show_update(self):
        f = self.clear()
        ttk.Label(f, text="Update Daftar Barang", font=(FONT, 16, "bold")).pack()
        ttk.Label(f, text="Kolom Excel: Nama Barang | Harga | Barcode (header opsional)\n"
                          "Impor akan MENGGANTI seluruh daftar barang lama.", justify="center").pack(pady=10)

        def do_import():
            path = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
            if not path or not messagebox.askyesno("Konfirmasi", "Ganti seluruh daftar barang?"):
                return
            try:
                n = self.store.import_excel(path)
            except Exception as e:
                return messagebox.showerror("Impor gagal", str(e))
            messagebox.showinfo("Berhasil", f"{n} barang diimpor")
            self.show_update()  # refresh nav bar file name + count

        ttk.Button(f, text="Impor Excel...", command=do_import).pack(pady=10)
        ttk.Label(f, text=f"Jumlah barang saat ini: {len(self.store.items)}", font=(FONT, 14)).pack()

    def show_users(self):
        f = self.clear()
        ttk.Label(f, text="Kelola User", font=(FONT, 16, "bold")).pack()
        tree = ttk.Treeview(f, columns=("role",), height=10)
        tree.heading("#0", text="Username")
        tree.heading("role", text="Role")
        tree.pack(fill="x", pady=10)
        for name, role in self.store.list_users():
            tree.insert("", "end", iid=name, text=name, values=(role,))

        form = ttk.Frame(f)
        form.pack(pady=6)
        user, pw = ttk.Entry(form, width=18), ttk.Entry(form, width=18, show="*")
        role = ttk.Combobox(form, values=ROLES, state="readonly", width=10)
        role.set("scanner")
        for label, w in [("Username", user), ("Password", pw), ("Role", role)]:
            ttk.Label(form, text=label).pack(side="left", padx=(8, 2))
            w.pack(side="left")

        def act(fn, *args):
            try:
                fn(*args)
            except Exception as e:
                return messagebox.showerror("Gagal", str(e))
            self.show_users()

        ttk.Button(form, text="Tambah", command=lambda: act(
            self.store.add_user, user.get().strip(), pw.get(), role.get())).pack(side="left", padx=8)
        ttk.Button(f, text="Hapus user terpilih", command=lambda: tree.selection() and messagebox.askyesno(
            "Konfirmasi", f"Hapus {tree.selection()[0]}?") and act(self.store.delete_user, tree.selection()[0])).pack()


if __name__ == "__main__":
    App().mainloop()
