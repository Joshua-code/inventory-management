"""App updates from the folder that holds the database (shared via Google Drive).

HQ drops `Retail Price Tag Management Setup X.Y.Z.exe` + `update.json` there. The manifest is
signed with the developer's private key (the one that makes licenses), and the app only runs a
Setup whose version is newer and whose SHA-256 matches the signed manifest. No GUI here.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import tempfile

import licensing

MANIFEST = "update.json"
MAX_BYTES = 200 * 1024 * 1024


def parse_version(text):
    if not re.fullmatch(r"\d+(\.\d+){1,3}", str(text)):
        raise ValueError(f"Versi tidak valid: {text}")
    return tuple(int(p) for p in text.split("."))


def message(version, sha256):
    # prefix keeps update signatures and license codes (which sign a Device ID) from being interchangeable
    return f"rptm-update|{version}|{sha256}".encode()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(key, setup_path):
    """Developer side: sign `setup_path` and write update.json next to it. Returns the manifest path."""
    name = os.path.basename(setup_path)
    m = re.search(r"(\d+\.\d+\.\d+)\.exe$", name)
    if not m:
        raise ValueError("Nama file harus berakhir dengan nomor versi, contoh: ... Setup 1.1.0.exe")
    version, digest = m.group(1), sha256_file(setup_path)
    sig = licensing.format_code(key.sign(message(version, digest)))
    out = os.path.join(os.path.dirname(setup_path), MANIFEST)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"version": version, "file": name, "sha256": digest, "sig": sig}, f, indent=1)
    return out


def check(folder, current):
    """The update waiting in `folder`, or None. Anything unsigned, malformed or not newer is ignored."""
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            info = json.load(f)
        version, name, digest, sig = info["version"], info["file"], info["sha256"], info["sig"]
        if not (isinstance(name, str) and name == os.path.basename(name) and name.lower().endswith(".exe")):
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        if parse_version(version) <= parse_version(current):
            return None
        if not licensing.verify_sig(sig, message(version, digest)):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"version": version, "file": name, "sha256": digest}


def prepare(info, folder):
    """Copy the Setup to a private temp folder and verify it there (so it can't be swapped afterwards)."""
    src = os.path.join(folder, info["file"])
    if not os.path.isfile(src):
        raise ValueError("File update tidak ditemukan di folder database")
    if os.path.getsize(src) > MAX_BYTES:
        raise ValueError("File update terlalu besar")
    for old in glob.glob(os.path.join(tempfile.gettempdir(), "rptm-update-*")):
        shutil.rmtree(old, ignore_errors=True)  # leftovers of earlier updates
    tmp = tempfile.mkdtemp(prefix="rptm-update-")
    dst = os.path.join(tmp, info["file"])
    shutil.copyfile(src, dst)
    if sha256_file(dst) != info["sha256"]:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("File update belum lengkap atau tidak cocok (mungkin Google Drive masih "
                         "menyinkronkan). Coba lagi sebentar lagi.")
    return dst


def install_cmd(path):
    """Silent in-place upgrade; /RELAUNCH=1 makes the installer reopen the app afterwards."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]
