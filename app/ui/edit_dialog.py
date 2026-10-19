"""Dialog ubah data transaksi (dipakai dari Laporan dan Transaksi). Wajib alasan; tercatat di audit log."""
from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from app import util
from app.errors import UserError
from app.services import masterdata, weighing
from app.ui import widgets as w


class TransactionEditDialog(w.FadeDialog):
    def __init__(self, parent, trx_id):
        super().__init__(parent)
        trx = weighing.get_transaction(trx_id)
        if trx is None or trx["status"] not in (weighing.STATUS_WAITING, weighing.STATUS_COMPLETED):
            raise UserError("Transaksi ini tidak dapat diubah (tidak ditemukan atau sudah dibatalkan).")
        self.trx_id, self.trx = trx_id, trx
        self.completed = trx["status"] == weighing.STATUS_COMPLETED
        self.saved = False
        self.setWindowTitle("Scaler")
        self.setMinimumWidth(680)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 24)
        lay.setSpacing(8)
        lay.addWidget(w.label("Ubah transaksi %s" % trx["trx_number"], role="value", size="md"))
        lay.addWidget(w.label("Kotor, tara, dan bersih dihitung ulang otomatis. Semua perubahan dicatat di audit log.",
                              role="subtitle"))
        lay.addSpacing(8)

        self.truck, self.customer, self.material, self.supplier = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        w.fill_combo(self.truck, [(r["id"], r["plate_display"] + (("  ·  " + r["truck_code"]) if r["truck_code"] else ""))
                                  for r in masterdata.truck_options(include_id=trx["truck_id"])])
        w.fill_combo(self.customer, masterdata.options("customers", include_id=trx["customer_id"]))
        w.fill_combo(self.material, masterdata.options("materials", include_id=trx["material_id"]))
        w.fill_combo(self.supplier, masterdata.options("suppliers", optional=True, include_id=trx["supplier_id"]))
        for combo, value in ((self.truck, trx["truck_id"]), (self.customer, trx["customer_id"]),
                             (self.material, trx["material_id"]), (self.supplier, trx["supplier_id"] or 0)):
            combo.setCurrentIndex(combo.findData(value))
        self.dest = QLineEdit(trx["destination"] or "")
        self.driver = QLineEdit(trx["driver_name"] or "")
        self.volume = QLineEdit(("%g" % trx["volume_m3"]) if trx["volume_m3"] else "")
        self.notes = QLineEdit(trx["notes"] or "")
        digits = QRegExpValidator(QRegExp(r"[0-9.,\s]*"))
        self.w1 = QLineEdit(str(trx["first_weight"]))
        self.w1.setValidator(digits)
        self.w2 = QLineEdit(str(trx["second_weight"]) if trx["second_weight"] else "")
        self.w2.setValidator(digits)
        self.w2.setEnabled(self.completed)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("mis. koreksi salah input timbangan")

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        cells = [("No. polisi", self.truck, 0, 0), ("Pelanggan", self.customer, 0, 1),
                 ("Mutu beton / material", self.material, 1, 0), ("Supplier", self.supplier, 1, 1),
                 ("Tujuan / proyek", self.dest, 2, 0), ("Nama sopir", self.driver, 2, 1),
                 ("Volume tercatat (m³)", self.volume, 3, 0), ("Catatan", self.notes, 3, 1),
                 ("Timbangan 1 (kg)", self.w1, 4, 0), ("Timbangan 2 (kg)", self.w2, 4, 1)]
        for text, widget, r, c in cells:
            grid.addWidget(w.caption(text), r * 2, c)
            grid.addWidget(widget, r * 2 + 1, c)
        grid.addWidget(w.caption("Alasan perubahan (wajib)"), 10, 0, 1, 2)
        grid.addWidget(self.reason, 11, 0, 1, 2)
        lay.addLayout(grid)
        self.preview = w.label("", tone="ok")
        lay.addSpacing(6)
        lay.addWidget(self.preview)
        row = QHBoxLayout()
        row.addStretch(1)
        no, ok = w.btn("Batal", "ghost", 100), w.btn("Simpan perubahan", "primary", 160)
        no.clicked.connect(self.reject)
        ok.clicked.connect(self.save)
        row.addWidget(no)
        row.addWidget(ok)
        lay.addSpacing(8)
        lay.addLayout(row)
        self.w1.textChanged.connect(self.recalc)
        self.w2.textChanged.connect(self.recalc)
        self.recalc()

    def recalc(self, *_):
        try:
            first = util.parse_weight(self.w1.text())
            if not self.completed:
                self.preview.setText("Timbangan 1: %s" % util.format_weight(first))
                return
            gross, tare, net = weighing.compute(first, util.parse_weight(self.w2.text()))
            self.preview.setText("Kotor %s   ·   Tara %s   ·   Bersih %s   ·   %s" % (
                util.format_weight(gross), util.format_weight(tare), util.format_weight(net),
                util.format_volume(weighing.net_volume(net))))
        except UserError:
            self.preview.setText("Isi berat yang valid (angka > 0).")

    @w.guarded
    def save(self):
        trx, changes = self.trx, {}

        def put(key, value):
            if value != trx[key]:
                changes[key] = value

        put("truck_id", self.truck.currentData())
        put("customer_id", self.customer.currentData())
        put("material_id", self.material.currentData())
        put("supplier_id", self.supplier.currentData() or None)
        put("destination", self.dest.text().strip() or None)
        put("driver_name", self.driver.text().strip() or None)
        put("notes", self.notes.text().strip() or None)
        vol_text = self.volume.text().strip().replace(",", ".")
        try:
            volume = float(vol_text) if vol_text else None
        except ValueError:
            raise UserError("Volume harus berupa angka.")
        put("volume_m3", volume)
        put("first_weight", util.parse_weight(self.w1.text()))
        if self.completed:
            put("second_weight", util.parse_weight(self.w2.text()))
        result = weighing.update_transaction(self.trx_id, changes, self.reason.text())
        for message in result["warnings"]:
            w.warn(self, message)
        self.saved = True
        w.notify("Transaksi %s diperbarui" % trx["trx_number"])
        self.accept()
