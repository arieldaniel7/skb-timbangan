"""Tema modern minimalis: token warna terang/gelap, stylesheet dinamis, palet Qt.

Modul ini tidak mengimpor Qt di tingkat atas (qss() murni Python agar bisa diuji); Qt hanya dipakai di apply()."""
import os
import tempfile
from string import Template

DARK = {
    "name": "dark",
    "bg": "#0E1114", "surface": "#151A1F", "surface2": "#1B2127", "hover": "#202830", "border": "#262E37",
    "text": "#E9EEF4", "muted": "#8B98A8", "faint": "#5C6876",
    "accent": "#3DD68C", "accent_fg": "#06150D", "accent_soft": "#173A2A",
    "warn": "#F0B84B", "warn_soft": "#3A2F14", "error": "#F0625D", "error_soft": "#3B1D1C",
}
LIGHT = {
    "name": "light",
    "bg": "#F4F6F9", "surface": "#FFFFFF", "surface2": "#EEF1F5", "hover": "#E8ECF1", "border": "#E0E5EB",
    "text": "#18212B", "muted": "#667385", "faint": "#9AA5B4",
    "accent": "#17A05D", "accent_fg": "#FFFFFF", "accent_soft": "#DDF3E8",
    "warn": "#B7791F", "warn_soft": "#FBF0D9", "error": "#D64545", "error_soft": "#FBE3E3",
}

_mode = "dark"


def mode():
    return _mode


def tokens():
    return DARK if _mode == "dark" else LIGHT


def is_dark():
    return _mode == "dark"


_QSS = Template("""
QWidget { font-family: "Segoe UI", "Segoe UI Variable Text", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: $text; }
QMainWindow, QDialog, QWidget#root, QWidget#page { background: $bg; }
QScrollArea { border: none; background: transparent; }
QLabel { background: transparent; }
QLabel[role="caption"] { color: $muted; font-size: 8pt; font-weight: bold; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="title"] { font-size: 17pt; font-weight: bold; }
QLabel[role="subtitle"] { color: $muted; font-size: 9pt; }
QLabel[role="value"] { font-size: 22pt; font-weight: bold; }
QLabel[role="value"][size="xl"] { font-size: 30pt; }
QLabel[role="value"][size="md"] { font-size: 15pt; }
QLabel[role="value"][size="sm"] { font-size: 11pt; }
QLabel[tone="ok"] { color: $accent; }
QLabel[tone="warn"] { color: $warn; }
QLabel[tone="error"] { color: $error; }
QLabel[tone="muted"] { color: $muted; }
QLabel[chip="true"] { background: $surface2; border-radius: 11px; padding: 4px 12px; font-weight: 600; }
QLabel[chip="true"][tone="ok"] { background: $accent_soft; color: $accent; }
QLabel[chip="true"][tone="warn"] { background: $warn_soft; color: $warn; }
QLabel[chip="true"][tone="error"] { background: $error_soft; color: $error; }
QLabel#mark { background: $accent; color: $accent_fg; border-radius: 11px; font-size: 14pt; font-weight: bold; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; }
QFrame#card { background: $surface; border: 1px solid $border; border-radius: 14px; }
QFrame#sidebar { background: $surface; border: none; border-right: 1px solid $border; }
QFrame#topbar { background: $bg; border: none; }
QFrame#newbox { background: $accent_soft; border: none; border-radius: 10px; }
QFrame#toast { background: $surface2; border: 1px solid $border; border-radius: 12px; }
QFrame#toast[tone="ok"] { border-left: 4px solid $accent; }
QFrame#toast[tone="warn"] { border-left: 4px solid $warn; }
QFrame#toast[tone="error"] { border-left: 4px solid $error; }
QFrame#hline { background: $border; border: none; min-height: 1px; max-height: 1px; }
QFrame#paper { background: #FFFFFF; border: 1px solid $border; border-radius: 4px; }
QPushButton { background: $surface2; border: 1px solid $border; border-radius: 9px; padding: 8px 16px; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDateEdit, QComboBox { background: $surface; border: 1px solid $border; border-radius: 9px; padding: 7px 10px; selection-background-color: $accent_soft; selection-color: $text; }
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover { border-color: $faint; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled { color: $faint; background: $surface2; }
QComboBox QLineEdit, QComboBox QLineEdit:hover, QComboBox QLineEdit:focus { border: none; background: transparent; padding: 0px; }
QLineEdit[display="true"] { font-size: 30pt; font-weight: bold; padding: 8px 14px; border-radius: 12px; }
QLineEdit[picker="true"] { font-size: 14pt; font-weight: 600; }
$dropdown_rules
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $accent_soft; selection-color: $text; outline: none; padding: 4px; }
QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid $border; border-radius: 5px; background: $surface; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QTableWidget, QTableView { background: $surface; alternate-background-color: $surface; border: 1px solid $border; border-radius: 12px; gridline-color: $border; selection-background-color: $accent_soft; selection-color: $text; outline: none; }
QTableWidget::item { padding: 4px 10px; border-bottom: 1px solid $border; }
QTableWidget::item:hover { background: $hover; }
QTableWidget::item:selected { background: $accent_soft; color: $text; }
QHeaderView { background: $surface; border: none; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border; padding: 10px; font-weight: bold; font-size: 9pt; }
QTableCornerButton::section { background: $surface; border: none; }
QListWidget { background: $surface; border: 1px solid $border; border-radius: 12px; padding: 4px; outline: none; }
QListWidget::item { padding: 8px 10px; border-radius: 8px; }
QListWidget::item:hover { background: $hover; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: $faint; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
QToolTip { background: $surface2; color: $text; border: 1px solid $border; padding: 6px 8px; }
QTextBrowser { background: #FFFFFF; color: #000000; border: none; }
QSplitter::handle { background: transparent; }
""")


def qss(tk, arrow=""):
    """Stylesheet untuk satu set token. arrow = path PNG chevron untuk combo (kosong = gaya bawaan)."""
    values = dict(tk)
    values["dropdown_rules"] = (
        'QComboBox { padding-right: 30px; }\n'
        'QComboBox::drop-down { border: none; width: 30px; }\n'
        'QComboBox::down-arrow { image: url("%s"); width: 12px; height: 12px; }' % arrow) if arrow else ""
    return _QSS.substitute(values)


def _chevron_file(color, name):
    """Chevron kecil untuk combo box, digambar saat runtime (tanpa file aset)."""
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
        folder = os.path.join(tempfile.gettempdir(), "scaler_ui")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "chevron_%s.png" % name)
        pm = QPixmap(24, 24)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(6, 9, 12, 15)
        p.drawLine(12, 15, 18, 9)
        p.end()
        return path.replace("\\", "/") if pm.save(path, "PNG") else ""
    except Exception:
        return ""


def apply(app, mode_name):
    """Terapkan tema ke seluruh aplikasi (palet + stylesheet). Aman dipanggil berulang saat runtime."""
    global _mode
    _mode = "light" if mode_name == "light" else "dark"
    tk = tokens()
    from PyQt5.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: tk["bg"], QPalette.WindowText: tk["text"], QPalette.Base: tk["surface"],
        QPalette.AlternateBase: tk["surface2"], QPalette.Text: tk["text"], QPalette.Button: tk["surface2"],
        QPalette.ButtonText: tk["text"], QPalette.Highlight: tk["accent_soft"], QPalette.HighlightedText: tk["text"],
        QPalette.ToolTipBase: tk["surface2"], QPalette.ToolTipText: tk["text"], QPalette.BrightText: tk["text"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(tk["faint"]))
    try:
        pal.setColor(QPalette.PlaceholderText, QColor(tk["muted"]))
    except AttributeError:
        pass
    app.setPalette(pal)
    app.setStyleSheet(qss(tk, _chevron_file(tk["muted"], _mode)))
