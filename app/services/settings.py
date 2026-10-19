from app.database import db

DEFAULTS = {
    "company_name": "", "company_address": "", "company_phone": "", "company_email": "", "company_tax_id": "",
    "logo_path": "",
    "scale_type": "Manual", "com_port": "COM1", "baud": "9600", "databits": "8", "parity": "None", "stopbits": "1",
    "tcp_host": "192.168.1.100", "tcp_port": "4001", "tcp_poll_cmd": "",
    "unit": "KG", "precision": "1", "density_kg_m3": "2400", "theme": "dark",
    "printer": "", "paper": "A5", "paper_w_mm": "80", "paper_h_mm": "200", "copies": "1", "margin_mm": "8",
    "auto_backup": "1", "timeout_min": "30", "backup_dir": "",
}


def get(key, default=None):
    row = db.query_one("SELECT value FROM settings WHERE key=?", (key,))
    if row is not None and row[0] is not None:
        return row[0]
    if key in DEFAULTS:
        return DEFAULTS[key]
    return "" if default is None else default


def get_int(key, default=0):
    try:
        return int(str(get(key)).strip())
    except (TypeError, ValueError):
        return default


def set(key, value):  # noqa: A001 - sengaja bernama set
    db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, str(value)))


def set_many(values):
    with db.transaction() as c:
        for k, v in values.items():
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))
