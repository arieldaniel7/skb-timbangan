"""SQLite lokal: koneksi tunggal, WAL, foreign keys, skema, dan data awal."""
import contextlib
import os
import sqlite3

from app import paths, util

_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, description TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL REFERENCES roles(name),
  active INTEGER NOT NULL DEFAULT 1, must_change INTEGER NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, address TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS suppliers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, address TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS materials(
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, category TEXT, unit TEXT,
  description TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS trucks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL UNIQUE, plate_display TEXT NOT NULL, truck_code TEXT,
  truck_type TEXT, driver TEXT, notes TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, trx_number TEXT NOT NULL UNIQUE,
  truck_id INTEGER NOT NULL REFERENCES trucks(id), customer_id INTEGER NOT NULL REFERENCES customers(id),
  supplier_id INTEGER REFERENCES suppliers(id), material_id INTEGER NOT NULL REFERENCES materials(id),
  destination TEXT, driver_name TEXT, volume_m3 REAL,
  first_weight INTEGER CHECK (first_weight IS NULL OR first_weight > 0), first_weight_time TEXT,
  second_weight INTEGER CHECK (second_weight IS NULL OR second_weight > 0), second_weight_time TEXT,
  gross_weight INTEGER, tare_weight INTEGER, net_weight INTEGER CHECK (net_weight IS NULL OR net_weight >= 0),
  status TEXT NOT NULL CHECK (status IN ('OPEN','WAITING_SECOND_WEIGHT','COMPLETED','VOID','CANCELLED')),
  operator_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL, completed_at TEXT, notes TEXT,
  print_count INTEGER NOT NULL DEFAULT 0, void_reason TEXT, voided_by TEXT, voided_at TEXT);
CREATE TABLE IF NOT EXISTS transaction_weights(
  id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id INTEGER NOT NULL REFERENCES transactions(id),
  seq INTEGER NOT NULL, weight INTEGER NOT NULL, taken_at TEXT NOT NULL, operator_id INTEGER REFERENCES users(id),
  UNIQUE(transaction_id, seq));
CREATE TABLE IF NOT EXISTS print_templates(name TEXT PRIMARY KEY, content TEXT NOT NULL, layout_json TEXT, updated_at TEXT, updated_by TEXT);
CREATE TABLE IF NOT EXISTS print_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id INTEGER NOT NULL REFERENCES transactions(id),
  ts TEXT NOT NULL, username TEXT, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT, action TEXT NOT NULL, tbl TEXT,
  record_id TEXT, old_value TEXT, new_value TEXT, computer TEXT);
CREATE INDEX IF NOT EXISTS ix_trx_created ON transactions(created_at);
CREATE INDEX IF NOT EXISTS ix_trx_completed ON transactions(completed_at);
CREATE INDEX IF NOT EXISTS ix_trx_truck_status ON transactions(truck_id, status);
CREATE INDEX IF NOT EXISTS ix_trx_customer ON transactions(customer_id);
CREATE INDEX IF NOT EXISTS ix_trx_material ON transactions(material_id);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_logs(ts);
"""


def conn():
    global _conn
    if _conn is None:
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        c = sqlite3.connect(paths.DB_PATH, isolation_level=None)  # autocommit; transaksi eksplisit
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _conn = c
    return _conn


def close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        finally:
            _conn = None


def query(sql, params=()):
    return conn().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return conn().execute(sql, params).fetchone()


def scalar(sql, params=()):
    row = conn().execute(sql, params).fetchone()
    return row[0] if row is not None else None


def execute(sql, params=()):
    return conn().execute(sql, params)


@contextlib.contextmanager
def transaction():
    """Transaksi atomik (BEGIN IMMEDIATE). Jangan di-nest."""
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def init():
    """Buat skema, cek integritas, isi data awal bila database baru."""
    from app.errors import UserError
    conn().executescript(SCHEMA)
    _migrate()
    ok = scalar("PRAGMA integrity_check")
    if ok != "ok":
        raise UserError("Pemeriksaan integritas database gagal. Pulihkan dari backup (folder backups).")
    _seed()
    from app.printing import ticket
    ticket.ensure_template()


def columns(table):
    return set(r[1] for r in query("PRAGMA table_info(%s)" % table))


def _migrate():
    """Upgrade database dari versi sebelumnya (kolom lama dibiarkan, tidak dihapus)."""
    if "truck_code" not in columns("trucks"):
        execute("ALTER TABLE trucks ADD COLUMN truck_code TEXT")
    if "layout_json" not in columns("print_templates"):
        execute("ALTER TABLE print_templates ADD COLUMN layout_json TEXT")
    execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_trucks_code ON trucks(truck_code) WHERE truck_code IS NOT NULL")


def _seed():
    from app.authentication.auth import hash_password
    now = util.now_str()
    for name, desc in (("ADMIN", "Administrator"), ("SUPERVISOR", "Supervisor"), ("OPERATOR", "Operator timbangan")):
        execute("INSERT OR IGNORE INTO roles(name, description) VALUES(?,?)", (name, desc))
    if scalar("SELECT COUNT(*) FROM users") == 0:
        for username, full, role, pw in (("admin", "Administrator", "ADMIN", "admin123"),
                                         ("supervisor", "Supervisor", "SUPERVISOR", "supervisor123"),
                                         ("operator", "Operator 1", "OPERATOR", "operator123")):
            execute("INSERT INTO users(username, full_name, password_hash, role, active, must_change, created_at) "
                    "VALUES(?,?,?,?,1,1,?)", (username, full, hash_password(pw), role, now))
        for grade in ("K-175", "K-225", "K-250", "K-300", "K-350"):
            execute("INSERT OR IGNORE INTO materials(code, name, category, unit, active, created_at) "
                    "VALUES(?,?,?,?,1,?)", (grade, "Beton " + grade, "Beton Ready Mix", "m3", now))
        execute("INSERT OR IGNORE INTO customers(code, name, active, created_at) VALUES('C001','PT Contoh Konstruksi',1,?)", (now,))
        execute("INSERT OR IGNORE INTO trucks(plate, plate_display, truck_code, truck_type, active, created_at) "
                "VALUES('AE1234XY','AE 1234 XY','TM-001','Truk Mixer',1,?)", (now,))
    if scalar("SELECT COUNT(*) FROM settings") == 0:
        for k, v in (("company_name", "NAMA PERUSAHAAN BATCHING PLANT"), ("company_address", "Alamat perusahaan"),
                     ("company_phone", "")):
            execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, v))
