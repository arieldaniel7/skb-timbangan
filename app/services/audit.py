import datetime
import platform

from app import log as applog
from app import util
from app.database import db
from app.authentication.session import current_username, require

logger = applog.get(__name__)


def log(action, table=None, record_id=None, old=None, new=None):
    """Catat ke audit_logs. Tidak pernah melempar error ke pemanggil."""
    try:
        db.execute("INSERT INTO audit_logs(ts, username, action, tbl, record_id, old_value, new_value, computer) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (util.now_str(), current_username(), action, table,
                    None if record_id is None else str(record_id), old, new, platform.node()))
    except Exception:
        logger.exception("Gagal menulis audit log")


def search(date_from, date_to, text="", limit=1000):
    require("audit")
    like = "%" + text.strip() + "%"
    return db.query("SELECT ts, username, action, tbl, record_id, old_value, new_value, computer FROM audit_logs "
                    "WHERE ts>=? AND ts<? AND (action LIKE ? OR username LIKE ? OR new_value LIKE ? OR old_value LIKE ?) "
                    "ORDER BY id DESC LIMIT ?",
                    (util.day_str(date_from), util.day_str(date_to + datetime.timedelta(days=1)),
                     like, like, like, like, limit))
