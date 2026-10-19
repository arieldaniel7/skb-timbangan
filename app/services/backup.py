import datetime
import os
import shutil
import sqlite3

from app import log, paths
from app.errors import UserError
from app.database import db
from app.services import settings

logger = log.get(__name__)


def backup_dir():
    return settings.get("backup_dir") or paths.BACKUP_DIR


def default_name(prefix="backup"):
    return "%s_%s.db" % (prefix, datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))


def backup_to(path):
    """Backup konsisten via API backup SQLite (aman untuk mode WAL)."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    dst = sqlite3.connect(path)
    try:
        db.conn().backup(dst)
    finally:
        dst.close()
    return path


def auto_daily():
    """Satu backup otomatis per hari saat aplikasi dibuka; simpan 30 hari terakhir."""
    try:
        if settings.get("auto_backup") != "1":
            return None
        folder = backup_dir()
        os.makedirs(folder, exist_ok=True)
        today = datetime.date.today().strftime("%Y-%m-%d")
        made = None
        if not any(f.startswith("auto_" + today) for f in os.listdir(folder)):
            made = backup_to(os.path.join(folder, default_name("auto")))
        cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
        for f in os.listdir(folder):
            full = os.path.join(folder, f)
            if f.startswith("auto_") and f.endswith(".db") and datetime.datetime.fromtimestamp(os.path.getmtime(full)) < cutoff:
                os.remove(full)
        return made
    except Exception:
        logger.exception("Backup otomatis gagal")
        return None


def validate_backup(path):
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise UserError("File backup rusak (integrity check gagal).")
            names = set(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        finally:
            c.close()
    except sqlite3.Error:
        raise UserError("File ini bukan database SQLite yang valid.")
    if not {"users", "transactions", "settings"} <= names:
        raise UserError("File ini bukan backup database Scaler.")


def restore(source):
    """Ganti database dengan file backup. Backup otomatis kondisi saat ini dibuat lebih dulu.
    Setelah ini aplikasi harus login ulang."""
    validate_backup(source)
    before = backup_to(os.path.join(backup_dir(), default_name("before_restore")))
    db.close()
    for ext in ("-wal", "-shm"):
        if os.path.exists(paths.DB_PATH + ext):
            os.remove(paths.DB_PATH + ext)
    shutil.copyfile(source, paths.DB_PATH)
    return before
