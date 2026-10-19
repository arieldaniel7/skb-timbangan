"""Pindahkan folder data / folder skrip Lua ke lokasi lain, sehingga aplikasi dan datanya boleh berbeda folder.
Perubahan berlaku setelah aplikasi dimulai ulang (disimpan di scaler.ini)."""
import os
import shutil

from app import paths
from app.errors import UserError
from app.authentication.session import require
from app.services import audit, backup


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _inside(child, parent):
    try:
        return os.path.commonpath([os.path.abspath(child), os.path.abspath(parent)]) == os.path.abspath(parent)
    except ValueError:        # beda drive di Windows
        return False


def move_data_home(new_home):
    """Salin database (konsisten, via API backup SQLite) + skrip Lua + aset ke folder baru, lalu catat di scaler.ini."""
    require("settings")
    new_home = os.path.abspath(new_home)
    if _same(new_home, paths.BASE):
        raise UserError("Folder tujuan sama dengan folder data saat ini.")
    target_db = os.path.join(new_home, "data", "scaler.db")
    if os.path.exists(target_db):
        raise UserError("Folder tujuan sudah berisi database Scaler. Pilih folder yang kosong.")
    try:
        os.makedirs(os.path.dirname(target_db), exist_ok=True)
        backup.backup_to(target_db)
        for src, name in ((paths.LUA_DIR, "lua"), (paths.ASSETS_DIR, "assets")):
            if os.path.isdir(src) and _inside(src, paths.BASE):
                shutil.copytree(src, os.path.join(new_home, name), dirs_exist_ok=True)
    except OSError as exc:
        raise UserError("Gagal menyalin data ke folder tujuan: %s" % exc)
    ini = paths.save_ini(home=new_home)
    audit.log("PINDAH FOLDER DATA", "settings", None, paths.BASE, new_home)
    return ini


def set_lua_dir(new_dir):
    """Pakai folder terpisah untuk skrip Lua (template tiket & aturan). Skrip yang ada ikut disalin."""
    require("settings")
    new_dir = os.path.abspath(new_dir)
    if _same(new_dir, paths.LUA_DIR):
        raise UserError("Folder tujuan sama dengan folder skrip saat ini.")
    try:
        os.makedirs(new_dir, exist_ok=True)
        if os.path.isdir(paths.LUA_DIR):
            shutil.copytree(paths.LUA_DIR, new_dir, dirs_exist_ok=True)
    except OSError as exc:
        raise UserError("Gagal menyiapkan folder skrip: %s" % exc)
    ini = paths.save_ini(lua_dir=new_dir)
    audit.log("UBAH FOLDER SKRIP LUA", "settings", None, paths.LUA_DIR, new_dir)
    return ini
