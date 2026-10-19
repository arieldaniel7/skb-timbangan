"""Desainer Template Tiket: seret & lepas elemen / field data ke tata letak, atur properti, pratinjau langsung.

Alur: palet (kiri) -> daftar tata letak (tengah, bisa diurutkan dengan seret) -> pratinjau kertas (kanan).
Hasilnya disimpan sebagai layout JSON + skrip Lua yang dihasilkan otomatis (lihat app/printing/layout.py)."""
import json

from PyQt5.QtCore import QByteArray, QMimeData, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea, QShortcut, QSpinBox, QSplitter,
                             QTextBrowser, QVBoxLayout, QWidget)

from app.printing import layout, ticket
from app.services import settings
from app.ui import widgets as w

MIME = "application/x-scaler-element"
PAPER_MM = {"A4": 210, "A5": 148, "Thermal 80mm": 80, "Thermal 58mm": 58}
ALIGNS = [("left", "Kiri"), ("center", "Tengah"), ("right", "Kanan")]
PROP_LABELS = {"text": "Teks", "label": "Label", "value": "Nilai", "align": "Rata", "bold": "Tebal",
               "size": "Ukuran (+/- pt)", "hide_empty": "Sembunyikan bila kosong", "show_if": "Tampil hanya jika",
               "left": "Kiri", "right": "Kanan", "left_name": "Nama kiri", "right_name": "Nama kanan"}


class PaletteList(QListWidget):
    """Daftar sumber: item bisa diseret ke daftar tata letak (payload JSON di MIME khusus)."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def mimeData(self, items):
        data = QMimeData()
        if items:
            data.setData(MIME, QByteArray(items[0].data(Qt.UserRole).encode("utf-8")))
        return data


class LayoutList(QListWidget):
    """Daftar tata letak: menerima drop dari palette dan bisa diurutkan dengan menyeret barisnya."""

    def __init__(self, on_dropped, on_reordered):
        super().__init__()
        self._on_dropped, self._on_reordered = on_dropped, on_reordered
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            payload = json.loads(bytes(event.mimeData().data(MIME)).decode("utf-8"))
            index = self.indexAt(event.pos())
            row = self.count()
            if index.isValid():
                row = index.row()
                if event.pos().y() > self.visualItemRect(self.item(row)).center().y():
                    row += 1
            event.acceptProposedAction()
            self._on_dropped(payload, row)
        else:
            super().dropEvent(event)
            self._on_reordered()


class CodeViewDialog(w.FadeDialog):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.setWindowTitle("Scaler")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.addWidget(w.label("Kode Lua hasil desain", role="value", size="md"))
        edit = QPlainTextEdit(text)
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        edit.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 10pt;")
        lay.addWidget(edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = w.btn("Tutup", "primary", 100)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


class TemplateDesigner(w.FadeDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scaler")
        self.resize(1280, 800)
        self.model = layout.TemplateModel(ticket.get_layout())
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(w.label("Desainer template tiket", role="title"))
        titles.addWidget(w.label("Seret elemen atau field dari kiri ke daftar tata letak (atau klik dua kali). "
                                 "Seret baris untuk mengurutkan.", role="subtitle"))
        head.addLayout(titles, 1)
        self.paper = QComboBox()
        self.paper.addItems(ticket.PAPERS)
        self.paper.setCurrentText(settings.get("paper"))
        self.paper.currentIndexChanged.connect(lambda _=0: self.refresh_preview())
        b_print, b_code = w.btn("Pratinjau cetak"), w.btn("Lihat kode Lua")
        b_reset, b_close, b_save = w.btn("Kembalikan bawaan", "ghost"), w.btn("Tutup", "ghost"), w.btn("Simpan", "primary", 110)
        b_print.clicked.connect(self.print_preview)
        b_code.clicked.connect(self.show_code)
        b_reset.clicked.connect(self.reset)
        b_close.clicked.connect(self.reject)
        b_save.clicked.connect(self.save)
        head.addWidget(w.label("Kertas", role="muted"))
        head.addWidget(self.paper)
        for b in (b_print, b_code, b_reset, b_close, b_save):
            head.addWidget(b)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_palette())
        split.addWidget(self._build_middle())
        split.addWidget(self._build_preview())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 5)
        split.setSizes([250, 440, 520])
        root.addWidget(split, 1)
        self.refresh_list(select=0 if self.model.layout else None)
        self.refresh_preview()

    # ---------------------------------------------------------------- pembangun UI
    def _palette_list(self, entries, kind):
        lst = PaletteList()
        for key, text in entries:
            item = QListWidgetItem(text)
            payload = {"kind": "element", "type": key} if kind == "element" else {"kind": "field", "key": key}
            item.setData(Qt.UserRole, json.dumps(payload))
            lst.addItem(item)
        lst.itemDoubleClicked.connect(self.on_palette_double_click)
        return lst

    def _build_palette(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(6)
        v.addWidget(w.caption("Elemen"))
        v.addWidget(self._palette_list([(t, label) for t, label, _ in layout.ELEMENTS], "element"), 5)
        v.addWidget(w.caption("Field data  (jadi baris label : nilai)"))
        v.addWidget(self._palette_list(layout.FIELDS, "field"), 7)
        return box

    def _build_middle(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 0, 8, 0)
        v.setSpacing(6)
        v.addWidget(w.caption("Tata letak tiket"))
        self.list = LayoutList(self.on_dropped, self.on_reordered)
        self.list.currentRowChanged.connect(lambda _row: self.rebuild_props())
        delete_key = QShortcut(QKeySequence(QKeySequence.Delete), self.list)
        delete_key.setContext(Qt.WidgetShortcut)      # hanya saat daftar yang fokus (bukan saat mengetik properti)
        delete_key.activated.connect(self.delete)
        v.addWidget(self.list, 6)
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, fn in (("Naik", lambda: self.move(-1)), ("Turun", lambda: self.move(1)),
                         ("Duplikat", self.duplicate), ("Hapus", self.delete)):
            b = w.btn(text, "danger" if text == "Hapus" else "default")
            b.setMinimumHeight(34)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        v.addWidget(w.caption("Properti elemen terpilih"))
        self.props_scroll = QScrollArea()
        self.props_scroll.setWidgetResizable(True)
        self.props_scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(self.props_scroll, 5)
        return box

    def _build_preview(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(w.caption("Pratinjau (data contoh)"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 4, 0, 4)
        self.paper_frame = QFrame()
        self.paper_frame.setObjectName("paper")
        pl = QVBoxLayout(self.paper_frame)
        pl.setContentsMargins(0, 0, 0, 0)
        self.browser = QTextBrowser()
        self.browser.setFrameShape(QFrame.NoFrame)
        self.browser.setMinimumHeight(720)
        pl.addWidget(self.browser)
        hl.addStretch(1)
        hl.addWidget(self.paper_frame)
        hl.addStretch(1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)
        return box

    # ---------------------------------------------------------------- sinkronisasi
    def refresh_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.model.layout:
            item = QListWidgetItem(layout.describe(e))
            item.setData(Qt.UserRole, json.dumps(e, ensure_ascii=False))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if select is not None and 0 <= select < self.list.count():
            self.list.setCurrentRow(select)
        self.rebuild_props()

    def refresh_preview(self):
        paper = self.paper.currentText()
        mm = PAPER_MM.get(paper) or max(40, settings.get_int("paper_w_mm", 80))
        self.paper_frame.setFixedWidth(int(mm * 3.78) + 2)
        items = layout.render_layout(self.model.layout, ticket.sample_data())
        self.browser.setHtml(ticket.items_to_html(items, paper, settings.get("logo_path")))

    def _changed(self, select=None):
        self.dirty = True
        self.refresh_list(select)
        self.refresh_preview()

    # ---------------------------------------------------------------- properti
    def rebuild_props(self):
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(4, 4, 12, 4)
        form.setVerticalSpacing(8)
        row = self.list.currentRow()
        if 0 <= row < len(self.model.layout):
            e = self.model.layout[row]
            form.addRow(w.label(layout.ELEMENT_LABELS.get(e["type"], e["type"]), role="value", size="sm"))
            for key, kind in layout.PROPS[e["type"]]:
                form.addRow(w.caption(PROP_LABELS.get(key, key)), self._prop_widget(key, kind, e.get(key)))
        else:
            form.addRow(w.label("Pilih elemen di daftar untuk mengubah propertinya.", role="muted", wrap=True))
        self.props_scroll.setWidget(host)

    def _prop_widget(self, key, kind, value):
        if kind == "str":
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            edit = QLineEdit(str(value or ""))
            edit.textEdited.connect(lambda text, k=key: self.on_prop(k, text))
            insert = QComboBox()
            insert.addItem("+ field", "")
            for fkey, flabel in layout.FIELDS:
                insert.addItem(flabel, fkey)
            insert.setMaximumWidth(140)
            insert.activated.connect(lambda i, e=edit, cb=insert, k=key: self._insert_field(e, cb, i, k))
            hl.addWidget(edit, 1)
            hl.addWidget(insert)
            return box
        if kind == "bool":
            check = QCheckBox()
            check.setChecked(bool(value))
            check.toggled.connect(lambda on, k=key: self.on_prop(k, on))
            return check
        if kind == "int":
            spin = QSpinBox()
            spin.setRange(-6, 14)
            spin.setValue(int(value or 0))
            spin.valueChanged.connect(lambda v, k=key: self.on_prop(k, v))
            return spin
        combo = QComboBox()
        if kind == "align":
            for data, text in ALIGNS:
                combo.addItem(text, data)
            combo.setCurrentIndex(max(0, combo.findData(value or "left")))
        else:  # cond
            combo.addItem("(selalu tampil)", "")
            for data, text in layout.CONDITIONS:
                combo.addItem(text, data)
            combo.setCurrentIndex(max(0, combo.findData(value or "")))
        combo.currentIndexChanged.connect(lambda i, cb=combo, k=key: self.on_prop(k, cb.itemData(i)))
        return combo

    def _insert_field(self, edit, combo, index, key):
        field = combo.itemData(index)
        if field:
            edit.insert("{%s}" % field)
            self.on_prop(key, edit.text())
        combo.setCurrentIndex(0)

    def on_prop(self, key, value):
        row = self.list.currentRow()
        if not 0 <= row < len(self.model.layout):
            return
        self.model.update(row, key, value)
        e = self.model.layout[row]
        item = self.list.item(row)
        item.setText(layout.describe(e))
        item.setData(Qt.UserRole, json.dumps(e, ensure_ascii=False))
        self.dirty = True
        self.refresh_preview()

    # ---------------------------------------------------------------- aksi daftar
    def add_payload(self, payload, row=None):
        if payload.get("kind") == "field":
            index = self.model.add_field(payload["key"], row)
        else:
            index = self.model.add(payload["type"], row)
        self._changed(select=index)

    def on_dropped(self, payload, row):
        self.add_payload(payload, row)

    def on_palette_double_click(self, item):
        current = self.list.currentRow()
        self.add_payload(json.loads(item.data(Qt.UserRole)), current + 1 if current >= 0 else None)

    def on_reordered(self):
        order = [json.loads(self.list.item(i).data(Qt.UserRole)) for i in range(self.list.count())]
        self.model.set_layout(order)
        self._changed(select=self.list.currentRow())

    def move(self, delta):
        row = self.list.currentRow()
        if row >= 0:
            self._changed(select=self.model.move(row, delta))

    def duplicate(self):
        row = self.list.currentRow()
        if row >= 0:
            self._changed(select=self.model.duplicate(row))

    def delete(self):
        row = self.list.currentRow()
        if row >= 0:
            self.model.remove(row)
            self._changed(select=min(row, len(self.model.layout) - 1))

    # ---------------------------------------------------------------- tombol atas
    @w.guarded
    def save(self):
        ticket.save_layout(self.model.layout)
        self.dirty = False
        w.notify("Template tersimpan. Berlaku untuk cetakan berikutnya.")

    @w.guarded
    def print_preview(self):
        items = layout.render_layout(self.model.layout, ticket.sample_data())
        ticket.show_preview(ticket.items_to_html(items, self.paper.currentText(), settings.get("logo_path")), self)

    @w.guarded
    def show_code(self):
        CodeViewDialog(self, self.model.to_lua()).exec_()

    @w.guarded
    def reset(self):
        if w.ask(self, "Kembalikan tata letak ke bawaan? Perubahan yang belum disimpan akan hilang.", yes="Kembalikan",
                 no="Batal", danger=True):
            self.model.set_layout(layout.DEFAULT_LAYOUT)
            self._changed(select=0)

    def reject(self):
        if self.dirty and not w.ask(self, "Ada perubahan yang belum disimpan. Tutup tanpa menyimpan?", yes="Tutup",
                                    no="Kembali", danger=True):
            return
        super().reject()
