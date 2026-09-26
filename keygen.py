"""Developer tool: makes activation codes. Keep the private key safe and backed up.
The key is never bundled; the exe reads it from the developer's own laptop.

  (double-click / no args)               # GUI
  python keygen.py init                  # once: create private key, print public key for licensing.py
  python keygen.py XXXX-XXXX-XXXX-XXXX   # activation code for that Device ID
"""
import os
import re
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import licensing

KEY_FILE = os.path.join(os.path.expanduser("~"), ".rptm", "license_private.key")


def load_key(path):
    """Private key from file; refuses keys that don't match the app's PUBLIC_KEY."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        key = Ed25519PrivateKey.from_private_bytes(raw)
    except ValueError:
        raise ValueError("Bukan file kunci lisensi") from None
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if pub.hex() != licensing.PUBLIC_KEY:
        raise ValueError("Kunci ini tidak cocok dengan aplikasi")
    return key


def make_code(key, device):
    device = device.strip().upper().replace(" ", "")
    if re.fullmatch(r"[A-Z2-7]{16}", device):
        device = "-".join(device[i:i + 4] for i in range(0, 16, 4))
    if not re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", device):
        raise ValueError("Format Device ID harus XXXX-XXXX-XXXX-XXXX")
    code = licensing.format_code(key.sign(device.encode()))
    if not licensing.verify(code, device):
        raise ValueError("Kunci ini tidak cocok dengan aplikasi")
    return code


def save_key(raw):
    os.makedirs(os.path.dirname(KEY_FILE), mode=0o700, exist_ok=True)
    with open(os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(raw)


def init():
    if os.path.exists(KEY_FILE):
        sys.exit(f"Key already exists: {KEY_FILE}")
    key = Ed25519PrivateKey.generate()
    save_key(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                               serialization.NoEncryption()))
    print(f"Private key saved: {KEY_FILE}  (BACK IT UP)")
    print("PUBLIC_KEY =", key.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw).hex())


def gui():
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("Retail Price Tag License Generator")
    f = ttk.Frame(root, padding=20)
    f.pack(fill="both", expand=True)
    key_status, msg = tk.StringVar(), tk.StringVar()
    state = {"key": None}

    def refresh():
        try:
            state["key"] = load_key(KEY_FILE)
            key_status.set(f"Kunci: {KEY_FILE}")
            pick.pack_forget()
        except OSError:
            key_status.set("Kunci lisensi belum dipilih")
        except ValueError as e:
            key_status.set(f"Kunci di {KEY_FILE} tidak valid: {e}")

    def choose():
        path = filedialog.askopenfilename(title="Pilih file license_private.key")
        if not path:
            return
        try:
            load_key(path)
            with open(path, "rb") as src:
                save_key(src.read())
        except (OSError, ValueError) as e:
            return msg.set(f"Gagal: {e}")
        msg.set("")
        refresh()

    def generate(_=None):
        out.configure(state="normal")
        out.delete("1.0", "end")
        if not state["key"]:
            msg.set("Pilih file kunci dulu")
        else:
            try:
                out.insert("1.0", make_code(state["key"], device.get()))
                msg.set("")
            except ValueError as e:
                msg.set(str(e))
        out.configure(state="disabled")

    def copy():
        root.clipboard_clear()
        root.clipboard_append(out.get("1.0", "end").strip())

    ttk.Label(f, text="License Generator", font=("Segoe UI", 18, "bold")).pack()
    ttk.Label(f, textvariable=key_status).pack(pady=(6, 0))
    pick = ttk.Button(f, text="Pilih file kunci...", command=choose)
    pick.pack(pady=4)
    ttk.Label(f, text="Device ID").pack(pady=(16, 4))
    device = ttk.Entry(f, font=("Segoe UI", 14), justify="center", width=24)
    device.pack()
    device.bind("<Return>", generate)
    device.focus_set()
    ttk.Button(f, text="Buat Kode", command=generate).pack(pady=8)
    ttk.Label(f, textvariable=msg, foreground="red").pack()
    out = tk.Text(f, width=60, height=3, wrap="char", state="disabled")
    out.pack(pady=4)
    ttk.Button(f, text="Salin", command=copy).pack()
    refresh()
    return root


if __name__ == "__main__":
    if len(sys.argv) == 1:
        gui().mainloop()
    elif sys.argv[1] == "init":
        init()
    else:
        print(make_code(load_key(KEY_FILE), sys.argv[1]))
