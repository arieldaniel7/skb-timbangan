"""Laporan lokal. run() mengembalikan (headers, rows, total_net_kg, ids).

ids = id transaksi per baris untuk laporan rincian (agar bisa diubah dari jendela Laporan), None untuk ringkasan.
'Netto Volume' = netto kg / densitas beton (Pengaturan)."""
import datetime

from app import util
from app.errors import UserError
from app.database import db
from app.authentication.session import require
from app.services import weighing

KINDS = [
    ("daily", "Laporan Harian (Rincian)"),
    ("monthly", "Laporan Bulanan (Ringkasan per Hari)"),
    ("customer", "Ringkasan per Pelanggan"),
    ("supplier", "Ringkasan per Supplier"),
    ("material", "Ringkasan per Material / Mutu Beton"),
    ("truck", "Ringkasan per Truk"),
    ("truck_history", "Riwayat Transaksi Truk"),
]
DETAIL_KINDS = ("daily", "truck_history")

_FROM = (" FROM transactions t JOIN trucks k ON k.id=t.truck_id JOIN customers c ON c.id=t.customer_id"
         " JOIN materials m ON m.id=t.material_id LEFT JOIN suppliers s ON s.id=t.supplier_id"
         " LEFT JOIN users u ON u.id=t.operator_id"
         " WHERE t.status='COMPLETED' AND t.completed_at>=? AND t.completed_at<? ")

_GROUP_KEYS = {
    "monthly": ("Tanggal", "substr(t.completed_at,1,10)", "1"),
    "customer": ("Pelanggan", "c.name", "SUM(t.net_weight) DESC"),
    "supplier": ("Supplier", "COALESCE(s.name,'-')", "SUM(t.net_weight) DESC"),
    "material": ("Material", "m.name", "SUM(t.net_weight) DESC"),
    "truck": ("No. Polisi", "k.plate_display", "SUM(t.net_weight) DESC"),
}


def run(kind, date_from, date_to, plate_filter=""):
    require("reports")
    a = util.day_str(date_from)
    b = util.day_str(date_to + datetime.timedelta(days=1))
    dens = float(weighing.density())
    if kind in DETAIL_KINDS:
        extra, params = "", [dens, a, b]
        if kind == "truck_history" and plate_filter.strip():
            extra = " AND (k.plate LIKE ? OR UPPER(COALESCE(k.truck_code,'')) LIKE ?) "
            params += ["%" + util.normalize_plate(plate_filter) + "%", "%" + plate_filter.strip().upper() + "%"]
        headers = ["Selesai", "No. Transaksi", "No. Polisi", "Kode Truk", "Pelanggan", "Material", "Supplier", "Tujuan",
                   "Sopir", "Volume Tercatat (m3)", "Kotor (kg)", "Tara (kg)", "Bersih (kg)", "Netto Volume (m3)", "Operator"]
        rows = db.query(
            "SELECT t.id, substr(t.completed_at,1,16), t.trx_number, k.plate_display, COALESCE(k.truck_code,''), c.name, m.name,"
            " COALESCE(s.name,'-'), COALESCE(t.destination,''), COALESCE(t.driver_name,''), t.volume_m3, t.gross_weight,"
            " t.tare_weight, t.net_weight, ROUND(t.net_weight / ?, 2), COALESCE(u.full_name,'-')" + _FROM + extra +
            " ORDER BY t.completed_at", tuple(params))
        ids = [r[0] for r in rows]
        data = [list(r)[1:] for r in rows]
        return headers, data, sum(r[12] or 0 for r in data), ids
    if kind not in _GROUP_KEYS:
        raise UserError("Jenis laporan tidak dikenal.")
    label, key, order = _GROUP_KEYS[kind]
    rows = db.query("SELECT %s, COUNT(*), SUM(t.net_weight), ROUND(SUM(t.net_weight) / ?, 2), SUM(t.volume_m3)%s GROUP BY %s ORDER BY %s" %
                    (key, _FROM, key, order), (dens, a, b))
    data = [list(r) for r in rows]
    return ([label, "Jumlah Transaksi", "Total Bersih (kg)", "Netto Volume (m3)", "Volume Tercatat (m3)"], data,
            sum(r[2] or 0 for r in data), None)
