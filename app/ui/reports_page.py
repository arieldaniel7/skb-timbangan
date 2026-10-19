import datetime

from PyQt5.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from app import util
from app.errors import UserError
from app.authentication.session import can
from app.reports import export
from app.reports import service as reports
from app.services import audit
from app.ui import widgets as w
from app.ui.edit_dialog import TransactionEditDialog


class ReportsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self._data = None
        self._ids = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 8, 30, 24)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.kind = QComboBox()
        w.fill_combo(self.kind, reports.KINDS, keep_first=True)
        self.d_from, self.d_to = w.date_edit(datetime.date.today().replace(day=1)), w.date_edit()
        self.plate = QLineEdit()
        self.plate.setPlaceholderText("No. polisi / kode truk (Riwayat Truk)")
        self.plate.setMaximumWidth(260)
        show = w.btn("Tampilkan", "primary")
        show.clicked.connect(self.load)
        bar.addWidget(self.kind, 1)
        bar.addWidget(self.d_from)
        bar.addWidget(w.label("s/d", role="muted"))
        bar.addWidget(self.d_to)
        bar.addWidget(self.plate)
        bar.addWidget(show)
        lay.addLayout(bar)

        edit_bar = QHBoxLayout()
        self.hint = w.label("", role="subtitle")
        self.btn_edit = w.btn("Ubah data", "primary")
        self.btn_edit.clicked.connect(self.edit_selected)
        edit_bar.addWidget(self.hint, 1)
        edit_bar.addWidget(self.btn_edit)
        lay.addLayout(edit_bar)

        self.table = w.make_table()
        self.table.cellDoubleClicked.connect(lambda row, col: self.edit_row(row))
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.summary = w.label("", tone="ok")
        bottom.addWidget(self.summary, 1)
        for text, fn in (("CSV", self.to_csv), ("Excel", self.to_xlsx), ("PDF", self.to_pdf), ("Cetak", self.to_print)):
            b = w.btn(text)
            b.clicked.connect(fn)
            bottom.addWidget(b)
        lay.addLayout(bottom)

    def on_show(self):
        self.load()

    @w.guarded
    def load(self):
        self._data = reports.run(self.kind.currentData(), w.py_date(self.d_from), w.py_date(self.d_to), self.plate.text())
        headers, rows, total, self._ids = self._data
        w.fill_table(self.table, headers, rows)
        self.summary.setText("%d baris   ·   Total bersih %s kg  (%s)" %
                             (len(rows), util.format_int(total), util.format_weight(total, "TON")))
        editable = self._ids is not None and can("edit_trx")
        self.btn_edit.setEnabled(editable)
        if self._ids is None:
            self.hint.setText("Pilih laporan rincian (Harian / Riwayat Truk) untuk mengubah data transaksi.")
        elif editable:
            self.hint.setText("Klik dua kali sebuah baris, atau pilih baris lalu Ubah data, untuk mengoreksi transaksi.")
        else:
            self.hint.setText("Hanya Supervisor dan Admin yang dapat mengubah data.")

    # ---- ubah data dari laporan ----
    def edit_row(self, row):
        w.run_guarded(self, self._edit_row, row)

    @w.guarded
    def edit_selected(self):
        self._edit_row(self.table.currentRow())

    def _edit_row(self, row):
        if self._ids is None:
            raise UserError("Pilih laporan rincian (Harian / Riwayat Truk) untuk mengubah data.")
        if not can("edit_trx"):
            raise UserError("Hanya Supervisor dan Admin yang dapat mengubah data.")
        if not 0 <= row < len(self._ids):
            raise UserError("Pilih baris yang akan diubah.")
        dlg = TransactionEditDialog(self, self._ids[row])
        if dlg.exec_() == QDialog.Accepted and dlg.saved:
            self.load()
            if 0 <= row < self.table.rowCount():
                self.table.selectRow(row)

    # ---- ekspor ----
    def _current(self):
        if self._data is None:
            self.load()
        if self._data is None:
            raise UserError("Tidak ada data.")
        headers, rows, total, _ids = self._data
        sub = "Periode %s s/d %s   |   Total bersih %s kg" % (w.py_date(self.d_from).strftime("%d/%m/%Y"),
                                                              w.py_date(self.d_to).strftime("%d/%m/%Y"), util.format_int(total))
        return self.kind.currentText(), sub, headers, rows, total

    def _save_path(self, ext, label):
        name = "laporan_%s.%s" % (datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), ext)
        path, _ = QFileDialog.getSaveFileName(self, "Simpan laporan", name, "%s (*.%s)" % (label, ext))
        return path

    @w.guarded
    def to_csv(self):
        title, sub, headers, rows, total = self._current()
        path = self._save_path("csv", "CSV")
        if path:
            export.export_csv(path, headers, rows)
            audit.log("EKSPOR LAPORAN", None, None, None, "%s -> csv" % title)
            w.info(self, "Laporan tersimpan.")

    @w.guarded
    def to_xlsx(self):
        title, sub, headers, rows, total = self._current()
        path = self._save_path("xlsx", "Excel")
        if path:
            export.export_xlsx(path, title, headers, rows)
            audit.log("EKSPOR LAPORAN", None, None, None, "%s -> xlsx" % title)
            w.info(self, "Laporan tersimpan.")

    @w.guarded
    def to_pdf(self):
        title, sub, headers, rows, total = self._current()
        path = self._save_path("pdf", "PDF")
        if path:
            export.export_pdf(path, export.table_html(title, sub, headers, rows))
            audit.log("EKSPOR LAPORAN", None, None, None, "%s -> pdf" % title)
            w.info(self, "Laporan tersimpan.")

    @w.guarded
    def to_print(self):
        title, sub, headers, rows, total = self._current()
        if export.print_html(export.table_html(title, sub, headers, rows), self):
            audit.log("CETAK LAPORAN", None, None, None, title)
