-- Template tiket - dihasilkan oleh Desainer Template (Pengaturan > Desain Template).
-- Aman diubah manual: T.layout adalah data tata letak; fungsi render() di bawah menerjemahkannya.
-- Placeholder {field} diganti nilai data; show_if = nama field yang harus terisi agar elemen tampil.

local T = {}

T.layout = {
  { type = "logo", show_if = "has_logo" },
  { type = "text", text = "{company_name}", align = "center", bold = true, size = 2, hide_empty = true },
  { type = "text", text = "{company_address}", align = "center", bold = false, size = 0, hide_empty = true },
  { type = "text", text = "Telp: {company_phone}", align = "center", bold = false, size = 0, show_if = "company_phone" },
  { type = "sep" },
  { type = "text", text = "TIKET TIMBANGAN", align = "center", bold = true, size = 0 },
  { type = "text", text = "*** CETAK ULANG ***", align = "center", bold = true, size = 0, show_if = "reprint" },
  { type = "sep" },
  { type = "row", label = "No. Transaksi", value = "{trx_number}", hide_empty = true },
  { type = "row", label = "Tanggal", value = "{date}", hide_empty = true },
  { type = "row", label = "Jam", value = "{time}", hide_empty = true },
  { type = "row", label = "No. Polisi", value = "{plate}", hide_empty = true },
  { type = "row", label = "Kode Truk", value = "{truck_code}", hide_empty = true },
  { type = "row", label = "Sopir", value = "{driver}", hide_empty = true },
  { type = "row", label = "Pelanggan", value = "{customer}", hide_empty = true },
  { type = "row", label = "Mutu/Material", value = "{material}", hide_empty = true },
  { type = "row", label = "Volume", value = "{volume}", hide_empty = true },
  { type = "row", label = "Supplier", value = "{supplier}", hide_empty = true },
  { type = "row", label = "Tujuan/Proyek", value = "{destination}", hide_empty = true },
  { type = "sep" },
  { type = "amount", label = "BERAT KOTOR", value = "{gross_text}" },
  { type = "amount", label = "TARA", value = "{tare_text}" },
  { type = "sep" },
  { type = "big", label = "BERAT BERSIH", value = "{net_text}" },
  { type = "amount", label = "NETTO (VOLUME)", value = "{net_volume_text}" },
  { type = "sep" },
  { type = "row", label = "Catatan", value = "{notes}", hide_empty = true },
  { type = "space" },
  { type = "signature", left = "Operator", right = "Sopir", left_name = "{operator}", right_name = "{driver}" },
}

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
