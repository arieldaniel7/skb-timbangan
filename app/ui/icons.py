"""Ikon garis minimalis digambar dengan QPainter (tanpa file aset; ikut warna tema)."""
import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QPen

ARC = 16  # Qt menyatakan sudut dalam 1/16 derajat


def _dashboard(p):
    for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
        p.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)


def _list(p):
    for y in (6, 12, 18):
        p.drawLine(QPointF(9, y), QPointF(20, y))
        p.drawEllipse(QPointF(4.5, y), 1.2, 1.2)


def _database(p):
    p.drawEllipse(QRectF(4, 3, 16, 6))
    p.drawLine(QPointF(4, 6), QPointF(4, 18))
    p.drawLine(QPointF(20, 6), QPointF(20, 18))
    p.drawArc(QRectF(4, 9, 16, 6), 180 * ARC, 180 * ARC)
    p.drawArc(QRectF(4, 15, 16, 6), 180 * ARC, 180 * ARC)


def _chart(p):
    for x, top in ((6, 13), (12, 5), (18, 10)):
        p.drawLine(QPointF(x, 20), QPointF(x, top))
    p.drawLine(QPointF(3, 21.5), QPointF(21, 21.5))


def _users(p):
    p.drawEllipse(QPointF(12, 8), 4, 4)
    p.drawArc(QRectF(4, 14, 16, 14), 0, 180 * ARC)


def _audit(p):
    p.drawRoundedRect(QRectF(5, 4, 14, 17), 2.5, 2.5)
    for y in (10, 14, 18):
        p.drawLine(QPointF(8.5, y), QPointF(15.5, y))
    p.drawLine(QPointF(9.5, 2.5), QPointF(14.5, 2.5))


def _gear(p):
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    p.drawEllipse(QPointF(12, 12), 7, 7)
    for k in range(8):
        a = math.radians(k * 45)
        p.drawLine(QPointF(12 + 7 * math.cos(a), 12 + 7 * math.sin(a)), QPointF(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)))


def _logout(p):
    p.drawLine(QPointF(10, 4), QPointF(4, 4))
    p.drawLine(QPointF(4, 4), QPointF(4, 20))
    p.drawLine(QPointF(4, 20), QPointF(10, 20))
    p.drawLine(QPointF(9, 12), QPointF(21, 12))
    p.drawLine(QPointF(17, 8), QPointF(21, 12))
    p.drawLine(QPointF(21, 12), QPointF(17, 16))


def _chevron_left(p):
    p.drawLine(QPointF(14.5, 6), QPointF(8.5, 12))
    p.drawLine(QPointF(8.5, 12), QPointF(14.5, 18))


def _chevron_right(p):
    p.drawLine(QPointF(9.5, 6), QPointF(15.5, 12))
    p.drawLine(QPointF(15.5, 12), QPointF(9.5, 18))


SHAPES = {"dashboard": _dashboard, "list": _list, "database": _database, "chart": _chart, "users": _users,
          "audit": _audit, "gear": _gear, "logout": _logout, "chevron_left": _chevron_left, "chevron_right": _chevron_right}


def draw(painter, name, rect, color, width=1.8):
    """Gambar ikon 'name' di dalam rect (QRectF persegi) dengan warna QColor."""
    shape = SHAPES.get(name)
    if shape is None:
        return
    painter.save()
    painter.translate(rect.topLeft())
    scale = rect.width() / 24.0
    painter.scale(scale, scale)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    shape(painter)
    painter.restore()
