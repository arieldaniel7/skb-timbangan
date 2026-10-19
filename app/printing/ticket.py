"""Tiket timbangan: data transaksi -> daftar item (template Lua, atau bawaan Python bila Lua tidak
tersedia) -> HTML -> printer / pratinjau / PDF."""
import copy
import html
import json
import os

from app import log, util
from app.errors import UserError
from app.database import db
from app.authentication.session import require, current_username
from app.printing import layout
from app.services import audit, settings, weighing
from app.scripting import lua_engine

logger = log.get(__name__)

PAPERS = ["A4", "A5", "Thermal 80mm", "Thermal 58mm", "Custom"]
BASE_PT = {"A4": 12, "A5": 10, "Thermal 80mm": 9, "Thermal 58mm": 8, "Custom": 10}
ITEM_TYPES = ("text", "row", "amount", "big", "sep", "space", "logo", "signature")


# ---- data ---------------------------------------------------------------------------
def ticket_data(trx):
    unit = settings.get("unit")
    stamp = trx.get("completed_at") or trx.get("created_at") or ""
    logo = settings.get("logo_path")
    vol = trx.get("volume_m3")
    gross, tare, net = trx.get("gross_weight"), trx.get("tare_weight"), trx.get("net_weight")
    return {
        "company_name": settings.get("company_name"), "company_address": settings.get("company_address"),
        "company_phone": settings.get("company_phone"), "has_logo": bool(logo and os.path.isfile(logo)),
        "trx_number": trx["trx_number"], "date": util.fmt_dt(stamp, False), "time": util.fmt_dt(stamp)[-5:],
        "plate": trx["plate"], "truck_code": trx.get("truck_code") or "", "driver": trx.get("driver_name") or "",
        "customer": trx["customer"],
        "supplier": trx.get("supplier") or "", "material": trx["material"],
        "volume": (("%g" % vol).replace(".", ",") + " m³") if vol else "",
        "destination": trx.get("destination") or "", "notes": trx.get("notes") or "",
        "gross": gross or 0, "tare": tare or 0, "net": net or 0,
        "gross_text": util.format_weight(gross, unit), "tare_text": util.format_weight(tare, unit),
        "net_text": util.format_weight(net, unit),
        "net_volume_text": util.format_volume(weighing.net_volume(net)) if net else "",
        "operator": trx.get("operator_name") or "", "reprint": (trx.get("print_count") or 0) > 0,
        "unit": unit,
    }


def sample_data():
    unit = settings.get("unit")
    return {
        "company_name": settings.get("company_name") or "NAMA PERUSAHAAN", "company_address": settings.get("company_address"),
        "company_phone": settings.get("company_phone"), "has_logo": False, "trx_number": "TICK-20261018-0001",
        "date": "18/10/2026", "time": "10:45", "plate": "AE 1234 XY", "truck_code": "TM-001", "driver": "Budi",
        "customer": "PT Contoh Konstruksi", "supplier": "", "material": "Beton K-300", "volume": "7 m³",
        "destination": "Proyek Gedung A", "notes": "",
        "gross": 30450, "tare": 13650, "net": 16800, "gross_text": util.format_weight(30450, unit),
        "tare_text": util.format_weight(13650, unit), "net_text": util.format_weight(16800, unit),
        "net_volume_text": util.format_volume(weighing.net_volume(16800)),
        "operator": "Operator 1", "reprint": False, "unit": unit,
    }


# ---- template (tersimpan di DB: kode Lua + layout JSON) ---------------------------------------
def default_template_source():
    return layout.layout_to_lua(layout.DEFAULT_LAYOUT)


def _store(content, layout_json, by=None):
    db.execute("INSERT OR REPLACE INTO print_templates(name, content, layout_json, updated_at, updated_by) VALUES('ticket',?,?,?,?)",
               (content, layout_json, util.now_str(), by or current_username()))


def ensure_template():
    if db.query_one("SELECT 1 FROM print_templates WHERE name='ticket'") is None:
        _store(default_template_source(), json.dumps(layout.DEFAULT_LAYOUT, ensure_ascii=False), "system")


def template_source():
    row = db.query_one("SELECT content FROM print_templates WHERE name='ticket'")
    if row is not None and (row[0] or "").strip():
        return row[0]
    return default_template_source()


def get_layout():
    """Layout untuk desainer: layout JSON, atau dibaca dari skrip Lua (T.get_layout), atau bawaan."""
    row = db.query_one("SELECT content, layout_json FROM print_templates WHERE name='ticket'")
    if row is not None:
        if row["layout_json"]:
            lay = layout.layout_from_json(row["layout_json"])
            if lay:
                return lay
        eng = lua_engine.get_engine()
        if eng.available and row["content"]:
            try:
                lay = layout.sanitize(eng.call_source("ticket_layout", row["content"], "get_layout"))
                if lay:
                    return lay
            except lua_engine.LuaError:
                pass
    return copy.deepcopy(layout.DEFAULT_LAYOUT)


def save_layout(lay):
    """Simpan hasil Desainer Template: layout JSON + skrip Lua yang dihasilkan."""
    require("edit_template")
    lay = layout.sanitize(lay)
    if not lay:
        raise UserError("Template kosong. Tambahkan minimal satu elemen.")
    source = layout.layout_to_lua(lay)
    eng = lua_engine.get_engine()
    if eng.available:
        try:
            eng.check_source(source, "template")
        except lua_engine.LuaError as exc:
            raise UserError("Template tidak valid:\n%s" % exc)
    _store(source, json.dumps(lay, ensure_ascii=False))
    audit.log("UBAH TEMPLATE TIKET", "print_templates", "ticket", None, "desainer (%d elemen)" % len(lay))


def save_template(source):
    """Simpan kode Lua hasil edit manual (divalidasi dengan mesin Lua)."""
    require("edit_template")
    eng = lua_engine.get_engine()
    if not eng.available:
        raise UserError("Lua tidak tersedia, kode tidak dapat divalidasi. Gunakan Desainer Template.")
    try:
        eng.check_source(source)
    except lua_engine.LuaError as exc:
        raise UserError("Template tidak valid:\n%s" % exc)
    layout_json = None
    try:
        lay = layout.sanitize(eng.call_source("ticket_probe", source, "get_layout"))
        if lay:
            layout_json = json.dumps(lay, ensure_ascii=False)
    except lua_engine.LuaError:
        pass
    _store(source, layout_json)
    audit.log("UBAH TEMPLATE TIKET", "print_templates", "ticket", None, "kode Lua")


def reset_template():
    save_layout(layout.DEFAULT_LAYOUT)


def _valid_items(items):
    if not isinstance(items, list):
        return None
    out = [i for i in items if isinstance(i, dict) and i.get("type") in ITEM_TYPES]
    return out or None


def default_items(data):
    return layout.render_layout(layout.DEFAULT_LAYOUT, data)


def render_items(data, source=None, strict=False):
    """Lua bila tersedia; bila tidak/gagal -> penerjemah Python atas layout yang sama (kecuali strict=True)."""
    src = source if source is not None else template_source()
    eng = lua_engine.get_engine()
    if src and eng.available:
        try:
            name = "ticket" if source is None else "ticket_preview"
            items = _valid_items(eng.call_source(name, src, "render", data, settings.get("paper")))
            if items:
                return items
            if strict:
                raise UserError("Template tidak menghasilkan item tiket.")
        except lua_engine.LuaError as exc:
            if strict:
                raise UserError("Template error:\n%s" % exc)
            logger.warning("Template tiket Lua error, memakai penerjemah Python: %s", exc)
    elif strict and source is not None:
        raise UserError("Lua tidak tersedia: %s" % eng.error)
    return layout.render_layout(get_layout() if source is None else layout.DEFAULT_LAYOUT, data)


# ---- HTML ---------------------------------------------------------------------------
def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True).replace("\n", "<br>")


def _num(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def items_to_html(items, paper="A5", logo_path=""):
    base = BASE_PT.get(paper, 10)
    out = ['<html><body style="font-family:\'Courier New\',monospace; font-size:%dpt; color:#000000; background-color:#ffffff;">' % base]
    for it in items:
        kind = it.get("type")
        size = _num(it.get("size"), 0)
        pt = max(6, min(36, base + size))
        weight = "bold" if it.get("bold") else "normal"
        if kind == "text":
            align = it.get("align") if it.get("align") in ("left", "center", "right") else "left"
            out.append('<p align="%s" style="margin:0; font-size:%dpt; font-weight:%s;">%s</p>' %
                       (align, pt, weight, _esc(it.get("text"))))
        elif kind == "row":
            out.append('<table width="100%%" cellspacing="0" cellpadding="1"><tr><td width="38%%" style="font-size:%dpt;">%s</td>'
                       '<td style="font-size:%dpt;">: %s</td></tr></table>' % (pt, _esc(it.get("label")), pt, _esc(it.get("value"))))
        elif kind in ("amount", "big"):
            if kind == "big":
                weight = "bold"
                if "size" not in it:
                    pt = min(36, base + 3)
            out.append('<table width="100%%" cellspacing="0" cellpadding="1"><tr><td align="left" style="font-size:%dpt; font-weight:%s;">%s</td>'
                       '<td align="right" style="font-size:%dpt; font-weight:%s;">%s</td></tr></table>' %
                       (pt, weight, _esc(it.get("label")), pt, weight, _esc(it.get("value"))))
        elif kind == "sep":
            out.append("<hr>")
        elif kind == "space":
            out.append('<p style="margin:0;">&nbsp;</p>')
        elif kind == "logo":
            if logo_path and os.path.isfile(logo_path):
                out.append('<p align="center"><img src="file:///%s" width="120"></p>' % logo_path.replace("\\", "/"))
        elif kind == "signature":
            out.append('<table width="100%%" cellspacing="0" cellpadding="2"><tr>'
                       '<td align="center" width="50%%">%s<br><br><br><br>______________<br>%s</td>'
                       '<td align="center" width="50%%">%s<br><br><br><br>______________<br>%s</td></tr></table>' %
                       (_esc(it.get("left")), _esc(it.get("left_name")), _esc(it.get("right")), _esc(it.get("right_name"))))
    out.append("</body></html>")
    return "".join(out)


def ticket_html(trx_id=None, source=None, strict=False):
    """HTML tiket untuk transaksi tertentu, atau data contoh (trx_id=None) untuk pratinjau template."""
    if trx_id is None:
        data = sample_data()
    else:
        trx = weighing.get_transaction(trx_id)
        if trx is None:
            raise UserError("Transaksi tidak ditemukan.")
        data = ticket_data(trx)
    paper = settings.get("paper")
    logo = settings.get("logo_path")
    return items_to_html(render_items(data, source, strict), paper, logo)


# ---- Qt: printer, pratinjau, PDF -----------------------------------------------------
def _configure(printer, paper):
    from PyQt5.QtCore import QSizeF
    from PyQt5.QtGui import QPageSize
    from PyQt5.QtPrintSupport import QPrinter
    margin = float(max(0, min(30, settings.get_int("margin_mm", 8))))
    if paper == "A4":
        printer.setPageSize(QPageSize(QPageSize.A4))
    elif paper == "A5":
        printer.setPageSize(QPageSize(QPageSize.A5))
    else:
        width = {"Thermal 80mm": 80, "Thermal 58mm": 58}.get(paper) or max(40, settings.get_int("paper_w_mm", 80))
        height = max(60, settings.get_int("paper_h_mm", 200))
        printer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Millimeter, "Tiket"))
        margin = min(margin, 3.0)
    printer.setPageMargins(margin, margin, margin, margin, QPrinter.Millimeter)


def show_preview(html_text, parent=None):
    from PyQt5.QtGui import QTextDocument
    from PyQt5.QtPrintSupport import QPrinter, QPrintPreviewDialog
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)  # pratinjau tidak butuh printer fisik
    _configure(printer, settings.get("paper"))
    doc = QTextDocument()
    doc.setHtml(html_text)
    dlg = QPrintPreviewDialog(printer, parent)
    dlg.paintRequested.connect(lambda p: doc.print_(p))
    dlg.resize(900, 700)
    dlg.exec_()


def print_ticket(trx_id, preview=False, pdf_path=None, parent=None):
    from PyQt5.QtGui import QTextDocument
    from PyQt5.QtPrintSupport import QPrinter
    trx = weighing.get_transaction(trx_id)
    if trx is None:
        raise UserError("Transaksi tidak ditemukan.")
    if trx["status"] != weighing.STATUS_COMPLETED:
        raise UserError("Hanya transaksi yang sudah selesai yang dapat dicetak.")
    reprint = trx["print_count"] > 0
    html_text = ticket_html(trx_id)
    if preview:
        show_preview(html_text, parent)
        return
    require("reprint" if reprint else "print")
    printer = QPrinter(QPrinter.HighResolution)
    if pdf_path:
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(pdf_path)
    else:
        name = settings.get("printer")
        if name:
            printer.setPrinterName(name)
        if not printer.isValid():
            raise UserError("Printer tidak ditemukan. Pilih printer di Pengaturan.")
        copies = settings.get_int("copies", 1)
        if copies > 1:
            printer.setCopyCount(min(copies, 5))
    _configure(printer, settings.get("paper"))
    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.print_(printer)
    weighing.mark_printed(trx_id, "PDF" if pdf_path else ("REPRINT" if reprint else "PRINT"))
