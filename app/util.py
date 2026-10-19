import datetime
import re

from app.errors import UserError


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def day_str(d):
    return d.strftime("%Y-%m-%d")


def normalize_plate(text):
    """'b-1234 xyz' -> 'B1234XYZ'."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def format_plate(text):
    """'ae1234xy' -> 'AE 1234 XY'; bila sudah ada spasi hanya dirapikan."""
    raw = re.sub(r"\s+", " ", (text or "").strip().upper())
    if " " in raw or "-" in raw:
        return raw
    m = re.match(r"^([A-Z]{1,2})(\d{1,4})([A-Z]{0,3})$", raw)
    return " ".join(g for g in m.groups() if g) if m else raw


def format_decimal(value, digits=2):
    """7.5 -> '7,50' (format Indonesia)."""
    return ("{:,.%df}" % digits).format(value).replace(",", "X").replace(".", ",").replace("X", ".")


def format_volume(m3):
    """7.0 -> '7,00 m³' (format Indonesia)."""
    if m3 is None:
        return "-"
    return ("{:,.2f}".format(m3)).replace(",", "X").replace(".", ",").replace("X", ".") + " m³"


def format_int(n):
    """12450 -> '12.450' (format Indonesia)."""
    return "{:,}".format(int(n)).replace(",", ".")


def format_weight(kg, unit="KG"):
    if kg is None:
        return "-"
    if str(unit).upper() == "TON":
        s = "{:,.2f}".format(kg / 1000.0)
        return s.replace(",", "X").replace(".", ",").replace("X", ".") + " TON"
    return format_int(kg) + " KG"


def parse_weight(text):
    """Ketikan operator ('12.450', '12450 kg') -> int kg. Berat disimpan sebagai integer."""
    raw = (text or "").strip()
    if "-" in raw:
        raise UserError("Berat tidak boleh negatif.")
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        raise UserError("Berat harus lebih dari 0.")
    return int(digits)


def quantize(weight, step):
    """Bulatkan ke kelipatan presisi (1, 5, 10 kg) - half up, tanpa float drift."""
    step = max(1, int(step))
    return ((int(weight) * 2 + step) // (step * 2)) * step


def fmt_dt(value, with_time=True):
    try:
        d = datetime.datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        return d.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value) if value else ""
