"""Shared look for both exes: palette, ttk theme, icon buttons, header and footer.
No Pillow here, so the License Generator stays small."""
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

VERSION = "1.0.0"
FONT = "Segoe UI"
ICON_FONT = "Segoe MDL2 Assets"  # built into Windows 10/11; buttons fall back to text-only without it
RED, RED_DARK = "#D6232A", "#A8181E"
BG, SIDE, BORDER, TEXT, MUTED = "#FFFFFF", "#F5F6F8", "#E3E5E8", "#1F2937", "#6B7280"

ICONS = {
    "search": "", "print": "", "upload": "", "people": "",
    "add": "", "adduser": "", "delete": "", "save": "",
    "copy": "", "folder": "", "open": "", "switch": "",
    "login": "", "logout": "", "key": "",
}


def asset(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def setup(root, title, ico):
    root.title(f"{title} v{VERSION}")
    root.configure(bg=BG)
    try:
        root.iconbitmap(default=asset(ico))
    except tk.TclError:
        pass  # .ico window icons are Windows-only
    root.has_icons = ICON_FONT in tkfont.families(root)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=(FONT, 10), bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, focuscolor=RED)
    s.configure("TEntry", padding=7, fieldbackground="white")
    s.map("TEntry", bordercolor=[("focus", RED)], lightcolor=[("focus", RED)])
    s.configure("TCombobox", padding=6, fieldbackground="white", arrowsize=14)
    s.configure("TCheckbutton", padding=4, indicatorbackground="white", indicatorforeground="white")
    s.map("TCheckbutton", indicatorbackground=[("selected", RED)], background=[("active", BG)])
    s.configure("Treeview", rowheight=30, fieldbackground="white", borderwidth=1)
    s.configure("Treeview.Heading", background=SIDE, font=(FONT, 10, "bold"), relief="flat", padding=6)
    s.map("Treeview", background=[("selected", RED)], foreground=[("selected", "white")])
    s.configure("Side.TFrame", background=SIDE)
    s.configure("Side.TLabel", background=SIDE, foreground=MUTED, font=(FONT, 9))
    s.configure("SideUser.TLabel", background=SIDE, foreground=TEXT, font=(FONT, 11, "bold"))
    s.configure("Card.TFrame", relief="solid", borderwidth=1)
    s.configure("Title.TLabel", font=(FONT, 20, "bold"))
    s.configure("H2.TLabel", font=(FONT, 16, "bold"))
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Error.TLabel", foreground=RED)


class Button(tk.Frame):
    """Flat button: icon glyph + text. kind: primary (red), normal (grey), nav / nav_on (sidebar)."""
    COLORS = {"primary": (RED, RED_DARK, "white"), "normal": ("#EEF0F3", "#E1E4E8", TEXT),
              "nav": (SIDE, "#E6E8EC", TEXT), "nav_on": (RED, RED, "white")}

    def __init__(self, parent, text, icon=None, command=None, kind="normal"):
        bg, hover, fg = self.COLORS[kind]
        super().__init__(parent, bg=bg, cursor="hand2")
        self.command = command
        parts = []
        if icon and self.winfo_toplevel().has_icons:
            parts.append(tk.Label(self, text=ICONS[icon], font=(ICON_FONT, 12), bg=bg, fg=fg))
        weight = "bold" if kind in ("primary", "nav_on") else "normal"
        parts.append(tk.Label(self, text=text, font=(FONT, 10, weight), bg=bg, fg=fg))
        for i, w in enumerate(parts):
            w.pack(side="left", padx=(14 if i == 0 else 8, 14 if i == len(parts) - 1 else 0), pady=8)
        for w in [self, *parts]:
            w.bind("<ButtonRelease-1>", lambda _: self.invoke())
            w.bind("<Enter>", lambda _: self._paint(hover))
            w.bind("<Leave>", lambda _: self._paint(bg))

    def _paint(self, color):
        for w in [self, *self.winfo_children()]:
            w.configure(bg=color)

    def invoke(self):
        if self.command:
            self.command()


def header(root, title, icon_png):
    bar = tk.Frame(root, bg=RED)
    bar.pack(side="top", fill="x")
    img = tk.PhotoImage(file=asset(icon_png))
    logo = tk.Label(bar, image=img, bg=RED)
    logo.image = img
    logo.pack(side="left", padx=(16, 10), pady=12)
    tk.Label(bar, text=title, bg=RED, fg="white", font=(FONT, 15, "bold")).pack(side="left")


def footer(root, logo_png=None):
    bar = tk.Frame(root, bg=SIDE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(bar, bg=BORDER, height=1).pack(fill="x")
    row = tk.Frame(bar, bg=SIDE)
    row.pack(fill="x", padx=16, pady=6)
    tk.Label(row, text="Dikembangkan oleh Joshua-code", bg=SIDE, fg=MUTED, font=(FONT, 9)).pack(side="left")
    tk.Label(row, text=f"© 2026 Babel Mart  ·  v{VERSION}", bg=SIDE, fg=MUTED, font=(FONT, 9)).pack(side="right")
    if logo_png:
        img = tk.PhotoImage(file=asset(logo_png))
        logo = tk.Label(row, image=img, bg=SIDE)
        logo.image = img
        logo.pack(side="right", padx=10)
