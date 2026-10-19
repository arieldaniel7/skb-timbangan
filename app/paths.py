"""Lokasi folder aplikasi - tidak bergantung pada current working directory.

Folder data ("home": database, backup, log, skrip Lua, aset) ditentukan dengan prioritas:
    argumen --home  >  env SCALER_HOME  >  scaler.ini  >  folder aplikasi (jika bisa ditulis) / %LOCALAPPDATA%\\Scaler
Folder skrip Lua boleh dipisah: --lua-dir  >  env SCALER_LUA_DIR  >  scaler.ini [paths] lua_dir.
Skrip bawaan dibundel bersama aplikasi (RESOURCE_DIR/lua) dan disalin ke folder Lua saat pertama kali jalan,
sehingga kode sumber/aplikasi dan skrip yang bisa diubah pengguna dapat berada di folder berbeda."""
import argparse
import configparser
import os
import shutil
import sys

APP_DIR = RESOURCE_DIR = ""
BASE = DATA_DIR = DB_PATH = BACKUP_DIR = LOG_DIR = LUA_DIR = ASSETS_DIR = INI_PATH = ""


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir():
    return getattr(sys, "_MEIPASS", None) or _app_dir()


def _user_dir():
    root = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
            or os.path.join(os.path.expanduser("~"), ".local", "share"))
    return os.path.join(root, "Scaler")


def _writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_test")
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def configure(base=None, lua_dir=None, data_dir=None, backup_dir=None, log_dir=None, ini_path=""):
    """Tetapkan semua path. Dipakai oleh resolve() dan oleh tes."""
    global APP_DIR, RESOURCE_DIR, BASE, DATA_DIR, DB_PATH, BACKUP_DIR, LOG_DIR, LUA_DIR, ASSETS_DIR, INI_PATH
    APP_DIR = _app_dir()
    RESOURCE_DIR = _resource_dir()
    BASE = os.path.abspath(base) if base else APP_DIR
    DATA_DIR = os.path.abspath(data_dir) if data_dir else os.path.join(BASE, "data")
    DB_PATH = os.path.join(DATA_DIR, "scaler.db")
    BACKUP_DIR = os.path.abspath(backup_dir) if backup_dir else os.path.join(BASE, "backups")
    LOG_DIR = os.path.abspath(log_dir) if log_dir else os.path.join(BASE, "logs")
    LUA_DIR = os.path.abspath(lua_dir) if lua_dir else os.path.join(BASE, "lua")
    ASSETS_DIR = os.path.join(BASE, "assets")
    INI_PATH = ini_path or ""


# ---- scaler.ini ------------------------------------------------------------------------
def _ini_candidates():
    return [os.path.join(_app_dir(), "scaler.ini"), os.path.join(_user_dir(), "scaler.ini")]


def read_ini(path=None):
    """-> (dict nilai [paths], file yang dibaca atau None)."""
    for candidate in ([path] if path else _ini_candidates()):
        if candidate and os.path.isfile(candidate):
            cp = configparser.ConfigParser()
            try:
                cp.read(candidate, encoding="utf-8")
            except configparser.Error:
                return {}, candidate
            return (dict(cp["paths"]) if cp.has_section("paths") else {}), candidate
    return {}, None


def save_ini(**values):
    """Simpan nilai folder ke scaler.ini (None = hapus kunci). Mengembalikan file yang ditulis."""
    current, found = read_ini(INI_PATH or None)
    merged = dict(current)
    for key, value in values.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    targets = [INI_PATH] if INI_PATH else []
    targets += [found] if found else []
    targets += _ini_candidates()
    for target in targets:
        if not target:
            continue
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            cp = configparser.ConfigParser()
            cp["paths"] = merged
            with open(target, "w", encoding="utf-8") as fh:
                cp.write(fh)
            return target
        except OSError:
            continue
    raise OSError("Tidak dapat menulis scaler.ini")


def resolve(argv=None, environ=None):
    """Tentukan semua folder dari argumen/env/ini. Mengembalikan argumen sisa (untuk Qt)."""
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--home")
    parser.add_argument("--lua-dir")
    parser.add_argument("--config")
    args, rest = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    cfg = args.config or env.get("SCALER_CONFIG")
    ini, ini_file = read_ini(cfg)
    home = args.home or env.get("SCALER_HOME") or ini.get("home")
    if not home:
        home = _app_dir() if _writable(_app_dir()) else _user_dir()
    configure(home,
              lua_dir=args.lua_dir or env.get("SCALER_LUA_DIR") or ini.get("lua_dir") or None,
              data_dir=ini.get("data_dir") or None, backup_dir=ini.get("backup_dir") or None,
              ini_path=ini_file or cfg or "")
    return rest


def seed_resources():
    """Salin skrip Lua bawaan (RESOURCE_DIR/lua) ke folder Lua bila belum ada. Tidak menimpa file pengguna."""
    for folder in (DATA_DIR, LUA_DIR, ASSETS_DIR):
        os.makedirs(folder, exist_ok=True)
    src = os.path.join(RESOURCE_DIR, "lua")
    copied = []
    if not os.path.isdir(src) or os.path.abspath(src) == os.path.abspath(LUA_DIR):
        return copied
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dst_dir = LUA_DIR if rel == "." else os.path.join(LUA_DIR, rel)
        os.makedirs(dst_dir, exist_ok=True)
        for name in files:
            target = os.path.join(dst_dir, name)
            if not os.path.exists(target):
                shutil.copyfile(os.path.join(root, name), target)
                copied.append(target)
    return copied


configure()
