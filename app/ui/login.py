from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QLabel, QLineEdit, QVBoxLayout

from app.errors import UserError
from app.authentication import auth
from app.ui import widgets as w


class LoginDialog(w.FadeDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scaler")
        self.setFixedSize(420, 470)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(42, 36, 42, 34)
        lay.setSpacing(6)
        mark = QLabel("S")
        mark.setObjectName("mark")
        mark.setAlignment(Qt.AlignCenter)
        lay.addWidget(mark)
        lay.addSpacing(10)
        lay.addWidget(w.label("Selamat datang", role="title"))
        lay.addWidget(w.label("Jembatan timbang & tiket pengiriman beton", role="subtitle"))
        lay.addSpacing(22)
        lay.addWidget(w.caption("Operator"))
        self.user = QComboBox()
        for uid, text in auth.login_choices():
            self.user.addItem(text, uid)
        lay.addWidget(self.user)
        lay.addSpacing(8)
        lay.addWidget(w.caption("Password"))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.returnPressed.connect(self.do_login)
        lay.addWidget(self.pw)
        lay.addSpacing(22)
        ok = w.btn("Masuk", "primary")
        ok.setMinimumHeight(46)
        ok.setDefault(True)
        ok.clicked.connect(self.do_login)
        lay.addWidget(ok)
        lay.addStretch(1)
        self.pw.setFocus()

    def do_login(self):
        if self.user.currentIndex() < 0:
            w.warn(self, "Pilih operator.")
            return
        try:
            auth.login(self.user.currentData(), self.pw.text())
        except UserError as exc:
            w.warn(self, str(exc))
            self.pw.selectAll()
            self.pw.setFocus()
            return
        self.accept()
