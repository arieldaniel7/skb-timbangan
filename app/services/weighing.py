"""Logika penimbangan dua tahap: WAITING_SECOND_WEIGHT -> COMPLETED (atau VOID / CANCELLED).

Aturan keras (berat > 0, net > 0, status valid, master aktif, tanpa transaksi ganda) ditegakkan di
Python; aturan bisnis tambahan yang dapat diubah ada di lua/scripts/rules.lua."""
import datetime
import os
import sqlite3

from app import log, paths, util
from app.errors import UserError
from app.database import db
from app.authentication.session import session, require
from app.services import audit, settings
from app.scripting import lua_engine

logger = log.get(__name__)

STATUS_OPEN = "OPEN"
STATUS_WAITING = "WAITING_SECOND_WEIGHT"
STATUS_COMPLETED = "COMPLETED"
STATUS_VOID = "VOID"
STATUS_CANCELLED = "CANCELLED"
STATUS_LABELS = {STATUS_OPEN: "TERBUKA", STATUS_WAITING: "MENUNGGU TIMBANG 2", STATUS_COMPLETED: "SELESAI",
                 STATUS_VOID: "BATAL", STATUS_CANCELLED: "DIBATALKAN"}

MAX_WEIGHT_KG = 200000

TRX_SELECT = """
SELECT t.*, k.plate_display AS plate, COALESCE(k.truck_code, '') AS truck_code,
       c.name AS customer, m.code AS material_code, m.name AS material,
       COALESCE(s.name, '') AS supplier, COALESCE(u.full_name, '') AS operator_name
FROM transactions t
JOIN trucks k ON k.id = t.truck_id
JOIN customers c ON c.id = t.customer_id
JOIN materials m ON m.id = t.material_id
LEFT JOIN suppliers s ON s.id = t.supplier_id
LEFT JOIN users u ON u.id = t.operator_id
"""


def compute(first, second):
    """Gross = berat terbesar, Tare = terkecil, Net = selisih (integer kg)."""
    gross, tare = max(first, second), min(first, second)
    return gross, tare, gross - tare


def validate_weight(weight):
    if isinstance(weight, bool) or not isinstance(weight, int):
        raise UserError("Berat tidak valid.")
    if weight <= 0:
        raise UserError("Berat harus lebih dari 0.")
    if weight > MAX_WEIGHT_KG:
        raise UserError("Berat tidak masuk akal (> %s kg). Periksa kembali." % util.format_int(MAX_WEIGHT_KG))
    return weight


def density():
    """Densitas beton kg/m3 (pengaturan) untuk mengubah netto kg -> volume m3."""
    d = settings.get_int("density_kg_m3", 2400)
    return d if d > 0 else 2400


def net_volume(net_kg):
    """Netto dalam volume (m3) = netto kg / densitas."""
    return (net_kg or 0) / float(density())


def _as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return list(x.values())
    return [x]


def _rules(func, ctx):
    """Jalankan aturan Lua. Mengembalikan (errors, warnings)."""
    path = os.path.join(paths.LUA_DIR, "scripts", "rules.lua")
    eng = lua_engine.get_engine()
    if not eng.available or not os.path.isfile(path):
        return [], []
    try:
        res = eng.call_file(path, func, ctx)
    except lua_engine.LuaError as exc:
        logger.warning("rules.lua: %s", exc)
        return [], ["Script aturan (rules.lua) bermasalah; aturan tambahan dilewati."]
    if not isinstance(res, dict):
        return [], []
    return [str(x) for x in _as_list(res.get("errors"))], [str(x) for x in _as_list(res.get("warnings"))]


def _next_number(c, now):
    day = now.strftime("%Y%m%d")
    key = "trx-" + day
    row = c.execute("SELECT value FROM counters WHERE name=?", (key,)).fetchone()
    seq = (row[0] if row else 0) + 1
    c.execute("INSERT OR REPLACE INTO counters(name, value) VALUES(?,?)", (key, seq))
    number = None
    path = os.path.join(paths.LUA_DIR, "scripts", "rules.lua")
    eng = lua_engine.get_engine()
    if eng.available and os.path.isfile(path):
        try:
            number = eng.call_file(path, "format_trx_number", day, seq)
        except lua_engine.LuaError as exc:
            logger.warning("format_trx_number: %s", exc)
    if (not isinstance(number, str) or not number.strip()
            or c.execute("SELECT 1 FROM transactions WHERE trx_number=?", (number,)).fetchone()):
        number = "TICK-%s-%04d" % (day, seq)
    return number


def get_transaction(trx_id):
    row = db.query_one(TRX_SELECT + " WHERE t.id=?", (trx_id,))
    return dict(row) if row else None


def find_open(plate_text):
    plate = util.normalize_plate(plate_text)
    if not plate:
        return None
    row = db.query_one(TRX_SELECT + " WHERE k.plate=? AND t.status=? ORDER BY t.id DESC LIMIT 1", (plate, STATUS_WAITING))
    return dict(row) if row else None


def start_first(plate, customer_id, material_id, weight, supplier_id=None, destination="", driver="",
                volume=None, notes="", create_truck=False, truck_code=""):
    require("weigh")
    weight = validate_weight(weight)
    plate_norm = util.normalize_plate(plate)
    if not plate_norm:
        raise UserError("Nomor polisi wajib diisi.")
    if not customer_id:
        raise UserError("Pelanggan wajib dipilih.")
    if not material_id:
        raise UserError("Mutu beton / material wajib dipilih.")
    if volume is not None and volume < 0:
        raise UserError("Volume tidak boleh negatif.")
    errors, warnings = _rules("validate_first", {
        "weight": weight, "plate": plate_norm, "customer_id": customer_id, "material_id": material_id,
        "destination": destination or "", "driver": driver or "", "volume": volume or 0})
    if errors:
        raise UserError("\n".join(errors))

    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as c:
        truck = c.execute("SELECT id, active FROM trucks WHERE plate=?", (plate_norm,)).fetchone()
        if truck is None:
            if not create_truck:
                raise UserError("Nomor polisi belum terdaftar.")
            try:
                c.execute("INSERT INTO trucks(plate, plate_display, truck_code, driver, active, created_at) VALUES(?,?,?,?,1,?)",
                          (plate_norm, util.format_plate(plate), (truck_code or "").strip().upper() or None,
                           driver or None, stamp))
            except sqlite3.IntegrityError:
                raise UserError("Kode truk %s sudah dipakai truk lain." % truck_code)
            truck_id = c.execute("SELECT id FROM trucks WHERE plate=?", (plate_norm,)).fetchone()[0]
        else:
            if not truck["active"]:
                raise UserError("Truk ini berstatus nonaktif. Hubungi Supervisor.")
            truck_id = truck["id"]
        if not c.execute("SELECT 1 FROM customers WHERE id=? AND active=1", (customer_id,)).fetchone():
            raise UserError("Pelanggan tidak aktif atau tidak ditemukan.")
        if not c.execute("SELECT 1 FROM materials WHERE id=? AND active=1", (material_id,)).fetchone():
            raise UserError("Material tidak aktif atau tidak ditemukan.")
        if supplier_id and not c.execute("SELECT 1 FROM suppliers WHERE id=? AND active=1", (supplier_id,)).fetchone():
            raise UserError("Supplier tidak aktif atau tidak ditemukan.")
        pending = c.execute("SELECT trx_number FROM transactions WHERE truck_id=? AND status=?",
                            (truck_id, STATUS_WAITING)).fetchone()
        if pending:
            raise UserError("Truk ini masih punya transaksi yang belum selesai (%s)." % pending[0])
        number = _next_number(c, now)
        cur = c.execute(
            "INSERT INTO transactions(trx_number, truck_id, customer_id, supplier_id, material_id, destination, driver_name,"
            " volume_m3, first_weight, first_weight_time, status, operator_id, created_at, notes)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, truck_id, customer_id, supplier_id or None, material_id, destination or None, driver or None,
             volume if volume else None, weight, stamp, STATUS_WAITING, session.user["id"], stamp, notes or None))
        trx_id = cur.lastrowid
        c.execute("INSERT INTO transaction_weights(transaction_id, seq, weight, taken_at, operator_id) VALUES(?,?,?,?,?)",
                  (trx_id, 1, weight, stamp, session.user["id"]))
    audit.log("TIMBANG PERTAMA", "transactions", trx_id, None, "%s / %s kg" % (number, weight))
    return {"id": trx_id, "number": number, "warnings": warnings}


def preview_second(trx_id, weight):
    """Hitung gross/tare/net dan jalankan aturan, tanpa menyimpan."""
    require("weigh")
    weight = validate_weight(weight)
    trx = get_transaction(trx_id)
    if trx is None:
        raise UserError("Transaksi tidak ditemukan.")
    if trx["status"] != STATUS_WAITING:
        raise UserError("Transaksi ini sudah selesai atau dibatalkan.")
    first = trx["first_weight"]
    gross, tare, net = compute(first, weight)
    if net <= 0:
        raise UserError("Berat timbangan kedua sama dengan pertama. Periksa kembali.")
    errors, warnings = _rules("validate_second", {
        "first_weight": first, "second_weight": weight, "gross": gross, "tare": tare, "net": net})
    if errors:
        raise UserError("\n".join(errors))
    return {"first_weight": first, "second_weight": weight, "gross": gross, "tare": tare, "net": net,
            "net_m3": net_volume(net), "warnings": warnings, "transaction": trx}


def complete_second(trx_id, weight):
    res = preview_second(trx_id, weight)
    stamp = util.now_str()
    with db.transaction() as c:
        cur = c.execute(
            "UPDATE transactions SET second_weight=?, second_weight_time=?, gross_weight=?, tare_weight=?, net_weight=?,"
            " status=?, completed_at=? WHERE id=? AND status=?",
            (res["second_weight"], stamp, res["gross"], res["tare"], res["net"], STATUS_COMPLETED, stamp,
             trx_id, STATUS_WAITING))
        if cur.rowcount != 1:
            raise UserError("Transaksi sudah diproses di tempat lain.")
        c.execute("INSERT INTO transaction_weights(transaction_id, seq, weight, taken_at, operator_id) VALUES(?,?,?,?,?)",
                  (trx_id, 2, res["second_weight"], stamp, session.user["id"]))
    audit.log("TIMBANG KEDUA", "transactions", trx_id, None,
              "%s / kotor %s tara %s bersih %s kg" % (res["transaction"]["trx_number"], res["gross"], res["tare"], res["net"]))
    return res


def void_transaction(trx_id, reason):
    """Transaksi SELESAI -> VOID; transaksi yang masih menunggu timbangan kedua -> CANCELLED."""
    require("void")
    reason = (reason or "").strip()
    if not reason:
        raise UserError("Alasan pembatalan wajib diisi.")
    trx = get_transaction(trx_id)
    if trx is None:
        raise UserError("Transaksi tidak ditemukan.")
    if trx["status"] == STATUS_WAITING:
        new = STATUS_CANCELLED
    elif trx["status"] == STATUS_COMPLETED:
        new = STATUS_VOID
    else:
        raise UserError("Transaksi ini sudah dibatalkan.")
    stamp = util.now_str()
    db.execute("UPDATE transactions SET status=?, void_reason=?, voided_by=?, voided_at=? WHERE id=?",
               (new, reason, session.user["username"], stamp, trx_id))
    audit.log("BATAL TRANSAKSI", "transactions", trx_id, trx["status"], "%s: %s" % (new, reason))
    return new


def mark_printed(trx_id, kind):
    """kind: PRINT / REPRINT (dihitung) atau PDF (hanya dicatat)."""
    stamp = util.now_str()
    with db.transaction() as c:
        c.execute("INSERT INTO print_log(transaction_id, ts, username, kind) VALUES(?,?,?,?)",
                  (trx_id, stamp, session.user["username"] if session.user else "-", kind))
        if kind in ("PRINT", "REPRINT"):
            c.execute("UPDATE transactions SET print_count=print_count+1 WHERE id=?", (trx_id,))
    audit.log("CETAK ULANG" if kind == "REPRINT" else "CETAK" if kind == "PRINT" else "SIMPAN PDF", "transactions", trx_id)


# ---- ubah data transaksi (Laporan / Transaksi) --------------------------------------------
EDITABLE = ("truck_id", "customer_id", "material_id", "supplier_id", "destination", "driver_name", "volume_m3", "notes",
            "first_weight", "second_weight")


def update_transaction(trx_id, changes, reason):
    """Ubah data transaksi (Supervisor/Admin). Wajib alasan; berat dihitung ulang; semua perubahan masuk audit log."""
    require("edit_trx")
    reason = (reason or "").strip()
    if not reason:
        raise UserError("Alasan perubahan wajib diisi.")
    trx = get_transaction(trx_id)
    if trx is None:
        raise UserError("Transaksi tidak ditemukan.")
    if trx["status"] not in (STATUS_WAITING, STATUS_COMPLETED):
        raise UserError("Transaksi yang sudah dibatalkan tidak dapat diubah.")
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise UserError("Kolom tidak dapat diubah: %s" % ", ".join(sorted(unknown)))
    new = dict((k, trx[k]) for k in EDITABLE)
    new.update(changes)
    completed = trx["status"] == STATUS_COMPLETED
    if new["volume_m3"] is not None and new["volume_m3"] < 0:
        raise UserError("Volume tidak boleh negatif.")
    validate_weight(new["first_weight"])
    gross = tare = net = None
    warnings = []
    if completed:
        validate_weight(new["second_weight"])
        gross, tare, net = compute(new["first_weight"], new["second_weight"])
        if net <= 0:
            raise UserError("Berat timbangan 1 dan 2 tidak boleh sama.")
        errors, warnings = _rules("validate_second", {"first_weight": new["first_weight"],
                                                      "second_weight": new["second_weight"], "gross": gross,
                                                      "tare": tare, "net": net})
        if errors:
            raise UserError("\n".join(errors))
    elif new["second_weight"] is not None:
        raise UserError("Timbangan kedua belum dilakukan untuk transaksi ini.")
    diffs = ["%s: %s -> %s" % (k, trx[k], new[k]) for k in EDITABLE if trx[k] != new[k]]
    if not diffs:
        raise UserError("Tidak ada perubahan data.")
    with db.transaction() as c:
        for table, col in (("customers", "customer_id"), ("materials", "material_id"), ("suppliers", "supplier_id"),
                           ("trucks", "truck_id")):
            if new[col] != trx[col] and new[col] and not c.execute(
                    "SELECT 1 FROM %s WHERE id=? AND active=1" % table, (new[col],)).fetchone():
                raise UserError("Data %s yang dipilih tidak aktif atau tidak ditemukan." % table)
        if new["truck_id"] != trx["truck_id"] and not completed and c.execute(
                "SELECT 1 FROM transactions WHERE truck_id=? AND status=? AND id<>?",
                (new["truck_id"], STATUS_WAITING, trx_id)).fetchone():
            raise UserError("Truk tujuan masih punya transaksi yang belum selesai.")
        c.execute("UPDATE transactions SET truck_id=?, customer_id=?, material_id=?, supplier_id=?, destination=?, driver_name=?,"
                  " volume_m3=?, notes=?, first_weight=?, second_weight=?, gross_weight=?, tare_weight=?, net_weight=? WHERE id=?",
                  (new["truck_id"], new["customer_id"], new["material_id"], new["supplier_id"] or None,
                   new["destination"] or None, new["driver_name"] or None, new["volume_m3"] or None, new["notes"] or None,
                   new["first_weight"], new["second_weight"], gross, tare, net, trx_id))
        c.execute("UPDATE transaction_weights SET weight=? WHERE transaction_id=? AND seq=1", (new["first_weight"], trx_id))
        if completed:
            c.execute("UPDATE transaction_weights SET weight=? WHERE transaction_id=? AND seq=2", (new["second_weight"], trx_id))
    audit.log("UBAH TRANSAKSI", "transactions", trx_id, None, "%s | alasan: %s" % ("; ".join(diffs), reason))
    return {"warnings": warnings, "changed": diffs}


# ---- daftar & statistik -------------------------------------------------------------
_FROM = (" FROM transactions t JOIN trucks k ON k.id=t.truck_id JOIN customers c ON c.id=t.customer_id"
         " JOIN materials m ON m.id=t.material_id LEFT JOIN suppliers s ON s.id=t.supplier_id"
         " LEFT JOIN users u ON u.id=t.operator_id ")


def list_transactions(date_from, date_to, text="", status="", page=0, page_size=100):
    """Mengembalikan (rows, total). Pencarian meliputi no. polisi, kode truk, no. transaksi, pelanggan, supplier,
    material, tujuan, sopir, dan operator."""
    require("view_trx")
    raw = text.strip()
    like = "%" + raw + "%"
    plate_like = "%" + util.normalize_plate(raw) + "%"
    where = (" WHERE t.created_at>=? AND t.created_at<? AND (?='' OR t.status=?) AND (k.plate LIKE ? OR COALESCE(k.truck_code,'') LIKE ?"
             " OR t.trx_number LIKE ? OR c.name LIKE ? OR COALESCE(s.name,'') LIKE ? OR m.name LIKE ?"
             " OR COALESCE(t.destination,'') LIKE ? OR COALESCE(t.driver_name,'') LIKE ? OR COALESCE(u.full_name,'') LIKE ?) ")
    params = (util.day_str(date_from), util.day_str(date_to + datetime.timedelta(days=1)), status, status,
              plate_like, like, like, like, like, like, like, like, like)
    total = db.scalar("SELECT COUNT(*)" + _FROM + where, params)
    rows = db.query(
        "SELECT t.id, substr(t.created_at,1,16) AS tanggal, t.trx_number, k.plate_display, COALESCE(k.truck_code,'') AS truck_code,"
        " c.name AS customer, m.name AS material, COALESCE(s.name,'-') AS supplier, COALESCE(t.destination,'') AS destination,"
        " t.gross_weight, t.tare_weight, t.net_weight, COALESCE(u.full_name,'-') AS operator, t.status, t.print_count"
        + _FROM + where + " ORDER BY t.id DESC LIMIT ? OFFSET ?", params + (page_size, page * page_size))
    return rows, total


def open_transactions():
    return db.query(
        "SELECT t.id, substr(t.first_weight_time,1,16) AS waktu, t.trx_number, k.plate_display, COALESCE(k.truck_code,'') AS truck_code,"
        " c.name AS customer, m.name AS material, t.first_weight" + _FROM + " WHERE t.status=? ORDER BY t.id", (STATUS_WAITING,))


def today_stats():
    today = datetime.date.today()
    a, b = util.day_str(today), util.day_str(today + datetime.timedelta(days=1))
    count = db.scalar("SELECT COUNT(*) FROM transactions WHERE created_at>=? AND created_at<? AND status NOT IN (?,?)",
                      (a, b, STATUS_VOID, STATUS_CANCELLED))
    net = db.scalar("SELECT COALESCE(SUM(net_weight),0) FROM transactions WHERE status=? AND completed_at>=? AND completed_at<?",
                    (STATUS_COMPLETED, a, b))
    recorded = db.scalar("SELECT COALESCE(SUM(volume_m3),0) FROM transactions WHERE status=? AND completed_at>=? AND completed_at<?",
                         (STATUS_COMPLETED, a, b))
    waiting = db.scalar("SELECT COUNT(*) FROM transactions WHERE status=?", (STATUS_WAITING,))
    last = db.query_one("SELECT t.trx_number, k.plate_display FROM transactions t JOIN trucks k ON k.id=t.truck_id"
                        " WHERE t.status NOT IN (?,?) ORDER BY t.id DESC LIMIT 1", (STATUS_VOID, STATUS_CANCELLED))
    return {"count": count, "net_kg": net, "net_m3": net_volume(net), "recorded_m3": recorded, "waiting": waiting,
            "last": (last[0], last[1]) if last else None}


def volume_by_material_today():
    """Netto dalam volume per mutu beton untuk hari ini -> [(material, jumlah, net_kg, net_m3)]."""
    today = datetime.date.today()
    a, b = util.day_str(today), util.day_str(today + datetime.timedelta(days=1))
    rows = db.query("SELECT m.name, COUNT(*), COALESCE(SUM(t.net_weight),0) FROM transactions t JOIN materials m ON m.id=t.material_id"
                    " WHERE t.status=? AND t.completed_at>=? AND t.completed_at<? GROUP BY m.id ORDER BY SUM(t.net_weight) DESC",
                    (STATUS_COMPLETED, a, b))
    return [(r[0], r[1], r[2], net_volume(r[2])) for r in rows]
