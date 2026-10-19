"""Komponen UI bersama: tombol & navigasi beranimasi, kartu statistik, switch tema, toast, transisi halaman,
dialog, tabel. Semua warna diambil dari tema aktif (terang/gelap) saat digambar."""
import datetime
import functools
import math

from PyQt5.QtCore import (QDate, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                          pyqtSignal)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from app import log, util
from app.errors import UserError
from app.ui import icons, theme

logger = log.get(__name__)


# ---- warna & util gaya ----------------------------------------------------------------------
def color(name):
    return QColor(theme.tokens()[name])


def mix(a, b, t):
    t = max(0.0, min(1.0, float(t)))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_tone(widget, tone):
    widget.setProperty("tone", tone or "")
    repolish(widget)


def label(text="", role=None, tone=None, wrap=False, chip=False, size=None):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if size:
        lbl.setProperty("size", size)
    if tone:
        lbl.setProperty("tone", tone)
    if chip:
        lbl.setProperty("chip", True)
    lbl.setWordWrap(wrap)
    return lbl


def caption(text):
    return label(text.upper(), role="caption")


def hline():
    f = QFrame()
    f.setObjectName("hline")
    f.setFixedHeight(1)
    return f


def make_card(direction="v", margins=(20, 18, 20, 18), spacing=10):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame) if direction == "v" else QHBoxLayout(frame)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return frame, lay


def animate(owner, start, end, setter, ms=400, curve=QEasingCurve.OutCubic, key="_anim", on_finish=None):
    """Animasi nilai float start->end; setter(v) dipanggil tiap frame. Animasi lama pada owner dihentikan."""
    old = getattr(owner, key, None)
    if old is not None:
        old.stop()
    anim = QVariantAnimation(owner)
    anim.setDuration(ms)
    anim.setEasingCurve(curve)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.valueChanged.connect(lambda v: setter(float(v)))
    if on_finish is not None:
        anim.finished.connect(on_finish)
    setattr(owner, key, anim)
    anim.start()
    return anim


# ---- tombol --------------------------------------------------------------------------------
class Button(QPushButton):
    """Tombol rata modern; transisi hover halus. kind: default | primary | danger | ghost | tab."""

    def __init__(self, text="", kind="default"):
        super().__init__(text)
        self.kind = kind
        self._h = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        f = self.font()
        f.setBold(True)
        f.setPointSizeF(9.5)
        self.setFont(f)

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def sizeHint(self):
        return QSize(max(96, self.fontMetrics().horizontalAdvance(self.text()) + 40), 38)

    def _to(self, target):
        animate(self, self._h, target, self._set_h, 140, QEasingCurve.OutCubic)

    def _set_h(self, v):
        self._h = v
        self.update()

    def enterEvent(self, event):
        self._to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        tk = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isCheckable() and self.isChecked()
        kind = self.kind
        white, black = QColor("#FFFFFF"), QColor("#000000")
        if kind == "primary" or (kind == "tab" and checked):
            base, fg, border = QColor(tk["accent"]), QColor(tk["accent_fg"]), QColor(tk["accent"])
            hover = mix(base, white if theme.is_dark() else black, 0.16 if theme.is_dark() else 0.10)
            border_hover = hover
        elif kind == "danger":
            base, fg, border = QColor(tk["error"]), QColor("#FFFFFF"), QColor(tk["error"])
            hover = mix(base, white, 0.14)
            border_hover = hover
        elif kind == "ghost":
            base, fg, border = QColor(0, 0, 0, 0), QColor(tk["text"]), QColor(0, 0, 0, 0)
            hover = QColor(tk["hover"])
            border_hover = QColor(tk["hover"])
        else:
            base, fg, border = QColor(tk["surface"]), QColor(tk["text"]), QColor(tk["border"])
            hover = QColor(tk["hover"])
            border_hover = QColor(tk["accent"])
        bg = mix(base, hover, self._h)
        if self.isDown():
            bg = bg.darker(108)
        line = mix(border, border_hover, self._h)
        if self.hasFocus():
            line = QColor(tk["accent"])
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setPen(QPen(line, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, 10, 10)
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


def btn(text, kind="default", width=None, checkable=False):
    b = Button(text, kind)
    b.setCheckable(checkable)
    if width:
        b.setMinimumWidth(width)
    return b


class NavButton(QPushButton):
    """Item sidebar: ikon + teks, latar & garis aksen beranimasi, bisa diciutkan jadi ikon saja."""

    def __init__(self, text, icon):
        super().__init__(text)
        self.full_text, self.icon_name = text, icon
        self.collapsed = False
        self._hover, self._checked = 0.0, 0.0
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.toggled.connect(lambda on: animate(self, self._checked, 1.0 if on else 0.0, self._set_checked, 220, key="_anim_c"))

    def _set_checked(self, v):
        self._checked = v
        self.update()

    def _set_hover(self, v):
        self._hover = v
        self.update()

    def set_collapsed(self, collapsed):
        self.collapsed = collapsed
        self.setToolTip(self.full_text if collapsed else "")
        self.update()

    def enterEvent(self, event):
        animate(self, self._hover, 1.0, self._set_hover, 140, key="_anim_h")
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate(self, self._hover, 0.0, self._set_hover, 140, key="_anim_h")
        super().leaveEvent(event)

    def paintEvent(self, event):
        tk = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pill = QRectF(10, 3, w - 20, h - 6)
        bg = mix(mix(QColor(0, 0, 0, 0), QColor(tk["hover"]), self._hover), QColor(tk["accent_soft"]), self._checked)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(pill, 11, 11)
        if self._checked > 0.01:
            p.setBrush(QColor(tk["accent"]))
            bar_h = h * 0.42 * self._checked
            p.drawRoundedRect(QRectF(0, (h - bar_h) / 2.0, 4, bar_h), 2, 2)
        fg = mix(QColor(tk["muted"]), QColor(tk["accent"]), self._checked)
        if self._hover > 0 and self._checked < 0.5:
            fg = mix(fg, QColor(tk["text"]), self._hover)
        icon_x = (w - 20) / 2.0 if self.collapsed else 24
        icons.draw(p, self.icon_name, QRectF(icon_x, (h - 20) / 2.0, 20, 20), fg)
        if not self.collapsed:
            f = self.font()
            f.setBold(self._checked > 0.5)
            p.setFont(f)
            p.setPen(mix(QColor(tk["text"]), QColor(tk["accent"]), self._checked))
            p.drawText(QRectF(58, 0, w - 66, h), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ThemeSwitch(QWidget):
    """Saklar terang/gelap dengan ikon bulan/matahari dan gerakan halus. toggled(True) = mode gelap."""
    toggled = pyqtSignal(bool)

    def __init__(self, dark=True):
        super().__init__()
        self._dark = dark
        self._pos = 1.0 if dark else 0.0
        self.setFixedSize(60, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Ganti tema terang / gelap")

    def is_dark(self):
        return self._dark

    def set_dark(self, dark, animated=True):
        if dark == self._dark:
            return
        self._dark = dark
        if animated:
            animate(self, self._pos, 1.0 if dark else 0.0, self._set_pos, 240, QEasingCurve.InOutCubic)
        else:
            self._set_pos(1.0 if dark else 0.0)

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def mousePressEvent(self, event):
        self.set_dark(not self._dark)
        self.toggled.emit(self._dark)

    def paintEvent(self, event):
        tk = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(tk["border"]), 1))
        p.setBrush(mix(QColor(tk["surface2"]), QColor(tk["accent_soft"]), self._pos))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2.0, h / 2.0)
        d = h - 8
        knob = QRectF(4 + (w - 8 - d) * self._pos, 4, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tk["accent"]))
        p.drawEllipse(knob)
        c, r = knob.center(), d / 2.0 - 4.5
        p.setBrush(QColor(tk["accent_fg"]))
        if self._pos > 0.5:     # bulan sabit
            moon = QPainterPath()
            moon.addEllipse(c, r + 1, r + 1)
            cut = QPainterPath()
            cut.addEllipse(QPointF(c.x() + r * 0.6, c.y() - r * 0.4), r * 0.9, r * 0.9)
            p.drawPath(moon.subtracted(cut))
        else:                   # matahari
            p.drawEllipse(c, r * 0.62, r * 0.62)
            pen = QPen(QColor(tk["accent_fg"]), 1.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            for k in range(8):
                a = math.radians(k * 45)
                p.drawLine(QPointF(c.x() + (r * 0.95) * math.cos(a), c.y() + (r * 0.95) * math.sin(a)),
                           QPointF(c.x() + (r * 1.3) * math.cos(a), c.y() + (r * 1.3) * math.sin(a)))


class BarWidget(QWidget):
    """Batang horizontal beranimasi (mis. volume per mutu beton)."""

    def __init__(self):
        super().__init__()
        self._f = 0.0
        self.setFixedHeight(10)

    def set_fraction(self, fraction):
        animate(self, self._f, max(0.0, min(1.0, fraction)), self._set, 650)

    def _set(self, v):
        self._f = v
        self.update()

    def paintEvent(self, event):
        tk = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tk["surface2"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2.0, h / 2.0)
        if self._f > 0.001:
            p.setBrush(QColor(tk["accent"]))
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._f), h), h / 2.0, h / 2.0)


class StatCard(QFrame):
    def __init__(self, title, size="lg", tone=None):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.title = caption(title)
        self.value = label("-", role="value", size=size, tone=tone)
        self.sub = label("", role="subtitle")
        self.sub.setVisible(False)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        self._num = 0.0

    def _sub(self, sub):
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))

    def set_text(self, text, tone=None, sub=None):
        self._num = 0.0
        self.value.setText(text)
        set_tone(self.value, tone)
        self._sub(sub)

    def set_number(self, number, fmt, tone=None, sub=None):
        """Hitung naik/turun dari nilai sebelumnya (animasi) lalu tampilkan fmt(number)."""
        start, self._num = self._num, float(number)
        set_tone(self.value, tone)
        self._sub(sub)
        animate(self, start, number, lambda v: self.value.setText(fmt(v)), 600,
                on_finish=lambda: self.value.setText(fmt(number)))


# ---- transisi halaman ------------------------------------------------------------------------
class FadeStack(QStackedWidget):
    def show_page(self, page, animate_it=True):
        if self.currentWidget() is page:
            return
        self.setCurrentWidget(page)
        if not animate_it:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        self._fade = anim
        anim.start()


def animate_height(widget, target, ms=220, on_finish=None):
    """Buka/tutup panel dengan menganimasikan tinggi maksimum."""
    start = widget.maximumHeight() if widget.maximumHeight() < 10000 else widget.sizeHint().height()
    animate(widget, start, target, lambda v: widget.setMaximumHeight(int(v)), ms, QEasingCurve.InOutCubic, key="_anim_h",
            on_finish=on_finish)


# ---- toast & dialog pesan ----------------------------------------------------------------------
class Toast(QFrame):
    def __init__(self, host):
        super().__init__(host)
        self.setObjectName("toast")
        self.host = host
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(420)
        lay.addWidget(self.label)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._leave)
        self._anims = []

    def show_message(self, text, tone="ok", ms=3200):
        self.label.setText(text)
        self.setProperty("tone", tone)
        repolish(self)
        self.adjustSize()
        x = max(10, self.host.width() - self.width() - 28)
        y = max(10, self.host.height() - self.height() - 28)
        self.move(x, y + 18)
        self.show()
        self.raise_()
        self._play(0.0, 1.0, QPointF(x, y + 18), QPointF(x, y), 220, hide_after=False)
        self._timer.start(ms)

    def _leave(self):
        pos = QPointF(self.pos())
        self._play(1.0, 0.0, pos, QPointF(pos.x(), pos.y() + 12), 260, hide_after=True)

    def _play(self, o_from, o_to, p_from, p_to, ms, hide_after):
        fade = QPropertyAnimation(self.effect, b"opacity", self)
        fade.setDuration(ms)
        fade.setStartValue(o_from)
        fade.setEndValue(o_to)
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(ms)
        slide.setStartValue(p_from.toPoint())
        slide.setEndValue(p_to.toPoint())
        slide.setEasingCurve(QEasingCurve.OutCubic)
        if hide_after:
            fade.finished.connect(self.hide)
        self._anims = [fade, slide]
        fade.start()
        slide.start()


_TOAST = None


def install_toast(host):
    global _TOAST
    _TOAST = Toast(host)


def notify(text, tone="ok", ms=None):
    """Pesan singkat non-blokir di pojok kanan bawah (tone: ok | warn | error)."""
    if _TOAST is not None:
        _TOAST.show_message(text, tone, ms or (5200 if tone != "ok" else 3200))
    else:
        logger.info("notify[%s]: %s", tone, text)


class FadeDialog(QDialog):
    """Dialog dengan fade-in saat tampil."""

    def showEvent(self, event):
        super().showEvent(event)
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(170)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        self._fade = anim
        anim.start()


class MessageDialog(FadeDialog):
    def __init__(self, parent, title, text, yes="OK", no=None, danger=False):
        super().__init__(parent)
        self.setWindowTitle("Scaler")
        self.setMinimumWidth(440)
        self.confirmed = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(14)
        lay.addWidget(label(title, role="value", size="md"))
        body = label(text, wrap=True)
        body.setMinimumWidth(380)
        lay.addWidget(body)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        if no:
            b_no = btn(no, "ghost", 100)
            b_no.clicked.connect(self.reject)
            row.addWidget(b_no)
        b_yes = btn(yes, "danger" if danger else "primary", 110)
        b_yes.setDefault(True)
        b_yes.clicked.connect(self._yes)
        row.addWidget(b_yes)
        lay.addLayout(row)

    def _yes(self):
        self.confirmed = True
        self.accept()


def _dialog(parent, title, text, **kw):
    dlg = MessageDialog(parent, title, text, **kw)
    dlg.exec_()
    return dlg.confirmed


def _short(text):
    return "\n" not in text and len(text) <= 170


def info(parent, text):
    if _TOAST is not None and _short(text):
        notify(text, "ok")
    else:
        _dialog(parent, "Informasi", text)


def warn(parent, text):
    if _TOAST is not None and _short(text):
        notify(text, "warn")
    else:
        _dialog(parent, "Perhatian", text)


def error(parent, text):
    _dialog(parent, "Terjadi kesalahan", text)


def ask(parent, text, yes="Ya", no="Tidak", title="Konfirmasi", danger=False):
    return _dialog(parent, title, text, yes=yes, no=no, danger=danger)


def run_guarded(parent, fn, *args):
    """Jalankan fn; UserError -> pesan ramah, error lain -> log + pesan umum (tanpa stack trace)."""
    try:
        return fn(*args)
    except UserError as exc:
        warn(parent, str(exc))
    except Exception:
        logger.exception("Error tak terduga di %s", getattr(fn, "__name__", fn))
        error(parent, "Terjadi kesalahan. Data tidak diubah.\nDetail teknis tersimpan di folder logs.")
    return None


def guarded(fn):
    """Dekorator slot Qt: argumen sinyal (mis. checked) diabaikan."""
    @functools.wraps(fn)
    def wrapper(self, *args):
        return run_guarded(self, fn, self)
    return wrapper


# ---- tabel & input -------------------------------------------------------------------------------
def make_table():
    t = QTableWidget()
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(False)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(38)
    t.horizontalHeader().setHighlightSections(False)
    return t


def fill_table(tbl, headers, rows, hidden=()):
    tbl.setSortingEnabled(False)
    tbl.clear()
    tbl.setColumnCount(len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v is None:
                text = ""
            elif isinstance(v, bool):
                text = "Ya" if v else "Tidak"
            elif isinstance(v, int) and c not in hidden:
                text = util.format_int(v)
            elif isinstance(v, float):
                text = ("%.2f" % v).replace(".", ",")
            else:
                text = str(v)
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, v)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(r, c, item)
    for c in range(len(headers)):
        tbl.setColumnHidden(c, c in hidden)
    tbl.resizeColumnsToContents()
    tbl.horizontalHeader().setStretchLastSection(True)


def selected_value(tbl, col=0):
    row = tbl.currentRow()
    if row < 0 or tbl.item(row, col) is None:
        raise UserError("Pilih data terlebih dahulu.")
    return tbl.item(row, col).data(Qt.UserRole)


def date_edit(value=None):
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd/MM/yyyy")
    d.setDate(QDate.currentDate() if value is None else QDate(value.year, value.month, value.day))
    return d


def py_date(qdate_edit):
    return qdate_edit.date().toPyDate()


def fill_combo(combo, options, keep_first=False):
    """options: [(id, label)]."""
    combo.clear()
    for key, text in options:
        combo.addItem(text, key)
    combo.setCurrentIndex(0 if (keep_first and combo.count()) else -1)


def quick_range(name):
    t = datetime.date.today()
    if name == "Kemarin":
        y = t - datetime.timedelta(days=1)
        return y, y
    if name == "Minggu ini":
        return t - datetime.timedelta(days=t.weekday()), t
    if name == "Bulan ini":
        return t.replace(day=1), t
    return t, t


class FieldDialog(FadeDialog):
    """fields: list of dict(key, label, value, required, password, options, int)."""

    def __init__(self, parent, title, fields):
        super().__init__(parent)
        self.setWindowTitle("Scaler")
        self.setMinimumWidth(480)
        self._fields, self._inputs, self.result_values = fields, {}, None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(6)
        lay.addWidget(label(title, role="value", size="md"))
        lay.addSpacing(8)
        for f in fields:
            lay.addWidget(caption(f["label"]))
            if f.get("options"):
                widget = QComboBox()
                widget.addItems(f["options"])
                idx = widget.findText(f.get("value", ""))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            else:
                widget = QLineEdit(f.get("value", "") or "")
                if f.get("password"):
                    widget.setEchoMode(QLineEdit.Password)
            self._inputs[f["key"]] = widget
            lay.addWidget(widget)
            lay.addSpacing(4)
        row = QHBoxLayout()
        row.addStretch(1)
        no, ok = btn("Batal", "ghost", 100), btn("Simpan", "primary", 110)
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        no.clicked.connect(self.reject)
        row.addWidget(no)
        row.addWidget(ok)
        lay.addSpacing(10)
        lay.addLayout(row)

    def _text(self, key):
        widget = self._inputs[key]
        return (widget.currentText() if isinstance(widget, QComboBox) else widget.text()).strip()

    def _ok(self):
        values = {}
        for f in self._fields:
            v = self._text(f["key"])
            if f.get("required") and not v:
                warn(self, "%s wajib diisi." % f["label"])
                return
            if f.get("int") and v and not v.isdigit():
                warn(self, "%s harus berupa angka bulat >= 0." % f["label"])
                return
            values[f["key"]] = v
        self.result_values = values
        self.accept()


def prompt_fields(parent, title, fields):
    dlg = FieldDialog(parent, title, fields)
    return dlg.result_values if dlg.exec_() == QDialog.Accepted else None
