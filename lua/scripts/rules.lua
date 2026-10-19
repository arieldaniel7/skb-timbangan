-- Aturan bisnis penimbangan yang dapat diubah tanpa menyentuh kode Python.
-- Python tetap menegakkan aturan keras (berat > 0, net > 0, tanpa transaksi ganda, dst).
-- Fungsi di sini menambah error (menolak) atau warning (minta konfirmasi operator).

local R = {}

R.config = {
  max_weight_kg = 200000,           -- batas berat masuk akal
  max_net_kg = 0,                   -- peringatan bila netto melebihi nilai ini (0 = nonaktif), mis. 22000
  require_destination = false,      -- wajibkan tujuan/proyek pada timbangan pertama
  require_driver = false,           -- wajibkan nama sopir pada timbangan pertama
}

-- Format nomor transaksi. day = "20261018", seq = nomor urut harian (integer, unik).
function R.format_trx_number(day, seq)
  return string.format("TICK-%s-%04d", day, seq)
end

-- ctx: weight, plate, customer_id, material_id, destination, driver, volume
function R.validate_first(ctx)
  local errors, warnings = {}, {}
  if ctx.weight > R.config.max_weight_kg then
    errors[#errors + 1] = "Berat melebihi batas " .. R.config.max_weight_kg .. " kg."
  end
  if R.config.require_destination and (ctx.destination == nil or ctx.destination == "") then
    errors[#errors + 1] = "Tujuan/proyek wajib diisi."
  end
  if R.config.require_driver and (ctx.driver == nil or ctx.driver == "") then
    errors[#errors + 1] = "Nama sopir wajib diisi."
  end
  return { errors = errors, warnings = warnings }
end

-- ctx: first_weight, second_weight, gross, tare, net
function R.validate_second(ctx)
  local errors, warnings = {}, {}
  if ctx.gross > R.config.max_weight_kg then
    errors[#errors + 1] = "Berat melebihi batas " .. R.config.max_weight_kg .. " kg."
  end
  if R.config.max_net_kg > 0 and ctx.net > R.config.max_net_kg then
    warnings[#warnings + 1] = "Berat bersih " .. ctx.net .. " kg melebihi batas " .. R.config.max_net_kg .. " kg."
  end
  return { errors = errors, warnings = warnings }
end

return R
