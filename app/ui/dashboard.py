"""Dashboard = konsol operator: statistik hari ini, pilih truk (data otomatis termuat), penimbangan dua tahap,
simpan nomor polisi baru langsung dari sini, dan netto dalam volume (m³)."""
from PyQt5.QtCore import QRegExp, QTimer, Qt
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import (QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout,
                             QWidget)

from app import log, util
from app.errors import UserError
from app.authentication.session import can
from app.services import masterdata, settings, weighing
from app.printing import ticket
from app.ui import widgets as w

logger = log.get(__name__)

MODES = {
    0: ("Pilih truk untuk memulai", ""),
    1: ("Timbangan pertama", "ok"),
    2: ("Menunggu timbangan kedua", "warn"),
    3: ("Selesai - siap dicetak", "ok"),
}
WAITING_HEADERS = ["id", "Waktu", "No. Transaksi", "No. Polisi", "Kode", "Pelanggan", "Material", "Timbangan 1 (kg)"]


class DashboardPage(QWidget):
    def __init__(self, scale):
        super().__init__()
        self.setObjectName("page")
        self.scale = scale
        self.mode = 0                # 0 kosong, 1 timbang pertama, 2 timbang kedua, 3 selesai
        self.open_id = None
        self.first_weight = 0
        self.last_done = None
        self.truck = None            # baris truk terdaftar yang sedang dimuat (None = nomor polisi baru)
        self.loaded_plate = ""       # nomor polisi ter-normalisasi yang sedang dimuat
        self._newbox_open = False
        self._vol_sig = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(30, 8, 30, 30)
        lay.setSpacing(18)
        lay.addLayout(self._build_stats())
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self._build_console(), 6)
        row.addLayout(self._build_side(), 5)
        lay.addLayout(row, 1)

        self.scale_timer = QTimer(self)
        self.scale_timer.setInterval(400)
        self.scale_timer.timeout.connect(self.poll_scale)
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(10000)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.reload_lists()
        self.set_mode(0)

    # ---------------------------------------------------------------- pembangun UI
    def _build_stats(self):
        row = QHBoxLayout()
        row.setSpacing(16)
        self.c_count = w.StatCard("Transaksi hari ini", size="xl", tone="ok")
        self.c_net = w.StatCard("Netto hari ini", size="xl")
        self.c_vol = w.StatCard("Netto dalam volume", size="xl", tone="ok")
        self.c_wait = w.StatCard("Menunggu timbangan kedua", size="xl")
        for c in (self.c_count, self.c_net, self.c_vol, self.c_wait):
            row.addWidget(c, 1)
        return row

    def _build_console(self):
        card, v = w.make_card(margins=(26, 22, 26, 24), spacing=12)
        head = QHBoxLayout()
        head.addWidget(w.caption("Penimbangan"))
        head.addStretch(1)
        self.mode_chip = w.label("", chip=True)
        head.addWidget(self.mode_chip)
        v.addLayout(head)

        # --- pemilih truk: pilih dari daftar (data otomatis termuat) atau ketik nomor baru ---
        row = QHBoxLayout()
        row.setSpacing(10)
        self.truck_combo = QComboBox()
        self.truck_combo.setEditable(True)
        self.truck_combo.setInsertPolicy(QComboBox.NoInsert)
        self.truck_combo.setMinimumHeight(50)
        edit = self.truck_combo.lineEdit()
        edit.setPlaceholderText("Pilih atau ketik nomor polisi / kode truk")
        edit.setProperty("picker", True)
        completer = self.truck_combo.completer()
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.truck_combo.activated.connect(self.on_pick)
        edit.returnPressed.connect(self.commit)
        self.btn_new = w.btn("Baru", "ghost")
        self.btn_new.setMinimumHeight(50)
        self.btn_new.clicked.connect(self.cancel)
        row.addWidget(self.truck_combo, 1)
        row.addWidget(self.btn_new)
        v.addLayout(row)
        self.truck_info = w.label("", role="muted")
        v.addWidget(self.truck_info)

        self.newbox = QFrame()
        self.newbox.setObjectName("newbox")
        self.newbox.setMaximumHeight(0)
        self.newbox.setVisible(False)
        nb = QHBoxLayout(self.newbox)
        nb.setContentsMargins(16, 10, 12, 10)
        nb.setSpacing(10)
        self.new_label = w.label("", tone="ok", wrap=True)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Kode truk, mis. TM-001 (opsional)")
        self.code_edit.setMaximumWidth(250)
        self.btn_save_truck = w.btn("Simpan ke database", "primary")
        self.btn_save_truck.clicked.connect(self.save_new_truck)
        nb.addWidget(self.new_label, 1)
        nb.addWidget(self.code_edit)
        nb.addWidget(self.btn_save_truck)
        v.addWidget(self.newbox)

        # --- data transaksi ---
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        self.customer, self.material, self.supplier = QComboBox(), QComboBox(), QComboBox()
        self.dest, self.volume, self.driver, self.notes = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.volume.setValidator(QRegExpValidator(QRegExp(r"[0-9]*[.,]?[0-9]*"), self.volume))
        cells = [("Pelanggan", self.customer, 0, 0), ("Mutu beton / material", self.material, 0, 1),
                 ("Supplier (opsional)", self.supplier, 1, 0), ("Tujuan / proyek", self.dest, 1, 1),
                 ("Volume tercatat (m³)", self.volume, 2, 0), ("Nama sopir", self.driver, 2, 1)]
        for text, widget, r, c in cells:
            grid.addWidget(w.caption(text), r * 2, c)
            grid.addWidget(widget, r * 2 + 1, c)
        grid.addWidget(w.caption("Catatan"), 6, 0, 1, 2)
        grid.addWidget(self.notes, 7, 0, 1, 2)
        v.addLayout(grid)
        v.addSpacing(4)
        v.addWidget(w.hline())

        # --- berat & aksi ---
        v.addWidget(w.caption("Berat"))
        wr = QHBoxLayout()
        self.weight = QLineEdit()
        self.weight.setProperty("display", True)
        self.weight.setAlignment(Qt.AlignRight)
        self.weight.setPlaceholderText("0")
        self.weight.setValidator(QRegExpValidator(QRegExp(r"[0-9.,\s]*"), self.weight))
        self.weight.returnPressed.connect(self.on_enter)
        wr.addWidget(self.weight, 1)
        wr.addWidget(w.label("KG", role="value", size="md", tone="muted"))
        v.addLayout(wr)
        self.scale_lbl = w.label("", role="subtitle")
        v.addWidget(self.scale_lbl)
        br = QHBoxLayout()
        br.setSpacing(10)
        self.btn_first = w.btn("Timbang pertama   F4", "primary")
        self.btn_second = w.btn("Timbang kedua   F5", "primary")
        self.btn_print = w.btn("Cetak tiket   F6")
        for b, fn in ((self.btn_first, self.do_first), (self.btn_second, self.do_second), (self.btn_print, self.do_print)):
            b.setMinimumHeight(50)
            b.clicked.connect(fn)
            br.addWidget(b, 1)
        v.addLayout(br)

        rr = QHBoxLayout()
        rr.setSpacing(10)
        self.r_gross = w.StatCard("Kotor", size="md")
        self.r_tare = w.StatCard("Tara", size="md")
        self.r_net = w.StatCard("Bersih", size="md", tone="ok")
        self.r_vol = w.StatCard("Netto volume", size="md", tone="ok")
        for c in (self.r_gross, self.r_tare, self.r_net, self.r_vol):
            rr.addWidget(c, 1)
        v.addLayout(rr)
        self.info = w.label("", role="muted", wrap=True)
        v.addWidget(self.info)
        return card

    def _build_side(self):
        col = QVBoxLayout()
        col.setSpacing(18)
        card, v = w.make_card(margins=(24, 20, 24, 22), spacing=12)
        head = QHBoxLayout()
        head.addWidget(w.caption("Netto dalam volume  ·  hari ini"))
        head.addStretch(1)
        self.vol_total = w.label("", role="value", size="sm", tone="ok")
        head.addWidget(self.vol_total)
        v.addLayout(head)
        self.vol_rows = QVBoxLayout()
        self.vol_rows.setSpacing(14)
        v.addLayout(self.vol_rows)
        self.vol_hint = w.label("", role="subtitle", wrap=True)
        v.addWidget(self.vol_hint)
        col.addWidget(card)

        card2, v2 = w.make_card(margins=(24, 20, 24, 22), spacing=12)
        v2.addWidget(w.caption("Menunggu timbangan kedua  ·  klik untuk memuat"))
        self.waiting = w.make_table()
        self.waiting.setMinimumHeight(230)
        self.waiting.cellClicked.connect(self.on_waiting_click)
        v2.addWidget(self.waiting, 1)
        col.addWidget(card2, 1)
        return col

    # ---------------------------------------------------------------- siklus tampil
    def showEvent(self, event):
        self.scale_timer.start()
        self.stats_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.scale_timer.stop()
        self.stats_timer.stop()
        super().hideEvent(event)

    def on_show(self):
        if self.mode in (0, 3):
            self.reload_lists()
        self.refresh_stats()
        self.focus_search()

    def focus_search(self):
        self.truck_combo.setFocus()
        self.truck_combo.lineEdit().selectAll()

    def reload_lists(self):
        w.fill_combo(self.customer, masterdata.options("customers"))
        w.fill_combo(self.material, masterdata.options("materials"))
        w.fill_combo(self.supplier, masterdata.options("suppliers", optional=True), keep_first=True)
        self.reload_trucks()

    def reload_trucks(self):
        keep = self.truck_combo.currentText()
        self.truck_combo.blockSignals(True)
        self.truck_combo.clear()
        for r in masterdata.truck_options():
            self.truck_combo.addItem(r["plate_display"] + (("   ·   " + r["truck_code"]) if r["truck_code"] else ""),
                                     r["plate_display"])
        self.truck_combo.setCurrentIndex(-1)
        self.truck_combo.setEditText(keep)
        self.truck_combo.blockSignals(False)

    # ---------------------------------------------------------------- state
    def set_mode(self, mode):
        self.mode = mode
        self.btn_first.setEnabled(mode == 1)
        self.btn_second.setEnabled(mode == 2)
        self.btn_print.setEnabled(mode == 3 and bool(self.last_done))
        edit = mode in (0, 1)
        for widget in (self.customer, self.material, self.supplier, self.dest, self.volume, self.driver, self.notes):
            widget.setEnabled(edit)
        text, tone = MODES[mode]
        if mode == 2:
            text += "  ·  timbangan 1: " + util.format_weight(self.first_weight, settings.get("unit"))
        self.mode_chip.setText(text)
        w.set_tone(self.mode_chip, tone)

    def _show_newbox(self, show):
        if show == self._newbox_open:
            return
        self._newbox_open = show
        if show:
            self.newbox.setVisible(True)
            w.animate_height(self.newbox, 68)
        else:
            w.animate_height(self.newbox, 0, on_finish=lambda: self.newbox.setVisible(self._newbox_open))

    def _clear_results(self):
        for c in (self.r_gross, self.r_tare, self.r_net, self.r_vol):
            c.set_text("-")

    @w.guarded
    def cancel(self):
        for edit in (self.dest, self.volume, self.driver, self.notes, self.weight, self.code_edit):
            edit.clear()
        self.truck_combo.setEditText("")
        self.truck_info.setText("")
        self._clear_results()
        self.info.setText("")
        self.truck, self.loaded_plate = None, ""
        self.open_id, self.first_weight, self.last_done = None, 0, None
        self._show_newbox(False)
        self.reload_lists()
        self.set_mode(0)
        self.focus_search()

    def _typed_plate(self):
        text = self.truck_combo.currentText()
        return text.split("·")[0].strip() if "·" in text else text.strip()

    # ---------------------------------------------------------------- memilih truk
    def on_pick(self, index):
        plate = self.truck_combo.itemData(index)
        if plate:
            self.truck_combo.setEditText(plate)
        self.commit()

    def on_waiting_click(self, row, col):
        item = self.waiting.item(row, 3)
        if item is not None and self.mode in (0, 3, 1, 2):
            self.truck_combo.setEditText(item.text())
            self.commit()

    @w.guarded
    def commit(self):
        text = self._typed_plate()
        if not util.normalize_plate(text):
            raise UserError("Pilih atau ketik nomor polisi / kode truk.")
        truck = masterdata.find_truck(text)
        if truck is None:
            self._new_plate(text)
        else:
            self._load(truck)

    def _new_plate(self, text):
        display = util.format_plate(text)
        self.truck, self.loaded_plate = None, util.normalize_plate(display)
        self.open_id, self.first_weight, self.last_done = None, 0, None
        self.truck_combo.setEditText(display)
        self._clear_results()
        self.truck_info.setText("Belum terdaftar di database")
        w.set_tone(self.truck_info, "warn")
        self.new_label.setText("%s belum ada di database. Simpan agar tidak perlu diketik lagi." % display)
        self._show_newbox(True)
        self.info.setText("")
        self.set_mode(1)
        self.weight.setFocus()

    def _load(self, truck):
        if not truck["active"]:
            raise UserError("Truk ini berstatus nonaktif. Hubungi Supervisor.")
        self.truck, self.loaded_plate = truck, truck["plate"]
        self.truck_combo.setEditText(truck["plate_display"])
        self._show_newbox(False)
        parts = [truck["truck_code"], truck["truck_type"], ("Sopir: %s" % truck["driver"]) if truck["driver"] else None]
        self.truck_info.setText("   ·   ".join(p for p in parts if p) or "Truk terdaftar")
        w.set_tone(self.truck_info, "muted")
        self.last_done = None
        self._clear_results()
        open_trx = weighing.find_open(truck["plate_display"])
        if open_trx:
            self.open_id = open_trx["id"]
            self.first_weight = open_trx["first_weight"]
            for combo, key in ((self.customer, "customer_id"), (self.material, "material_id")):
                combo.setCurrentIndex(combo.findData(open_trx[key]))
            self.supplier.setCurrentIndex(self.supplier.findData(open_trx["supplier_id"] or 0))
            self.dest.setText(open_trx["destination"] or "")
            self.driver.setText(open_trx["driver_name"] or "")
            self.notes.setText(open_trx["notes"] or "")
            self.volume.setText(("%g" % open_trx["volume_m3"]) if open_trx["volume_m3"] else "")
            self.info.setText("Transaksi terbuka %s  ·  %s  ·  %s  ·  timbangan 1: %s" % (
                open_trx["trx_number"], open_trx["customer"], open_trx["material"],
                util.format_weight(self.first_weight, settings.get("unit"))))
            self.set_mode(2)
        else:
            self.open_id, self.first_weight = None, 0
            if not self.driver.text().strip():
                self.driver.setText(truck["driver"] or "")
            self.info.setText("")
            self.set_mode(1)
        self.weight.setFocus()

    @w.guarded
    def save_new_truck(self):
        """Simpan nomor polisi baru ke database langsung dari dashboard (tanpa lewat Master Data)."""
        masterdata.register_truck(self._typed_plate(), self.code_edit.text(), self.driver.text())
        row = masterdata.find_truck(self._typed_plate())
        self.reload_trucks()
        self.code_edit.clear()
        w.notify("Truk %s tersimpan ke database" % row["plate_display"])
        self._load(row)

    def _check_loaded(self):
        if self.mode in (1, 2) and util.normalize_plate(self._typed_plate()) != self.loaded_plate:
            raise UserError("Nomor polisi diubah. Tekan Enter atau pilih truk dari daftar untuk memuat ulang.")

    # ---------------------------------------------------------------- berat
    def on_enter(self):
        if self.mode == 1:
            self.do_first()
        elif self.mode == 2:
            self.do_second()

    def poll_scale(self):
        bad = self.scale.device_fed and not self.scale.healthy()
        self.scale_lbl.setText("Timbangan: " + self.scale.status_text())
        w.set_tone(self.scale_lbl, "error" if bad else "muted")
        self.weight.setReadOnly(self.scale.device_fed)
        if self.scale.device_fed and self.mode in (1, 2):
            reading = self.scale.read()
            if reading is not None:
                self.weight.setText(str(reading.weight))

    def _read_weight(self):
        weight = util.quantize(util.parse_weight(self.weight.text()), settings.get_int("precision", 1))
        if self.scale.device_fed:
            reading = self.scale.read()
            if reading is None:
                raise UserError("Tidak ada data dari timbangan.")
            if not reading.stable:
                raise UserError("Berat belum stabil. Tunggu sampai stabil.")
        return weight

    def _read_volume(self):
        text = self.volume.text().strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            raise UserError("Volume harus berupa angka.")

    # ---------------------------------------------------------------- aksi penimbangan
    @w.guarded
    def do_first(self):
        self._check_loaded()
        if self.mode != 1:
            raise UserError("Pilih truk dulu. Timbangan pertama hanya untuk truk tanpa transaksi terbuka.")
        weight = self._read_weight()
        if self.customer.currentIndex() < 0:
            raise UserError("Pilih pelanggan.")
        if self.material.currentIndex() < 0:
            raise UserError("Pilih mutu beton / material.")
        volume = self._read_volume()
        new_truck = self.truck is None
        plate = self.truck["plate_display"] if self.truck is not None else self._typed_plate()
        res = weighing.start_first(
            plate, self.customer.currentData(), self.material.currentData(), weight,
            supplier_id=self.supplier.currentData() or None, destination=self.dest.text().strip(),
            driver=self.driver.text().strip(), volume=volume, notes=self.notes.text().strip(),
            create_truck=new_truck, truck_code=self.code_edit.text())
        for message in res["warnings"]:
            w.warn(self, message)
        shown = util.format_plate(plate)
        self.cancel()
        self.info.setText("Timbangan pertama tersimpan: %s  ·  %s  ·  %s. Truk boleh keluar." %
                          (res["number"], shown, util.format_weight(weight, settings.get("unit"))))
        w.notify("Timbangan pertama tersimpan%s" % (" - truk baru %s ikut disimpan" % shown if new_truck else ""))
        self.refresh_stats()

    @w.guarded
    def do_second(self):
        self._check_loaded()
        if self.mode != 2:
            raise UserError("Pilih truk yang sedang menunggu timbangan kedua.")
        weight = self._read_weight()
        prev = weighing.preview_second(self.open_id, weight)
        if prev["warnings"] and not w.ask(self, "\n".join(prev["warnings"]) + "\n\nTetap simpan?", yes="Tetap simpan", no="Batal"):
            return
        weighing.complete_second(self.open_id, weight)
        self.last_done = self.open_id
        unit = settings.get("unit")
        self.r_gross.set_text(util.format_weight(prev["gross"], unit))
        self.r_tare.set_text(util.format_weight(prev["tare"], unit))
        self.r_net.set_text(util.format_weight(prev["net"], unit), tone="ok")
        self.r_vol.set_text(util.format_volume(prev["net_m3"]), tone="ok")
        self.set_mode(3)
        self.refresh_stats()
        if w.ask(self, "Transaksi selesai. Cetak tiket sekarang?", yes="Cetak", no="Nanti"):
            self.do_print()

    @w.guarded
    def do_print(self):
        if not self.last_done:
            raise UserError("Belum ada transaksi selesai untuk dicetak. Cetak ulang dilakukan dari menu Transaksi.")
        ticket.print_ticket(self.last_done, parent=self)
        self.btn_print.setEnabled(can("reprint"))

    # ---------------------------------------------------------------- statistik & volume
    def refresh_stats(self):
        try:
            s = weighing.today_stats()
            whole = lambda v: str(int(round(v)))
            self.c_count.set_number(s["count"], whole, tone="ok")
            self.c_net.set_number(s["net_kg"] / 1000.0, lambda v: util.format_decimal(v) + " ton",
                                  sub="%s kg" % util.format_int(s["net_kg"]))
            self.c_vol.set_number(s["net_m3"], lambda v: util.format_decimal(v) + " m³", tone="ok",
                                  sub="Densitas %s kg/m³  ·  tercatat %s" % (util.format_int(weighing.density()),
                                                                              util.format_volume(s["recorded_m3"])))
            self.c_wait.set_number(s["waiting"], whole, tone="warn" if s["waiting"] else None)
            self._fill_volume(weighing.volume_by_material_today(), s["net_m3"])
            rows = [tuple(r) for r in weighing.open_transactions()]
            w.fill_table(self.waiting, WAITING_HEADERS, rows, hidden=(0,))
        except Exception:
            logger.exception("Refresh dashboard gagal")

    def _fill_volume(self, rows, total):
        sig = (tuple(rows), weighing.density())
        if sig == self._vol_sig:
            return
        self._vol_sig = sig
        while self.vol_rows.count():
            item = self.vol_rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.vol_total.setText(util.format_volume(total))
        if not rows:
            self.vol_hint.setText("Belum ada pengiriman selesai hari ini.")
            return
        self.vol_hint.setText("Netto kg ÷ densitas %s kg/m³ = volume (m³)." % util.format_int(weighing.density()))
        biggest = max(r[3] for r in rows) or 1.0
        for name, count, net_kg, m3 in rows:
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(5)
            top = QHBoxLayout()
            top.addWidget(w.label(name))
            top.addStretch(1)
            top.addWidget(w.label("%s  ·  %d kirim" % (util.format_volume(m3), count), role="muted"))
            bl.addLayout(top)
            bar = w.BarWidget()
            bl.addWidget(bar)
            self.vol_rows.addWidget(box)
            bar.set_fraction(m3 / biggest)
