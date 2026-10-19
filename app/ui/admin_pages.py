import datetime

from PyQt5.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from app.authentication import auth
from app.authentication.session import session
from app.services import audit
from app.ui import widgets as w


class UsersPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 8, 30, 24)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        add, edit, pw = w.btn("Tambah", "primary"), w.btn("Ubah"), w.btn("Reset password")
        add.clicked.connect(self.add)
        edit.clicked.connect(self.edit)
        pw.clicked.connect(self.reset_pw)
        for b in (add, edit, pw):
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.table = w.make_table()
        lay.addWidget(self.table, 1)

    def on_show(self):
        self.load()

    @w.guarded
    def load(self):
        rows = [[r["id"], r["username"], r["full_name"], r["role"], "Aktif" if r["active"] else "Nonaktif"]
                for r in auth.list_users()]
        w.fill_table(self.table, ["id", "Username", "Nama", "Role", "Status"], rows, hidden=(0,))

    @w.guarded
    def add(self):
        res = w.prompt_fields(self, "Tambah pengguna", [
            {"key": "u", "label": "Username", "required": True},
            {"key": "n", "label": "Nama lengkap", "required": True},
            {"key": "r", "label": "Role", "options": list(auth.ROLES), "value": "OPERATOR"},
            {"key": "p", "label": "Password awal (min. 6 karakter)", "required": True, "password": True}])
        if res is not None:
            auth.create_user(res["u"], res["n"], res["r"], res["p"])
            self.load()
            w.notify("Pengguna ditambahkan")

    def _row(self):
        uid = w.selected_value(self.table, 0)
        r = self.table.currentRow()
        return uid, [self.table.item(r, c).text() for c in range(5)]

    @w.guarded
    def edit(self):
        uid, vals = self._row()
        res = w.prompt_fields(self, "Ubah pengguna", [
            {"key": "n", "label": "Nama lengkap", "required": True, "value": vals[2]},
            {"key": "r", "label": "Role", "options": list(auth.ROLES), "value": vals[3]},
            {"key": "a", "label": "Status", "options": ["Aktif", "Nonaktif"], "value": vals[4]}])
        if res is not None:
            auth.update_user(uid, res["n"], res["r"], res["a"] == "Aktif")
            self.load()

    @w.guarded
    def reset_pw(self):
        uid, vals = self._row()
        res = w.prompt_fields(self, "Reset password - " + vals[1], [
            {"key": "p", "label": "Password baru (min. 6 karakter)", "required": True, "password": True}])
        if res is not None:
            auth.change_password(uid, res["p"])
            w.info(self, "Password diubah." if uid == session.user["id"] else
                   "Password diubah. Pengguna diminta menggantinya saat login berikutnya.")


class AuditPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 8, 30, 24)
        lay.setSpacing(14)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.d_from = w.date_edit(datetime.date.today() - datetime.timedelta(days=7))
        self.d_to = w.date_edit()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Cari aksi / pengguna / isi...")
        self.text.returnPressed.connect(self.load)
        go = w.btn("Tampilkan", "primary")
        go.clicked.connect(self.load)
        bar.addWidget(self.d_from)
        bar.addWidget(w.label("s/d", role="muted"))
        bar.addWidget(self.d_to)
        bar.addWidget(self.text, 1)
        bar.addWidget(go)
        lay.addLayout(bar)
        self.table = w.make_table()
        lay.addWidget(self.table, 1)

    def on_show(self):
        self.load()

    @w.guarded
    def load(self):
        rows = [tuple(r) for r in audit.search(w.py_date(self.d_from), w.py_date(self.d_to), self.text.text())]
        w.fill_table(self.table, ["Waktu", "Pengguna", "Aksi", "Tabel", "ID Data", "Nilai Lama", "Nilai Baru", "Komputer"], rows)
