import datetime
import time

from PyQt5.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QShortcut,
                             QVBoxLayout, QWidget)

from app.authentication import auth
from app.authentication.session import can, session
from app.services import settings
from app.ui import theme
from app.ui import widgets as w
from app.ui.admin_pages import AuditPage, UsersPage
from app.ui.dashboard import DashboardPage
from app.ui.master_data import MasterDataPage
from app.ui.reports_page import ReportsPage
from app.ui.settings_page import SettingsPage
from app.ui.transactions import TransactionsPage

DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November",
          "Desember"]
EXPANDED, COLLAPSED = 236, 76


class MainWindow(QMainWindow):
    def __init__(self, scale_service):
        super().__init__()
        self.scale = scale_service
        self.relogin = False
        self.current = ""
        self.pages, self.nav, self.titles = {}, {}, {}
        self._last_activity = time.time()
        self._timeout = settings.get_int("timeout_min", 30)
        self._collapsed = False
        self.setWindowTitle("Scaler - Jembatan Timbang")
        self.resize(1360, 820)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- sidebar ----------
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(EXPANDED)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 20, 0, 14)
        sl.setSpacing(2)
        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(20, 0, 12, 18)
        mark = QLabel("S")
        mark.setObjectName("mark")
        mark.setAlignment(Qt.AlignCenter)
        self.brand_text = w.label("Scaler", role="value", size="md")
        bl.addWidget(mark)
        bl.addWidget(self.brand_text)
        bl.addStretch(1)
        sl.addWidget(brand)

        items = [
            ("dash", "Dashboard", "dashboard", None, lambda: DashboardPage(self.scale), "F1 / F2"),
            ("trx", "Transaksi", "list", "view_trx", TransactionsPage, "F7"),
            ("master", "Master Data", "database", "view_trx", MasterDataPage, "F8"),
            ("report", "Laporan", "chart", "reports", ReportsPage, "F9"),
            ("users", "Pengguna", "users", "manage_users", UsersPage, ""),
            ("audit", "Audit Log", "audit", "audit", AuditPage, ""),
            ("settings", "Pengaturan", "gear", "settings", lambda: SettingsPage(self.scale, self.force_relogin, self.set_theme),
             ""),
        ]
        self.stack = w.FadeStack()
        for key, text, icon, perm, factory, hint in items:
            if perm and not can(perm):
                continue
            b = w.NavButton(text, icon)
            b.setToolTip(hint)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            sl.addWidget(b)
            self.nav[key], self.titles[key] = b, text
            page = factory()
            self.pages[key] = page
            self.stack.addWidget(page)
        sl.addStretch(1)
        self.collapse_btn = w.NavButton("Ciutkan menu", "chevron_left")
        self.collapse_btn.setCheckable(False)
        self.collapse_btn.clicked.connect(self.toggle_sidebar)
        self.logout_btn = w.NavButton("Keluar", "logout")
        self.logout_btn.setCheckable(False)
        self.logout_btn.clicked.connect(lambda: self.force_relogin("LOGOUT"))
        sl.addWidget(self.collapse_btn)
        sl.addWidget(self.logout_btn)

        # ---------- area kanan ----------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(76)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(30, 10, 30, 6)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = w.label("", role="title")
        self.subtitle = w.label("", role="subtitle")
        titles.addStretch(1)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        titles.addStretch(1)
        tl.addLayout(titles)
        tl.addStretch(1)
        self.scale_chip = w.label("", chip=True, tone="ok")
        self.user_chip = w.label("", chip=True)
        self.switch = w.ThemeSwitch(theme.is_dark())
        self.switch.toggled.connect(lambda dark: self.set_theme("dark" if dark else "light"))
        tl.addWidget(self.scale_chip)
        tl.addSpacing(8)
        tl.addWidget(self.user_chip)
        tl.addSpacing(14)
        tl.addWidget(self.switch)
        rl.addWidget(top)
        rl.addWidget(self.stack, 1)
        outer.addWidget(self.sidebar)
        outer.addWidget(right, 1)

        w.install_toast(self)
        self._bind_shortcuts()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QApplication.instance().installEventFilter(self)
        self.tick()
        self.go("dash")

    def _bind_shortcuts(self):
        def bind(key, fn):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

        dash = self.pages.get("dash")
        bind("F1", lambda: self.go("dash"))
        bind("F2", lambda: (self.go("dash"), dash.focus_search()))
        bind("F3", lambda: (self.go("dash"), dash.focus_search()))
        bind("F4", lambda: (self.go("dash"), dash.do_first()))
        bind("F5", lambda: (self.go("dash"), dash.do_second()))
        bind("F6", lambda: (self.go("dash"), dash.do_print()))
        bind("F7", lambda: self.go("trx"))
        bind("F8", lambda: self.go("master"))
        bind("F9", lambda: self.go("report"))
        bind("Esc", lambda: dash.cancel() if self.current == "dash" else None)

    # ---------- navigasi ----------
    def go(self, key):
        if key not in self.pages:
            return
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.current = key
        self.title.setText(self.titles[key])
        page = self.pages[key]
        self.stack.show_page(page)
        page.on_show()

    def toggle_sidebar(self):
        self._collapsed = not self._collapsed
        for b in list(self.nav.values()) + [self.collapse_btn, self.logout_btn]:
            b.set_collapsed(self._collapsed)
        self.brand_text.setVisible(not self._collapsed)
        self.collapse_btn.icon_name = "chevron_right" if self._collapsed else "chevron_left"
        w.animate(self.sidebar, self.sidebar.width(), COLLAPSED if self._collapsed else EXPANDED,
                  lambda v: self.sidebar.setFixedWidth(int(v)), 260, QEasingCurve.InOutCubic, key="_anim_w")

    # ---------- tema ----------
    def set_theme(self, mode):
        """Ganti tema terang/gelap dengan cross-fade dari tampilan lama."""
        if mode == theme.mode():
            return
        root = self.centralWidget()
        overlay = QLabel(root)
        overlay.setPixmap(root.grab())
        overlay.setGeometry(root.rect())
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.show()
        overlay.raise_()
        theme.apply(QApplication.instance(), mode)
        settings.set("theme", mode)
        self.switch.set_dark(mode == "dark")
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(420)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(overlay.deleteLater)
        self._theme_anim = anim
        anim.start()

    # ---------- status, jam, auto-logout ----------
    def tick(self):
        u = session.user
        if u is None:
            return
        now = datetime.datetime.now()
        self.subtitle.setText("%s, %d %s %d   %s" % (DAYS[now.weekday()], now.day, MONTHS[now.month - 1], now.year,
                                                      now.strftime("%H:%M:%S")))
        self.user_chip.setText("%s  ·  %s" % (u["full_name"], u["role"].title()))
        bad = self.scale.device_fed and not self.scale.healthy()
        self.scale_chip.setText(self.scale.status_text())
        w.set_tone(self.scale_chip, "error" if bad else "ok")
        if self._timeout > 0 and time.time() - self._last_activity >= self._timeout * 60:
            self.force_relogin("SESSION TIMEOUT")

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress):
            self._last_activity = time.time()
        return False

    def force_relogin(self, reason="LOGOUT"):
        self.timer.stop()
        self.relogin = True
        auth.logout(reason)
        self.close()
