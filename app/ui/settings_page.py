import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QScrollArea, QVBoxLayout, QWidget)

from app import paths
from app.errors import UserError
from app.authentication.session import can
from app.services import audit, backup, settings, storage
from app.printing import ticket
from app.scripting import lua_engine
from app.ui import theme
from app.ui import widgets as w
from app.ui.template_designer import TemplateDesigner

NUMERIC = {"baud": (300, 115200), "databits": (5, 8), "stopbits": (1, 2), "tcp_port": (1, 65535), "precision": (1, 100),
           "density_kg_m3": (1000, 4000), "copies": (1, 5), "margin_mm": (0, 30), "paper_w_mm": (40, 400),
           "paper_h_mm": (60, 1000), "timeout_min": (0, 480)}
THEMES = [("dark", "Gelap"), ("light", "Terang")]


def _ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


def _printers():
    try:
        from PyQt5.QtPrintSupport import QPrinterInfo
        return [""] + list(QPrinterInfo.availablePrinterNames())
    except Exception:
        return [""]


class CodeEditorDialog(w.FadeDialog):
    """Mode lanjutan: edit kode Lua template secara manual (divalidasi sebelum disimpan)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scaler")
        self.resize(940, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        lay.addWidget(w.label("Kode Lua template tiket", role="value", size="md"))
        lay.addWidget(w.label("Mode lanjutan. Untuk mengatur tata letak secara visual gunakan Desain Template.",
                              role="subtitle"))
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 10pt;")
        self.editor.setPlainText(ticket.template_source())
        lay.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        prev, save = w.btn("Pratinjau"), w.btn("Simpan", "primary", 110)
        reset, close = w.btn("Kembalikan bawaan", "ghost"), w.btn("Tutup", "ghost")
        prev.clicked.connect(self.preview)
        save.clicked.connect(self.save)
        reset.clicked.connect(self.reset)
        close.clicked.connect(self.accept)
        row.addWidget(prev)
        row.addStretch(1)
        row.addWidget(reset)
        row.addWidget(close)
        row.addWidget(save)
        lay.addLayout(row)

    @w.guarded
    def preview(self):
        ticket.show_preview(ticket.ticket_html(None, source=self.editor.toPlainText(), strict=True), self)

    @w.guarded
    def save(self):
        ticket.save_template(self.editor.toPlainText())
        w.notify("Template tersimpan. Berlaku untuk cetakan berikutnya.")

    @w.guarded
    def reset(self):
        if w.ask(self, "Kembalikan template ke bawaan? Perubahan Anda akan hilang.", yes="Kembalikan", no="Batal", danger=True):
            ticket.reset_template()
            self.editor.setPlainText(ticket.template_source())


class SettingsPage(QWidget):
    def __init__(self, scale, on_restored, on_theme):
        super().__init__()
        self.setObjectName("page")
        self.scale, self.on_restored, self.on_theme = scale, on_restored, on_theme
        self.fields = {}
        self.path_labels = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 8, 30, 20)
        outer.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(0, 0, 8, 0)
        self.col.setSpacing(16)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        form, _ = self.section("Tampilan")
        self.combo(form, "theme", "Tema", [label for _key, label in THEMES])

        form, _ = self.section("Perusahaan", "Tampil di kepala tiket.")
        for key, text in (("company_name", "Nama perusahaan"), ("company_address", "Alamat"), ("company_phone", "Telepon"),
                          ("company_email", "Email"), ("company_tax_id", "NPWP")):
            self.text(form, key, text)
        self.path_row(form, "logo_path", "Logo (png / jpg)", folder=False)

        form, v = self.section("Timbangan", "Manual = berat diketik. Serial / TCP = berat dibaca dari indikator (input manual dikunci, wajib stabil).")
        self.combo(form, "scale_type", "Jenis timbangan", ["Manual", "Serial", "TCP"])
        self.serial_box, sform = self._group(v)
        self.combo(sform, "com_port", "COM port", _ports(), editable=True)
        self.combo(sform, "baud", "Baud rate", ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"], editable=True)
        self.combo(sform, "databits", "Data bits", ["7", "8"])
        self.combo(sform, "parity", "Parity", ["None", "Even", "Odd"])
        self.combo(sform, "stopbits", "Stop bits", ["1", "2"])
        self.tcp_box, tform = self._group(v)
        self.text(tform, "tcp_host", "Alamat IP / host indikator")
        self.text(tform, "tcp_port", "Port TCP")
        self.text(tform, "tcp_poll_cmd", "Perintah minta berat (opsional)")
        self.fields["tcp_poll_cmd"].setPlaceholderText("mis. W\\r\\n  - kosong bila indikator mengirim terus-menerus")
        self.fields["scale_type"].currentTextChanged.connect(self._toggle_scale_boxes)
        form2 = QFormLayout()
        form2.setHorizontalSpacing(18)
        form2.setVerticalSpacing(10)
        v.addLayout(form2)
        self.combo(form2, "precision", "Pembulatan berat (kg)", ["1", "5", "10"])
        self.combo(form2, "unit", "Satuan tampilan berat", ["KG", "TON"])
        self.text(form2, "density_kg_m3", "Densitas beton (kg/m³) untuk netto dalam volume")

        form, _ = self.section("Printer & kertas")
        self.combo(form, "printer", "Printer (kosong = default Windows)", _printers())
        self.combo(form, "paper", "Ukuran kertas", ticket.PAPERS)
        self.text(form, "paper_w_mm", "Lebar kertas thermal / kustom (mm)")
        self.text(form, "paper_h_mm", "Tinggi kertas thermal / kustom (mm)")
        self.text(form, "copies", "Jumlah salinan (1-5)")
        self.text(form, "margin_mm", "Margin (mm)")

        form, _ = self.section("Aplikasi")
        self.combo(form, "auto_backup", "Backup otomatis harian (1 = ya, 0 = tidak)", ["1", "0"])
        self.path_row(form, "backup_dir", "Folder backup (kosong = folder backups)", folder=True)
        self.combo(form, "timeout_min", "Auto-logout bila idle (menit, 0 = mati)", ["0", "5", "15", "30", "60"], editable=True)
        self.lua_lbl = QLabel("")
        self.lua_lbl.setWordWrap(True)
        form.addRow("Mesin Lua", self.lua_lbl)

        form, v = self.section("Folder & penyimpanan",
                               "Aplikasi, database, dan skrip Lua boleh berada di folder yang berbeda. "
                               "Perubahan folder berlaku setelah aplikasi dimulai ulang.")
        for key, text in (("home", "Folder data"), ("db", "Database"), ("lua", "Folder skrip Lua"), ("backup", "Folder backup"),
                          ("ini", "File konfigurasi")):
            lbl = w.label("", role="muted", wrap=True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.path_labels[key] = lbl
            form.addRow(text, lbl)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        b1, b2 = w.btn("Pindahkan folder data..."), w.btn("Pilih folder skrip Lua...")
        b1.clicked.connect(self.move_home)
        b2.clicked.connect(self.pick_lua_dir)
        prow.addWidget(b1)
        prow.addWidget(b2)
        prow.addStretch(1)
        v.addLayout(prow)
        self.col.addStretch(1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        for text, kind, fn in (("Simpan", "primary", self.save), ("Tes timbangan", None, self.test_scale),
                               ("Desain template", None, self.open_designer), ("Kode Lua", None, self.open_code),
                               ("Backup sekarang", None, self.do_backup), ("Restore", "danger", self.do_restore)):
            b = w.btn(text, kind or "default")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)

    # ---------------------------------------------------------------- pembuat field
    def section(self, title, hint=""):
        card, v = w.make_card(margins=(26, 20, 26, 22), spacing=10)
        v.addWidget(w.caption(title))
        if hint:
            v.addWidget(w.label(hint, role="subtitle", wrap=True))
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        v.addLayout(form)
        self.col.addWidget(card)
        return form, v

    @staticmethod
    def _group(parent_layout):
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        parent_layout.addWidget(box)
        return box, form

    def text(self, form, key, label):
        edit = QLineEdit()
        self.fields[key] = edit
        form.addRow(label, edit)

    def combo(self, form, key, label, items, editable=False):
        cb = QComboBox()
        cb.setEditable(editable)
        cb.addItems(items)
        self.fields[key] = cb
        form.addRow(label, cb)

    def path_row(self, form, key, label, folder):
        edit = QLineEdit()
        browse = w.btn("...", "default", 44)
        browse.setMinimumHeight(36)

        def pick():
            if folder:
                chosen = QFileDialog.getExistingDirectory(self, label)
            else:
                chosen, _ = QFileDialog.getOpenFileName(self, label, "", "Gambar (*.png *.jpg *.jpeg *.bmp)")
            if chosen:
                edit.setText(chosen)

        browse.clicked.connect(pick)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(edit, 1)
        rl.addWidget(browse)
        self.fields[key] = edit
        form.addRow(label, row)

    def _toggle_scale_boxes(self, kind):
        self.serial_box.setVisible(kind == "Serial")
        self.tcp_box.setVisible(kind == "TCP")

    @staticmethod
    def _get(widget):
        return (widget.currentText() if isinstance(widget, QComboBox) else widget.text()).strip()

    @staticmethod
    def _set(widget, value):
        if isinstance(widget, QComboBox):
            idx = widget.findText(value)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            elif widget.isEditable():
                widget.setEditText(value)
        else:
            widget.setText(value)

    def on_show(self):
        for key, widget in self.fields.items():
            if key == "theme":
                self._set(widget, dict(THEMES)[theme.mode()])
            else:
                self._set(widget, settings.get(key))
        self._toggle_scale_boxes(self._get(self.fields["scale_type"]))
        eng = lua_engine.get_engine()
        self.lua_lbl.setText("Aktif - template tiket & aturan bisnis memakai Lua." if eng.available else
                             "Tidak tersedia - memakai penerjemah tata letak & aturan bawaan. (%s)" % eng.error)
        self.path_labels["home"].setText(paths.BASE)
        self.path_labels["db"].setText(paths.DB_PATH)
        self.path_labels["lua"].setText(paths.LUA_DIR)
        self.path_labels["backup"].setText(backup.backup_dir())
        self.path_labels["ini"].setText(paths.INI_PATH or "(belum ada - dibuat saat folder diubah)")

    # ---------------------------------------------------------------- aksi
    @w.guarded
    def save(self):
        values = dict((k, self._get(wd)) for k, wd in self.fields.items() if k != "theme")
        for key, (lo, hi) in NUMERIC.items():
            v = values.get(key, "")
            if not v.isdigit() or not lo <= int(v) <= hi:
                raise UserError("Nilai '%s' harus angka antara %d dan %d." % (key, lo, hi))
        if values["scale_type"] == "Serial" and not values["com_port"]:
            raise UserError("Isi COM port untuk timbangan serial.")
        if values["scale_type"] == "TCP" and not values["tcp_host"]:
            raise UserError("Isi alamat IP / host indikator untuk timbangan TCP.")
        if values["logo_path"] and not os.path.isfile(values["logo_path"]):
            raise UserError("File logo tidak ditemukan.")
        settings.set_many(values)
        audit.log("UBAH PENGATURAN", "settings")
        mode = "light" if self._get(self.fields["theme"]) == "Terang" else "dark"
        if mode != theme.mode():
            self.on_theme(mode)
        self.scale.configure()
        w.info(self, "Pengaturan tersimpan. Status timbangan: " + self.scale.status_text())

    @w.guarded
    def test_scale(self):
        self.save()

    @w.guarded
    def open_designer(self):
        if not can("edit_template"):
            raise UserError("Hanya Admin yang dapat mengubah template tiket.")
        TemplateDesigner(self).exec_()

    @w.guarded
    def open_code(self):
        if not can("edit_template"):
            raise UserError("Hanya Admin yang dapat mengubah template tiket.")
        CodeEditorDialog(self).exec_()

    @w.guarded
    def do_backup(self):
        default = os.path.join(backup.backup_dir(), backup.default_name())
        path, _ = QFileDialog.getSaveFileName(self, "Simpan backup", default, "Database SQLite (*.db)")
        if path:
            backup.backup_to(path)
            audit.log("BACKUP", "database", None, None, path)
            w.info(self, "Backup tersimpan: " + path)

    @w.guarded
    def do_restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih file backup", backup.backup_dir(), "Database SQLite (*.db)")
        if not path:
            return
        if not w.ask(self, "Restore akan MENGGANTI seluruh data saat ini dengan isi file backup.\n"
                           "Backup otomatis data sekarang dibuat lebih dulu.\n\nLanjutkan?", yes="Restore", no="Batal", danger=True):
            return
        before = backup.restore(path)
        w.info(self, "Restore selesai.\nBackup data sebelumnya: %s\n\nAnda akan diminta login ulang." % before)
        self.on_restored("RESTORE")

    @w.guarded
    def move_home(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder data yang baru")
        if not folder:
            return
        if not w.ask(self, "Salin database, skrip Lua, dan aset ke:\n%s\n\nSetelah itu aplikasi harus ditutup dan dibuka lagi."
                     % folder, yes="Pindahkan", no="Batal"):
            return
        storage.move_data_home(folder)
        w.info(self, "Data sudah disalin ke:\n%s\n\nTutup lalu buka kembali Scaler untuk memakai folder baru." % folder)

    @w.guarded
    def pick_lua_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder skrip Lua")
        if not folder:
            return
        storage.set_lua_dir(folder)
        w.info(self, "Folder skrip Lua diatur ke:\n%s\n\nTutup lalu buka kembali Scaler agar berlaku." % folder)
