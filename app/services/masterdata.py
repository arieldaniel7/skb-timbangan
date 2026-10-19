"""CRUD data induk (pelanggan, supplier, material/mutu beton, truk). Tidak ada hapus permanen: nonaktifkan."""
import sqlite3

from app import util
from app.errors import UserError
from app.database import db
from app.authentication.session import require
from app.services import audit


class Field(object):
    def __init__(self, key, label, required=False, kind="text"):
        self.key, self.label, self.required, self.kind = key, label, required, kind


class Entity(object):
    def __init__(self, table, title, fields, order):
        self.table, self.title, self.fields, self.order = table, title, fields, order


def _party(noun):
    return [Field("code", "Kode", True), Field("name", "Nama " + noun, True), Field("address", "Alamat")]


ENTITIES = [
    Entity("customers", "Pelanggan", _party("Pelanggan"), "name"),
    Entity("suppliers", "Supplier", _party("Supplier"), "name"),
    Entity("materials", "Material / Mutu Beton",
           [Field("code", "Kode (mis. K-300)", True), Field("name", "Nama Material", True), Field("category", "Kategori"),
            Field("unit", "Satuan"), Field("description", "Keterangan")], "code"),
    Entity("trucks", "Truk",
           [Field("plate_display", "Nomor Polisi", True), Field("truck_code", "Kode Truk (mis. TM-001)"),
            Field("truck_type", "Jenis Truk"), Field("driver", "Sopir"), Field("notes", "Catatan")], "plate_display"),
]
BY_TABLE = dict((e.table, e) for e in ENTITIES)
DUPLICATE = "Data dengan kode / nomor polisi yang sama sudah ada."


def _entity(table):
    if table not in BY_TABLE:
        raise UserError("Data induk tidak dikenal.")
    return BY_TABLE[table]


def list_rows(table, search=""):
    e = _entity(table)
    cols = ", ".join(f.key for f in e.fields)
    where = " OR ".join("CAST(%s AS TEXT) LIKE ?" % f.key for f in e.fields)
    like = "%" + search.strip() + "%"
    return db.query("SELECT id, %s, active FROM %s WHERE (%s) ORDER BY %s" % (cols, table, where, e.order),
                    tuple([like] * len(e.fields)))


def get(table, row_id):
    _entity(table)
    return db.query_one("SELECT * FROM %s WHERE id=?" % table, (row_id,))


def _clean(entity, data):
    values = {}
    for f in entity.fields:
        v = (data.get(f.key) or "").strip()
        if f.required and not v:
            raise UserError("%s wajib diisi." % f.label)
        if f.kind == "int":
            if v == "":
                v = None
            else:
                try:
                    v = int(v)
                except ValueError:
                    raise UserError("%s harus berupa angka bulat." % f.label)
                if v < 0:
                    raise UserError("%s tidak boleh negatif." % f.label)
        elif not f.required:
            v = v or None
        values[f.key] = v
    if entity.table == "trucks":
        values["plate_display"] = util.format_plate(values["plate_display"])
        values["plate"] = util.normalize_plate(values["plate_display"])
        if not values["plate"]:
            raise UserError("Nomor polisi tidak valid.")
        values["truck_code"] = values["truck_code"].upper() if values.get("truck_code") else None
    return values


def create(table, data):
    require("edit_master")
    e = _entity(table)
    values = _clean(e, data)
    cols = list(values.keys())
    try:
        cur = db.execute("INSERT INTO %s(%s, active, created_at) VALUES(%s, 1, ?)" %
                         (table, ", ".join(cols), ", ".join("?" * len(cols))),
                         tuple(values[c] for c in cols) + (util.now_str(),))
    except sqlite3.IntegrityError:
        raise UserError(DUPLICATE)
    audit.log("TAMBAH " + table.upper(), table, cur.lastrowid, None, ", ".join("%s=%s" % kv for kv in sorted(values.items())))
    return cur.lastrowid


def update(table, row_id, data):
    require("edit_master")
    e = _entity(table)
    if get(table, row_id) is None:
        raise UserError("Data tidak ditemukan.")
    values = _clean(e, data)
    cols = list(values.keys())
    try:
        db.execute("UPDATE %s SET %s, updated_at=? WHERE id=?" % (table, ", ".join(c + "=?" for c in cols)),
                   tuple(values[c] for c in cols) + (util.now_str(), row_id))
    except sqlite3.IntegrityError:
        raise UserError(DUPLICATE)
    audit.log("UBAH " + table.upper(), table, row_id, None, ", ".join("%s=%s" % kv for kv in sorted(values.items())))


def toggle_active(table, row_id):
    require("edit_master")
    _entity(table)
    db.execute("UPDATE %s SET active=1-active, updated_at=? WHERE id=?" % table, (util.now_str(), row_id))
    audit.log("AKTIF/NONAKTIF " + table.upper(), table, row_id)


def options(table, optional=False, include_id=None):
    """[(id, label)] data aktif untuk combo box. include_id: sertakan data tertentu walau sudah nonaktif."""
    label = "code || ' - ' || name" if table == "materials" else "name"
    order = "code" if table == "materials" else "name"
    rows = db.query("SELECT id, %s FROM %s WHERE active=1 OR id=? ORDER BY %s" % (label, table, order), (include_id or 0,))
    out = [(r[0], r[1]) for r in rows]
    return ([(0, "(tanpa)")] + out) if optional else out


# ---- truk -------------------------------------------------------------------------------
def truck_options(include_id=None):
    return db.query("SELECT id, plate_display, truck_code, driver FROM trucks WHERE active=1 OR id=? ORDER BY plate_display",
                    (include_id or 0,))


def find_truck(text):
    """Cari truk dari nomor polisi (format bebas) atau kode truk (mis. TM-001)."""
    text = (text or "").strip()
    plate = util.normalize_plate(text)
    if not plate:
        return None
    row = db.query_one("SELECT * FROM trucks WHERE plate=?", (plate,))
    if row is None:
        row = db.query_one("SELECT * FROM trucks WHERE UPPER(truck_code)=?", (text.upper(),))
    return row


def truck_by_plate(plate_text):
    plate = util.normalize_plate(plate_text)
    return db.query_one("SELECT * FROM trucks WHERE plate=?", (plate,)) if plate else None


def register_truck(plate_text, truck_code="", driver=""):
    """Simpan nomor polisi baru langsung dari layar penimbangan (tanpa lewat Master Data). Boleh dilakukan operator."""
    require("weigh")
    display = util.format_plate(plate_text)
    plate = util.normalize_plate(display)
    if not plate:
        raise UserError("Nomor polisi tidak valid.")
    if db.query_one("SELECT 1 FROM trucks WHERE plate=?", (plate,)):
        raise UserError("Nomor polisi %s sudah terdaftar." % display)
    code = (truck_code or "").strip().upper() or None
    try:
        cur = db.execute("INSERT INTO trucks(plate, plate_display, truck_code, driver, active, created_at) VALUES(?,?,?,?,1,?)",
                         (plate, display, code, (driver or "").strip() or None, util.now_str()))
    except sqlite3.IntegrityError:
        raise UserError("Kode truk %s sudah dipakai truk lain." % code)
    audit.log("TAMBAH TRUK", "trucks", cur.lastrowid, None, "%s %s" % (display, code or ""))
    return cur.lastrowid


def search_trucks(prefix, limit=10):
    plate = util.normalize_plate(prefix)
    if not plate:
        return []
    return [r[0] for r in db.query(
        "SELECT plate_display FROM trucks WHERE active=1 AND (plate LIKE ? OR UPPER(truck_code) LIKE ?) ORDER BY plate LIMIT ?",
        (plate + "%", prefix.strip().upper() + "%", limit))]
