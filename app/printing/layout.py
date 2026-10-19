"""Model tata letak tiket (dipakai desainer drag-and-drop) + penerjemahnya ke item cetak dan ke skrip Lua.

Layout = daftar elemen (dict). Dua penerjemah dengan semantik identik:
  * render_layout()  - Python (pratinjau instan, dan cadangan bila Lua tidak tersedia)
  * layout_to_lua()  - menghasilkan skrip Lua (T.layout + interpreter) yang dijalankan mesin Lua tertanam

Placeholder {field} diganti nilai data; baris kosong disembunyikan; show_if menampilkan elemen hanya bila
field 'truthy' (bukan nil/false/""/0)."""
import copy
import json
import re

# ---- katalog untuk desainer ---------------------------------------------------------------
FIELDS = [
    ("company_name", "Nama Perusahaan"), ("company_address", "Alamat Perusahaan"), ("company_phone", "Telepon Perusahaan"),
    ("trx_number", "No. Transaksi"), ("date", "Tanggal"), ("time", "Jam"), ("plate", "No. Polisi"),
    ("truck_code", "Kode Truk"), ("driver", "Sopir"), ("customer", "Pelanggan"), ("supplier", "Supplier"),
    ("material", "Mutu / Material"), ("volume", "Volume Tercatat"), ("destination", "Tujuan / Proyek"),
    ("notes", "Catatan"), ("gross_text", "Berat Kotor"), ("tare_text", "Tara"), ("net_text", "Berat Bersih"),
    ("net_volume_text", "Netto (Volume m³)"), ("operator", "Operator"),
]
FIELD_LABELS = dict(FIELDS)
CONDITIONS = FIELDS + [("has_logo", "Logo tersedia"), ("reprint", "Cetak ulang")]

ELEMENTS = [
    ("text", "Teks", {"text": "Teks baru", "align": "left", "bold": False, "size": 0, "hide_empty": True}),
    ("row", "Baris  Label : Nilai", {"label": "Label", "value": "{customer}", "hide_empty": True}),
    ("amount", "Nilai kiri - kanan", {"label": "Label", "value": "{net_text}"}),
    ("big", "Nilai besar", {"label": "BERAT BERSIH", "value": "{net_text}"}),
    ("sep", "Garis pemisah", {}),
    ("space", "Spasi kosong", {}),
    ("logo", "Logo perusahaan", {"show_if": "has_logo"}),
    ("signature", "Tanda tangan", {"left": "Operator", "right": "Sopir", "left_name": "{operator}", "right_name": "{driver}"}),
]
ELEMENT_LABELS = dict((t, label) for t, label, _ in ELEMENTS)
ELEMENT_DEFAULTS = dict((t, d) for t, _, d in ELEMENTS)

# properti yang boleh ada per tipe: (kunci, jenis)
PROPS = {
    "text": [("text", "str"), ("align", "align"), ("bold", "bool"), ("size", "int"), ("hide_empty", "bool"), ("show_if", "cond")],
    "row": [("label", "str"), ("value", "str"), ("hide_empty", "bool"), ("show_if", "cond")],
    "amount": [("label", "str"), ("value", "str"), ("bold", "bool"), ("size", "int"), ("show_if", "cond")],
    "big": [("label", "str"), ("value", "str"), ("size", "int"), ("show_if", "cond")],
    "sep": [("show_if", "cond")],
    "space": [("show_if", "cond")],
    "logo": [("show_if", "cond")],
    "signature": [("left", "str"), ("right", "str"), ("left_name", "str"), ("right_name", "str"), ("show_if", "cond")],
}


def _row(label, field):
    return {"type": "row", "label": label, "value": "{%s}" % field, "hide_empty": True}


DEFAULT_LAYOUT = [
    {"type": "logo", "show_if": "has_logo"},
    {"type": "text", "text": "{company_name}", "align": "center", "bold": True, "size": 2, "hide_empty": True},
    {"type": "text", "text": "{company_address}", "align": "center", "bold": False, "size": 0, "hide_empty": True},
    {"type": "text", "text": "Telp: {company_phone}", "align": "center", "bold": False, "size": 0, "show_if": "company_phone"},
    {"type": "sep"},
    {"type": "text", "text": "TIKET TIMBANGAN", "align": "center", "bold": True, "size": 0},
    {"type": "text", "text": "*** CETAK ULANG ***", "align": "center", "bold": True, "size": 0, "show_if": "reprint"},
    {"type": "sep"},
    _row("No. Transaksi", "trx_number"), _row("Tanggal", "date"), _row("Jam", "time"),
    _row("No. Polisi", "plate"), _row("Kode Truk", "truck_code"), _row("Sopir", "driver"),
    _row("Pelanggan", "customer"), _row("Mutu/Material", "material"), _row("Volume", "volume"),
    _row("Supplier", "supplier"), _row("Tujuan/Proyek", "destination"),
    {"type": "sep"},
    {"type": "amount", "label": "BERAT KOTOR", "value": "{gross_text}"},
    {"type": "amount", "label": "TARA", "value": "{tare_text}"},
    {"type": "sep"},
    {"type": "big", "label": "BERAT BERSIH", "value": "{net_text}"},
    {"type": "amount", "label": "NETTO (VOLUME)", "value": "{net_volume_text}"},
    {"type": "sep"},
    _row("Catatan", "notes"),
    {"type": "space"},
    {"type": "signature", "left": "Operator", "right": "Sopir", "left_name": "{operator}", "right_name": "{driver}"},
]


# ---- validasi -------------------------------------------------------------------------------
def sanitize(layout):
    """Buang elemen/properti tak dikenal, paksa tipe data. Selalu mengembalikan list baru."""
    out = []
    for e in layout if isinstance(layout, list) else []:
        if not isinstance(e, dict) or e.get("type") not in PROPS:
            continue
        clean = {"type": e["type"]}
        for key, kind in PROPS[e["type"]]:
            if key not in e or e[key] is None:
                continue
            v = e[key]
            if kind == "bool":
                clean[key] = v is True
            elif kind == "int":
                try:
                    clean[key] = max(-6, min(14, int(v)))
                except (TypeError, ValueError):
                    pass
            elif kind == "align":
                clean[key] = v if v in ("left", "center", "right") else "left"
            elif kind == "cond":
                if str(v).strip():
                    clean[key] = str(v).strip()
            else:
                clean[key] = str(v)[:200]
        out.append(clean)
    return out


def layout_from_json(text):
    try:
        return sanitize(json.loads(text))
    except (TypeError, ValueError):
        return []


# ---- penerjemah Python ----------------------------------------------------------------------
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _truthy(v):
    return v is not None and v is not False and v != "" and v != 0


def _subst(text, data):
    def repl(m):
        v = data.get(m.group(1))
        return "" if v is None or v is False else str(v)
    return _PLACEHOLDER.sub(repl, str(text if text is not None else ""))


def render_layout(layout, data):
    items = []
    for e in layout:
        cond = e.get("show_if")
        if cond and not _truthy(data.get(cond)):
            continue
        kind = e.get("type")
        if kind == "text":
            text = _subst(e.get("text"), data)
            if text != "" or e.get("hide_empty") is False:
                items.append({"type": "text", "text": text, "align": e.get("align") or "left",
                              "bold": e.get("bold") is True, "size": e.get("size") or 0})
        elif kind == "row":
            value = _subst(e.get("value"), data)
            if value != "" or e.get("hide_empty") is False:
                items.append({"type": "row", "label": _subst(e.get("label"), data), "value": value})
        elif kind in ("amount", "big"):
            item = {"type": kind, "label": _subst(e.get("label"), data), "value": _subst(e.get("value"), data),
                    "bold": e.get("bold") is True}
            if e.get("size") is not None:
                item["size"] = e["size"]
            items.append(item)
        elif kind == "signature":
            items.append({"type": "signature", "left": _subst(e.get("left"), data), "right": _subst(e.get("right"), data),
                          "left_name": _subst(e.get("left_name"), data), "right_name": _subst(e.get("right_name"), data)})
        elif kind in ("sep", "space", "logo"):
            items.append({"type": kind})
    return items


# ---- penerjemah Lua -------------------------------------------------------------------------
def _lua_str(s):
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def _lua_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return _lua_str(v)


LUA_INTERPRETER = '''
local function truthy(v)
  return v ~= nil and v ~= false and v ~= "" and v ~= 0
end

local function subst(s, t)
  local text = tostring(s == nil and "" or s)
  return (text:gsub("{([%w_]+)}", function(k)
    local v = t[k]
    if v == nil or v == false then return "" end
    return tostring(v)
  end))
end

function T.get_layout()
  return T.layout
end

function T.render(t, paper)
  local items = {}
  for _, e in ipairs(T.layout) do
    local show = true
    if e.show_if ~= nil and e.show_if ~= "" then show = truthy(t[e.show_if]) end
    if show then
      local kind = e.type
      if kind == "text" then
        local text = subst(e.text, t)
        if text ~= "" or e.hide_empty == false then
          items[#items + 1] = { type = "text", text = text, align = e.align or "left", bold = e.bold == true, size = e.size or 0 }
        end
      elseif kind == "row" then
        local value = subst(e.value, t)
        if value ~= "" or e.hide_empty == false then
          items[#items + 1] = { type = "row", label = subst(e.label, t), value = value }
        end
      elseif kind == "amount" or kind == "big" then
        items[#items + 1] = { type = kind, label = subst(e.label, t), value = subst(e.value, t), bold = e.bold == true, size = e.size }
      elseif kind == "signature" then
        items[#items + 1] = { type = "signature", left = subst(e.left, t), right = subst(e.right, t),
                              left_name = subst(e.left_name, t), right_name = subst(e.right_name, t) }
      else
        items[#items + 1] = { type = kind }
      end
    end
  end
  return items
end

return T
'''


def layout_to_lua(layout):
    lines = [
        "-- Template tiket - dihasilkan oleh Desainer Template (Pengaturan > Desain Template).",
        "-- Aman diubah manual: T.layout adalah data tata letak; fungsi render() di bawah menerjemahkannya.",
        "-- Placeholder {field} diganti nilai data; show_if = nama field yang harus terisi agar elemen tampil.",
        "",
        "local T = {}",
        "",
        "T.layout = {",
    ]
    for e in sanitize(layout):
        fields = ["type = %s" % _lua_str(e["type"])]
        fields += ["%s = %s" % (k, _lua_value(v)) for k, v in e.items() if k != "type"]
        lines.append("  { %s }," % ", ".join(fields))
    lines.append("}")
    return "\n".join(lines) + "\n" + LUA_INTERPRETER


# ---- model untuk desainer (tanpa Qt, bisa diuji) -----------------------------------------------
def describe(e):
    """Ringkasan satu baris untuk daftar elemen."""
    kind = e.get("type")
    name = ELEMENT_LABELS.get(kind, kind)
    if kind == "text":
        return "%s  -  %s" % (name, e.get("text", ""))
    if kind in ("row", "amount", "big"):
        return "%s  -  %s : %s" % (name, e.get("label", ""), e.get("value", ""))
    if kind == "signature":
        return "%s  -  %s / %s" % (name, e.get("left", ""), e.get("right", ""))
    return name


class TemplateModel(object):
    def __init__(self, layout=None):
        self.layout = sanitize(copy.deepcopy(layout if layout is not None else DEFAULT_LAYOUT))

    def set_layout(self, layout):
        self.layout = sanitize(layout)

    def add(self, element_type, row=None):
        if element_type not in ELEMENT_DEFAULTS:
            raise ValueError("Tipe elemen tidak dikenal: %s" % element_type)
        element = sanitize([dict(ELEMENT_DEFAULTS[element_type], type=element_type)])[0]
        return self._insert(element, row)

    def add_field(self, key, row=None):
        if key not in FIELD_LABELS:
            raise ValueError("Field tidak dikenal: %s" % key)
        return self._insert({"type": "row", "label": FIELD_LABELS[key], "value": "{%s}" % key, "hide_empty": True}, row)

    def _insert(self, element, row):
        row = len(self.layout) if row is None else max(0, min(row, len(self.layout)))
        self.layout.insert(row, element)
        return row

    def remove(self, row):
        if 0 <= row < len(self.layout):
            del self.layout[row]

    def move(self, row, delta):
        new = row + delta
        if not (0 <= row < len(self.layout)) or not (0 <= new < len(self.layout)):
            return row
        self.layout[row], self.layout[new] = self.layout[new], self.layout[row]
        return new

    def duplicate(self, row):
        if not (0 <= row < len(self.layout)):
            return row
        self.layout.insert(row + 1, copy.deepcopy(self.layout[row]))
        return row + 1

    def update(self, row, key, value):
        e = self.layout[row]
        if key not in dict(PROPS[e["type"]]):
            raise KeyError(key)
        probe = sanitize([dict(e, **{key: value})])[0]
        if key in probe:
            e[key] = probe[key]
        else:
            e.pop(key, None)

    def to_lua(self):
        return layout_to_lua(self.layout)

    def to_json(self):
        return json.dumps(self.layout, ensure_ascii=False)
