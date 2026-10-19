from PyQt5.QtWidgets import QButtonGroup, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from app.authentication.session import can
from app.services import masterdata
from app.ui import widgets as w


class MasterDataPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.cur = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 8, 30, 24)
        lay.setSpacing(14)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, e in enumerate(masterdata.ENTITIES):
            b = w.btn(e.title, "tab", 150, checkable=True)
            b.clicked.connect(lambda _=False, idx=i: self.select_tab(idx))
            self.group.addButton(b, i)
            tabs.addWidget(b)
            if i == 0:
                b.setChecked(True)
        tabs.addStretch(1)
        lay.addLayout(tabs)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari...")
        self.search_edit.returnPressed.connect(self.load)
        self.b_add, self.b_edit = w.btn("Tambah", "primary"), w.btn("Ubah")
        self.b_toggle = w.btn("Aktif / Nonaktif")
        self.b_add.clicked.connect(self.add)
        self.b_edit.clicked.connect(self.edit)
        self.b_toggle.clicked.connect(self.toggle)
        bar.addWidget(self.search_edit, 1)
        for b in (self.b_add, self.b_edit, self.b_toggle):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = w.make_table()
        lay.addWidget(self.table, 1)

    def on_show(self):
        editable = can("edit_master")
        for b in (self.b_add, self.b_edit, self.b_toggle):
            b.setEnabled(editable)
        self.load()

    @property
    def entity(self):
        return masterdata.ENTITIES[self.cur]

    def select_tab(self, idx):
        self.cur = idx
        self.search_edit.clear()
        self.load()

    @w.guarded
    def load(self):
        e = self.entity
        rows = []
        for r in masterdata.list_rows(e.table, self.search_edit.text()):
            vals = list(r)
            vals[-1] = "Aktif" if vals[-1] else "Nonaktif"
            rows.append(vals)
        w.fill_table(self.table, ["id"] + [f.label for f in e.fields] + ["Status"], rows, hidden=(0,))

    def _fields(self, row=None):
        out = []
        for f in self.entity.fields:
            value = "" if row is None or row[f.key] is None else str(row[f.key])
            out.append({"key": f.key, "label": f.label, "value": value, "required": f.required, "int": f.kind == "int"})
        return out

    @w.guarded
    def add(self):
        res = w.prompt_fields(self, "Tambah " + self.entity.title, self._fields())
        if res is not None:
            masterdata.create(self.entity.table, res)
            self.load()
            w.notify("%s ditambahkan" % self.entity.title)

    @w.guarded
    def edit(self):
        row_id = w.selected_value(self.table, 0)
        row = masterdata.get(self.entity.table, row_id)
        res = w.prompt_fields(self, "Ubah " + self.entity.title, self._fields(row))
        if res is not None:
            masterdata.update(self.entity.table, row_id, res)
            self.load()
            w.notify("Perubahan disimpan")

    @w.guarded
    def toggle(self):
        masterdata.toggle_active(self.entity.table, w.selected_value(self.table, 0))
        self.load()
