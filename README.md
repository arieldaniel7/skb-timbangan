# Scaler - Offline Truck Weighbridge (Python + PyQt5 + SQLite + Lua)

Local, fully offline weighbridge / concrete-delivery ticket application for Windows 7 - 11.
UI language: Indonesian. No internet, cloud, telemetry or license check.

## What changed in this version

| Request | What you get |
|---|---|
| Modern, minimal, animated UI + dark/light mode | Complete UI rework: flat cards, painted icons, animated sidebar / page fades / count-up numbers / hover / toast notifications, and a **dark / light switch** (top bar, or *Pengaturan > Tampilan*) with a cross-fade. The choice is remembered. |
| Customer & Supplier fields | Only **Kode, Nama, Alamat**. |
| Truck fields | **Owner removed -> Kode Truk** (e.g. `TM-001`, unique, optional). **Max capacity removed** (the per-truck overload warning is gone; `rules.lua` has an optional global `max_net_kg`). |
| Dashboard: pick truck without typing | The Dashboard is now the operator console (the separate *Penimbangan* page was merged into it). **Pick a truck from the dropdown (or type plate / truck code) and its data loads automatically** - an open transaction switches to second weighing. An unknown plate shows **"Simpan ke database"** right there (optional truck code) - no need to visit Master Data; if you weigh without pressing it, the truck is saved automatically. Clicking a truck in the *Menunggu timbangan kedua* list loads it. |
| Dashboard: netto in volume | New card + section: **netto kg ÷ concrete density = m³** (default 2,400 kg/m³, *Pengaturan*), total for today, **per concrete grade** with animated bars, and per-delivery volume on the result cards and the ticket. The volume you type per delivery is still stored and shown as "tercatat". |
| Edit data in Laporan | In detail reports (*Laporan Harian*, *Riwayat Transaksi Truk*): double-click a row or **Ubah data**. Supervisor/Admin only, reason required, weights re-computed, everything in the audit log. Same editor is available in *Transaksi*. |
| Source and app in different folders | Data, database, backups, logs and **Lua scripts can live anywhere** (see *Folders* below). The app never depends on the current working directory. |
| Drag-and-drop template designer | *Pengaturan > Desain template*: drag elements / data fields into the layout, reorder by dragging, edit properties, live paper preview (A4/A5/thermal), print preview, view generated Lua. |
| TCP scale provider | *Pengaturan > Timbangan > TCP*: host, port, optional poll command; auto-reconnect. |

An existing database from the previous version is **upgraded automatically** (old columns are kept, nothing is deleted).

## 1. Quick start

1. Windows 7: install **Python 3.8.x** (last version that runs there). Windows 10/11: any Python 3.8+.
2. `pip install -r requirements.txt`, then `python main.py` (or `run.bat`).
3. First logins (a new password is requested at first login): `admin / admin123`, `supervisor / supervisor123`, `operator / operator123`.

If `lupa` cannot be installed, everything still works: the ticket and rules fall back to the built-in Python interpreter of the same layout
(*Pengaturan* shows "Lua: tidak tersedia").

## 2. Folders - run source and app anywhere

Data folder ("home": `data/`, `backups/`, `logs/`, `lua/`, `assets/`) is chosen in this order:
`--home DIR` > env `SCALER_HOME` > `scaler.ini` > the app folder (if writable) / `%LOCALAPPDATA%\Scaler`.
The Lua scripts folder can be separate: `--lua-dir DIR` > env `SCALER_LUA_DIR` > `scaler.ini`.

```
python C:\src\scaler\main.py --home D:\ScalerData --lua-dir D:\ScalerScripts
Scaler.exe --home D:\ScalerData
```
`scaler.ini` (next to the app, or `--config FILE` / `SCALER_CONFIG`):
```
[paths]
home = D:\ScalerData
lua_dir = D:\ScalerScripts
```
The default scripts are bundled with the app and copied into the Lua folder on first run (existing files are never overwritten),
so the program and the editable scripts can be updated independently. In-app: *Pengaturan > Folder & penyimpanan* can copy
the data to another folder and pick a scripts folder (applies after restart).

## 3. Build `Scaler.exe`

`build.bat` installs dependencies, runs the tests, builds with PyInstaller 5.13 (bundles `lua/`) and creates a portable
`dist\Scaler\` folder. Build on the oldest Windows / Python 3.8 you must support.

## 4. Operator manual (Dashboard, F1)

1. **Pick the truck** (dropdown, or type plate / `TM-001`, Enter). Registered trucks load immediately; F2/F3 focus the picker.
2. *New truck on this visit*: choose customer + concrete grade (+ supplier, project, volume, driver), weight, **F4**.
3. *Truck returns*: pick it again (or click it in the waiting list), weight, **F5**. Gross = heavier, tare = lighter, net = difference,
   netto volume = net / density. Print with **F6**; **Esc** clears.

Checks: weight > 0, net > 0, inactive master data refused, one open transaction per truck, completed transactions cannot be
completed again, changed plate without reloading is refused. Weights are integer kg (rounding step 1/5/10 kg).

| | OPERATOR | SUPERVISOR | ADMIN |
|---|---|---|---|
| Weigh, save new truck, view, first print | yes | yes | yes |
| Reprint, void/cancel, **edit transactions**, master data, reports | | yes | yes |
| Users, settings, templates, backup/restore, audit log | | | yes |

Shortcuts: F1 Dashboard, F2/F3 find truck, F4 first weighing, F5 second weighing, F6 print, F7 Transactions, F8 Master data, F9 Reports, Esc cancel.

## 5. Templates & rules (Lua)

* **Designer** (visual): saves a layout (JSON) and generates the Lua template. Placeholders like `{plate}`, `{net_volume_text}`; rows with empty
  values are hidden; `show_if` shows an element only when a field is filled. Fields include truck code and netto volume.
* **Kode Lua** (advanced): edit the generated script directly; validated before saving.
* `lua/scripts/rules.lua`: max weight, optional `max_net_kg` warning, require destination/driver, transaction-number format.
  Re-read automatically when the file changes. Sandboxed (no os/io/require/load/debug) with an instruction limit.

## 6. Scale

*Pengaturan > Timbangan*: **Manual**, **Serial** (COM port, baud...), **TCP** (host, port, optional poll command such as `W\r\n`).
Serial/TCP: weight field is read-only and saving requires a stable reading. TCP reconnects automatically if the link drops;
if the first connection fails the app continues in manual mode and says so. The generic parser
(`app/weighing/scale.py -> parse_line`) takes the first number per line and treats `US` as unstable (`ST,GS,  12450kg` style) -
**adapt it to your indicator's real output.**

## 7. Architecture

```
main.py                         app/paths.py   folders, ini, resource seeding
app/database/db.py              schema, migrations, seed
app/authentication/             PBKDF2 hashing, session, permissions
app/services/                   weighing (state machine, edit, volume), masterdata, settings, audit, backup, storage
app/weighing/scale.py           ScaleProvider -> Manual | Serial | TCP ; StreamParser ; ScaleService
app/scripting/lua_engine.py     sandboxed lupa wrapper
app/printing/layout.py          layout model, Python + Lua interpreters, designer model
app/printing/ticket.py          data -> items -> HTML -> printer / preview / PDF
app/reports/                    queries (+ids for editing), CSV / Excel / PDF / print
app/ui/                         theme (tokens + QSS), widgets (animated), pages, template_designer
lua/scripts/rules.lua  lua/templates/ticket.lua (generated default)  tests/
```
States: `WAITING_SECOND_WEIGHT -> COMPLETED`; `VOID` (completed, then voided), `CANCELLED` (voided while waiting).

## 8. Tests & verification status

`python -m unittest discover -s tests -v` - 80 tests (9 more run only when `lupa` is installed: Lua engine, sandbox, rules, and a check that
the Lua and Python layout interpreters produce identical output). Covers weighing and validation, editing, volume, roles, migration from the
old schema, folder resolution, TCP scale (real localhost sockets), layout/designer model, backup/restore, reports, QSS validity for both themes.

**Not verified here:** the PyQt5 windows themselves (layout, painting, animations, drag-and-drop events), printing, serial/TCP hardware,
Windows 7. The UI *logic* was exercised through a stand-in for Qt, which cannot reveal visual or Qt-API problems - run the app and report anything odd.

## 9. Known limitations

* No TCP/RFID/ANPR/camera/QR/multi-weighbridge extras beyond the TCP scale provider; no installer.
* *Transaksi* filtering is one search box + status + date range. Excel export needs `openpyxl`.
* Editing weights of a completed transaction is allowed for Supervisor/Admin (audited); void/cancelled transactions are read-only.
