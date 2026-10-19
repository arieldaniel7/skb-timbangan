from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from app import util
from app.authentication.session import can
from app.services import weighing
from app.printing import ticket
from app.ui import widgets as w
from app.ui.edit_dialog import TransactionEditDialog

STATUSES = [("", "Semua status"), (weighing.STATUS_WAITING, "Menunggu timbangan 2"), (weighing.STATUS_COMPLETED, "Selesai"),
            (weighing.STATUS_VOID, "Batal (void)"), (weighing.STATUS_CANCELLED, "Dibatalkan")]
HEADERS = ["id", "Tanggal", "No. Transaksi", "No. Polisi", "Kode", "Pelanggan", "Material", "Supplier", "Tujuan",
           "Kotor (kg)", "Tara (kg)", "Bersih (kg)", "Netto (m³)", "Operator", "Status", "Cetak"]
PAGE = 100


class TransactionsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.page = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 8, 30, 24)
        lay.setSpacing(14)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.d_from, self.d_to = w.date_edit(), w.date_edit()
        bar.addWidget(self.d_from)
        bar.addWidget(w.label("s/d", role="muted"))
        bar.addWidget(self.d_to)
        for name in ("Hari ini", "Kemarin", "Minggu ini", "Bulan ini"):
            b = w.btn(name, "ghost")
            b.clicked.connect(lambda _=False, n=name: self.quick(n))
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        bar2 = QHBoxLayout()
        bar2.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari no. polisi, kode truk, transaksi, pelanggan, supplier, material, tujuan, sopir, operator")
        self.search_edit.returnPressed.connect(self.search)
        self.status = QComboBox()
        w.fill_combo(self.status, STATUSES, keep_first=True)
        go = w.btn("Cari", "primary", 90)
        go.clicked.connect(self.search)
        bar2.addWidget(self.search_edit, 1)
        bar2.addWidget(self.status)
        bar2.addWidget(go)
        lay.addLayout(bar2)

        self.table = w.make_table()
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.prev_b, self.next_b = w.btn("‹", "ghost", 44), w.btn("›", "ghost", 44)
        self.prev_b.clicked.connect(self.prev)
        self.next_b.clicked.connect(self.next)
        self.page_lbl = w.label("", role="muted")
        bottom.addWidget(self.prev_b)
        bottom.addWidget(self.next_b)
        bottom.addWidget(self.page_lbl)
        bottom.addStretch(1)
        self.b_detail, self.b_preview, self.b_pdf = w.btn("Detail"), w.btn("Pratinjau"), w.btn("Simpan PDF")
        self.b_print, self.b_edit = w.btn("Cetak / Cetak ulang", "primary"), w.btn("Ubah")
        self.b_void = w.btn("Batalkan", "danger")
        for b, fn in ((self.b_detail, self.detail), (self.b_preview, self.preview), (self.b_pdf, self.save_pdf),
                      (self.b_print, self.print_selected), (self.b_edit, self.edit), (self.b_void, self.void)):
            b.clicked.connect(fn)
            bottom.addWidget(b)
        lay.addLayout(bottom)
        self.quick("Hari ini", load=False)

    def on_show(self):
        self.b_void.setEnabled(can("void"))
        self.b_edit.setEnabled(can("edit_trx"))
        self.load()

    def quick(self, name, load=True):
        a, b = w.quick_range(name)
        self.d_from.setDate(QDate(a.year, a.month, a.day))
        self.d_to.setDate(QDate(b.year, b.month, b.day))
        self.page = 0
        if load:
            self.load()

    @w.guarded
    def search(self):
        self.page = 0
        self.load()

    @w.guarded
    def prev(self):
        if self.page > 0:
            self.page -= 1
            self.load()

    @w.guarded
    def next(self):
        self.page += 1
        self.load()

    @w.guarded
    def load(self):
        rows, total = weighing.list_transactions(w.py_date(self.d_from), w.py_date(self.d_to), self.search_edit.text(),
                                                 self.status.currentData() or "", self.page, PAGE)
        pages = max(1, (total + PAGE - 1) // PAGE)
        if self.page >= pages:
            self.page = pages - 1
        data = []
        for r in rows:
            net = r["net_weight"]
            data.append([r["id"], r["tanggal"], r["trx_number"], r["plate_display"], r["truck_code"], r["customer"],
                         r["material"], r["supplier"], r["destination"], r["gross_weight"], r["tare_weight"], net,
                         round(weighing.net_volume(net), 2) if net else None, r["operator"],
                         weighing.STATUS_LABELS.get(r["status"], r["status"]), r["print_count"]])
        w.fill_table(self.table, HEADERS, data, hidden=(0,))
        self.page_lbl.setText("Halaman %d / %d   ·   %d data" % (self.page + 1, pages, total))

    def _id(self):
        return w.selected_value(self.table, 0)

    @w.guarded
    def detail(self):
        t = weighing.get_transaction(self._id())
        unit = "KG"
        net = t["net_weight"]
        lines = [
            "No. Transaksi : %s" % t["trx_number"],
            "Status : %s" % weighing.STATUS_LABELS.get(t["status"], t["status"]),
            "No. Polisi : %s%s" % (t["plate"], ("  (%s)" % t["truck_code"]) if t["truck_code"] else ""),
            "Sopir : %s" % (t["driver_name"] or "-"), "Pelanggan : %s" % t["customer"], "Material : %s" % t["material"],
            "Volume tercatat : %s" % (util.format_volume(t["volume_m3"]) if t["volume_m3"] else "-"),
            "Supplier : %s" % (t["supplier"] or "-"), "Tujuan : %s" % (t["destination"] or "-"), "",
            "Timbangan 1 : %s  (%s)" % (util.format_weight(t["first_weight"], unit), util.fmt_dt(t["first_weight_time"])),
            "Timbangan 2 : %s" % ("-" if t["second_weight"] is None else "%s  (%s)" % (
                util.format_weight(t["second_weight"], unit), util.fmt_dt(t["second_weight_time"]))),
            "Kotor / Tara / Bersih : %s / %s / %s" % (util.format_weight(t["gross_weight"], unit),
                                                       util.format_weight(t["tare_weight"], unit),
                                                       util.format_weight(net, unit)),
            "Netto dalam volume : %s" % (util.format_volume(weighing.net_volume(net)) if net else "-"),
            "Operator : %s" % t["operator_name"], "Jumlah cetak : %d" % t["print_count"],
        ]
        if t["void_reason"]:
            lines.append("Alasan batal : %s (oleh %s)" % (t["void_reason"], t["voided_by"]))
        w.info(self, "\n".join(lines))

    @w.guarded
    def preview(self):
        ticket.print_ticket(self._id(), preview=True, parent=self)

    @w.guarded
    def print_selected(self):
        tid = self._id()
        t = weighing.get_transaction(tid)
        kind = "ULANG" if t["print_count"] > 0 else "pertama"
        if not w.ask(self, "Cetak tiket %s (cetak %s)?" % (t["trx_number"], kind), yes="Cetak", no="Batal"):
            return
        ticket.print_ticket(tid, parent=self)
        self.load()

    @w.guarded
    def save_pdf(self):
        tid = self._id()
        t = weighing.get_transaction(tid)
        path, _ = QFileDialog.getSaveFileName(self, "Simpan tiket PDF", "tiket_%s.pdf" % t["trx_number"], "PDF (*.pdf)")
        if path:
            ticket.print_ticket(tid, pdf_path=path, parent=self)
            self.load()
            w.info(self, "Tiket tersimpan: " + path)

    @w.guarded
    def edit(self):
        dlg = TransactionEditDialog(self, self._id())
        if dlg.exec_() == QDialog.Accepted and dlg.saved:
            self.load()

    @w.guarded
    def void(self):
        tid = self._id()
        res = w.prompt_fields(self, "Batalkan transaksi", [{"key": "reason", "label": "Alasan pembatalan", "required": True}])
        if res is None:
            return
        weighing.void_transaction(tid, res["reason"])
        self.load()
