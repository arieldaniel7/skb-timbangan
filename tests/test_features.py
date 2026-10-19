"""Tes fitur putaran kedua: folder terpisah, migrasi, data induk ringkas, edit transaksi, netto volume,
TCP scale, layout/desainer template."""
import datetime
import os
import shutil
import socketserver
import sqlite3
import tempfile
import threading
import time
import unittest

try:
    from test_core import Base, ROOT, HAVE_LUPA
except ImportError:  # dijalankan sebagai tests.test_features
    from tests.test_core import Base, ROOT, HAVE_LUPA

from app import paths, util
from app.errors import PermissionDenied, UserError
from app.database import db
from app.authentication.session import session
from app.printing import layout, ticket
from app.reports import service as reports
from app.scripting import lua_engine
from app.services import masterdata, settings, weighing
from app.weighing import scale


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        paths.configure()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_env_ini_precedence(self):
        home_cli, home_env, home_ini = [os.path.join(self.tmp, n) for n in ("cli", "env", "ini")]
        ini = os.path.join(self.tmp, "x.ini")
        with open(ini, "w") as fh:
            fh.write("[paths]\nhome = %s\nlua_dir = %s\n" % (home_ini, os.path.join(self.tmp, "ini_lua")))
        rest = paths.resolve(["--config", ini, "-style", "fusion"], {})
        self.assertEqual((paths.BASE, paths.LUA_DIR), (home_ini, os.path.join(self.tmp, "ini_lua")))
        self.assertEqual(rest, ["-style", "fusion"])         # argumen Qt dibiarkan
        paths.resolve(["--config", ini], {"SCALER_HOME": home_env})
        self.assertEqual(paths.BASE, home_env)
        paths.resolve(["--config", ini, "--home", home_cli, "--lua-dir", os.path.join(self.tmp, "L")], {"SCALER_HOME": home_env})
        self.assertEqual((paths.BASE, paths.LUA_DIR), (home_cli, os.path.join(self.tmp, "L")))
        self.assertEqual(paths.DB_PATH, os.path.join(home_cli, "data", "scaler.db"))

    def test_app_and_data_in_different_folders(self):
        home, lua = os.path.join(self.tmp, "data_home"), os.path.join(self.tmp, "scripts")
        paths.configure(home, lua_dir=lua)
        copied = paths.seed_resources()
        self.assertTrue(os.path.isfile(os.path.join(lua, "scripts", "rules.lua")))
        self.assertTrue(os.path.isfile(os.path.join(lua, "templates", "ticket.lua")))
        self.assertTrue(copied and all(c.startswith(lua) for c in copied))
        self.assertTrue(os.path.isdir(os.path.join(home, "data")))
        mine = os.path.join(lua, "scripts", "rules.lua")
        with open(mine, "w") as fh:
            fh.write("-- punya saya")
        self.assertEqual(paths.seed_resources(), [])          # tidak menimpa file pengguna
        with open(mine) as fh:
            self.assertEqual(fh.read(), "-- punya saya")

    def test_ini_roundtrip(self):
        ini = os.path.join(self.tmp, "a", "scaler.ini")
        paths.configure(self.tmp, ini_path=ini)
        paths.save_ini(home="D:/Scaler", lua_dir="D:/Skrip")
        values, found = paths.read_ini(ini)
        self.assertEqual((values["home"], values["lua_dir"], found), ("D:/Scaler", "D:/Skrip", ini))
        paths.save_ini(lua_dir=None)
        self.assertNotIn("lua_dir", paths.read_ini(ini)[0])

    def test_independent_of_cwd(self):
        old = os.getcwd()
        try:
            os.chdir(self.tmp)
            paths.configure()
            self.assertTrue(os.path.isabs(paths.BASE) and os.path.isdir(paths.RESOURCE_DIR))
            self.assertTrue(os.path.isfile(os.path.join(paths.RESOURCE_DIR, "lua", "scripts", "rules.lua")))
        finally:
            os.chdir(old)


class TestMigration(unittest.TestCase):
    """Database dari versi sebelumnya (kolom owner/kapasitas/telepon, tanpa kode truk) tetap bisa dipakai."""

    def test_old_schema_upgrades(self):
        tmp = tempfile.mkdtemp()
        try:
            paths.configure(tmp)
            paths.seed_resources()
            os.makedirs(paths.DATA_DIR, exist_ok=True)
            old = sqlite3.connect(paths.DB_PATH)
            old.executescript("""
CREATE TABLE trucks(id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT NOT NULL UNIQUE, plate_display TEXT NOT NULL,
  truck_type TEXT, owner TEXT, driver TEXT, max_capacity_kg INTEGER, notes TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT);
CREATE TABLE customers(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, address TEXT,
  phone TEXT, email TEXT, tax_id TEXT, contact TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE print_templates(name TEXT PRIMARY KEY, content TEXT NOT NULL, updated_at TEXT, updated_by TEXT);
INSERT INTO trucks(plate, plate_display, owner, max_capacity_kg, created_at) VALUES('B9999ZZ','B 9999 ZZ','Pak Budi',15000,'2026-01-01 00:00:00');
INSERT INTO customers(code, name, phone, created_at) VALUES('C900','Lama','0812','2026-01-01 00:00:00');
INSERT INTO print_templates(name, content) VALUES('ticket','local T = {} function T.render(t) return {} end return T');
""")
            old.close()
            db.close()
            db.init()
            self.assertIn("truck_code", db.columns("trucks"))
            self.assertIn("layout_json", db.columns("print_templates"))
            self.assertEqual(db.scalar("SELECT owner FROM trucks WHERE plate='B9999ZZ'"), "Pak Budi")   # data lama utuh
            from app.authentication import auth
            auth.login(db.query_one("SELECT id FROM users WHERE username='admin'")["id"], "admin123")
            tid = masterdata.create("trucks", {"plate_display": "AE 5 B", "truck_code": "TM-010"})
            self.assertEqual(masterdata.get("trucks", tid)["truck_code"], "TM-010")
            with self.assertRaises(UserError):
                masterdata.create("trucks", {"plate_display": "AE 6 B", "truck_code": "tm-010"})
            masterdata.create("customers", {"code": "C901", "name": "Baru"})
            # template lama tetap dipakai apa adanya, desainer jatuh ke layout bawaan
            self.assertIn("function T.render", ticket.template_source())
            self.assertEqual(ticket.get_layout(), layout.sanitize(layout.DEFAULT_LAYOUT))
        finally:
            db.close()
            session.user = None
            paths.configure()
            shutil.rmtree(tmp, ignore_errors=True)


class TestMasterSlim(Base):
    def test_entity_fields(self):
        keys = lambda t: [f.key for f in masterdata.BY_TABLE[t].fields]
        self.assertEqual(keys("customers"), ["code", "name", "address"])
        self.assertEqual(keys("suppliers"), ["code", "name", "address"])
        self.assertEqual(keys("trucks"), ["plate_display", "truck_code", "truck_type", "driver", "notes"])

    def test_register_truck_by_operator(self):
        self.login("operator")
        tid = masterdata.register_truck("ae5678zz", "tm-007", "Andi")
        row = masterdata.get("trucks", tid)
        self.assertEqual((row["plate_display"], row["truck_code"], row["driver"]), ("AE 5678 ZZ", "TM-007", "Andi"))
        with self.assertRaises(UserError):
            masterdata.register_truck("AE 5678 ZZ")           # plat sama
        with self.assertRaises(UserError):
            masterdata.register_truck("B 1 A", "TM-007")      # kode sama
        with self.assertRaises(UserError):
            masterdata.register_truck("  -- ")                # tidak valid
        with self.assertRaises(PermissionDenied):
            masterdata.create("trucks", {"plate_display": "B 2 A"})   # master data tetap dibatasi

    def test_find_truck_by_plate_or_code(self):
        self.assertEqual(masterdata.find_truck("tm-001")["plate_display"], "AE 1234 XY")
        self.assertEqual(masterdata.find_truck("ae-1234-xy")["truck_code"], "TM-001")
        self.assertIsNone(masterdata.find_truck("zzz"))
        self.assertIsNone(masterdata.find_truck(""))

    def test_options_include_inactive_current(self):
        cust = db.scalar("SELECT id FROM customers LIMIT 1")
        masterdata.toggle_active("customers", cust)
        self.assertEqual(masterdata.options("customers"), [])
        self.assertEqual(len(masterdata.options("customers", include_id=cust)), 1)

    def test_weighing_auto_registers_new_plate_with_code(self):
        cust, mat = self.ids()
        weighing.start_first("b 4321 qq", cust, mat, 9000, create_truck=True, truck_code="tm-050")
        row = masterdata.find_truck("TM-050")
        self.assertEqual(row["plate_display"], "B 4321 QQ")


class TestEditTransaction(Base):
    def setUp(self):
        super().setUp()
        self.tid = self.full_trx()                       # kotor 30450, tara 13650, bersih 16800
        self.login("supervisor")

    def test_edit_fields_and_recalculate(self):
        cust2 = masterdata.create("customers", {"code": "C002", "name": "PT Lain"})
        res = weighing.update_transaction(self.tid, {"destination": "Proyek B", "driver_name": "Citra", "customer_id": cust2,
                                                     "volume_m3": 8.0, "second_weight": 28650}, "koreksi timbangan kedua")
        t = weighing.get_transaction(self.tid)
        self.assertEqual((t["destination"], t["driver_name"], t["customer"], t["volume_m3"]), ("Proyek B", "Citra", "PT Lain", 8.0))
        self.assertEqual((t["gross_weight"], t["tare_weight"], t["net_weight"]), (28650, 13650, 15000))
        self.assertEqual(db.scalar("SELECT weight FROM transaction_weights WHERE transaction_id=? AND seq=2", (self.tid,)), 28650)
        self.assertTrue(res["changed"])
        entry = db.query_one("SELECT new_value, username FROM audit_logs WHERE action='UBAH TRANSAKSI'")
        self.assertIn("koreksi timbangan kedua", entry["new_value"])
        self.assertIn("second_weight: 30450 -> 28650", entry["new_value"])
        self.assertEqual(entry["username"], "supervisor")

    def test_swapping_weights_still_gross_is_heavier(self):
        weighing.update_transaction(self.tid, {"first_weight": 31000, "second_weight": 13000}, "tukar")
        t = weighing.get_transaction(self.tid)
        self.assertEqual((t["gross_weight"], t["tare_weight"], t["net_weight"]), (31000, 13000, 18000))

    def test_permissions_and_validation(self):
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"destination": "X"}, "  ")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {}, "tanpa perubahan")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"second_weight": 13650}, "sama")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"second_weight": -5}, "negatif")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"volume_m3": -1.0}, "negatif")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"status": "VOID"}, "kolom terlarang")
        other = masterdata.create("customers", {"code": "C003", "name": "PT Nonaktif"})
        masterdata.toggle_active("customers", other)
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"customer_id": other}, "pelanggan nonaktif")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"customer_id": 9999}, "pelanggan tidak ada")
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            weighing.update_transaction(self.tid, {"destination": "X"}, "operator")

    def test_voided_and_waiting_rules(self):
        weighing.void_transaction(self.tid, "salah")
        with self.assertRaises(UserError):
            weighing.update_transaction(self.tid, {"destination": "X"}, "sudah void")
        cust, mat = self.ids()
        w = weighing.start_first("B 77 A", cust, mat, 10000, create_truck=True)
        weighing.update_transaction(w["id"], {"first_weight": 10500}, "koreksi")
        self.assertEqual(weighing.get_transaction(w["id"])["first_weight"], 10500)
        with self.assertRaises(UserError):
            weighing.update_transaction(w["id"], {"second_weight": 20000}, "belum waktunya")
        weighing.complete_second(w["id"], 25500)
        self.assertEqual(weighing.get_transaction(w["id"])["net_weight"], 15000)

    def test_truck_switch_conflict_for_waiting(self):
        cust, mat = self.ids()
        a = weighing.start_first("B 11 A", cust, mat, 10000, create_truck=True)
        b = weighing.start_first("B 12 A", cust, mat, 10000, create_truck=True)
        truck_a = weighing.get_transaction(a["id"])["truck_id"]
        with self.assertRaises(UserError):
            weighing.update_transaction(b["id"], {"truck_id": truck_a}, "salah truk")


class TestNettoVolume(Base):
    def test_stats_and_density_setting(self):
        self.full_trx()                                   # netto 16.800 kg, volume tercatat 7
        s = weighing.today_stats()
        self.assertAlmostEqual(s["net_m3"], 7.0)
        self.assertAlmostEqual(s["recorded_m3"], 7.0)
        by = weighing.volume_by_material_today()
        self.assertEqual((by[0][0], by[0][1], by[0][2]), ("Beton K-300", 1, 16800))
        self.assertAlmostEqual(by[0][3], 7.0)
        settings.set("density_kg_m3", "2000")
        self.assertAlmostEqual(weighing.net_volume(16800), 8.4)
        settings.set("density_kg_m3", "0")                # nilai tidak valid -> bawaan 2400
        self.assertEqual(weighing.density(), 2400)

    def test_preview_has_volume_and_ticket_shows_it(self):
        cust, mat = self.ids()
        r = weighing.start_first("AE 1234 XY", cust, mat, 13650)
        prev = weighing.preview_second(r["id"], 30450)
        self.assertAlmostEqual(prev["net_m3"], 7.0)
        weighing.complete_second(r["id"], 30450)
        html_text = ticket.ticket_html(r["id"])
        self.assertIn("7,00 m³", html_text)
        self.assertIn("TM-001", html_text)

    def test_report_ids_and_volume_columns(self):
        tid = self.full_trx()
        today = datetime.date.today()
        headers, rows, total, ids = reports.run("daily", today, today)
        self.assertEqual(ids, [tid])
        self.assertEqual(weighing.get_transaction(ids[0])["trx_number"], rows[0][headers.index("No. Transaksi") ])
        self.assertEqual(rows[0][headers.index("Netto Volume (m3)")], 7.0)
        self.assertEqual(rows[0][headers.index("Kode Truk")], "TM-001")


class _StreamHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.connections += 1
        mode = self.server.mode
        if mode == "poll":
            reader = self.request.makefile("rb")
            while True:
                line = reader.readline()
                if not line:
                    return
                if line.strip() == b"W":
                    self.request.sendall(b"US,GS,  13000kg\r\n")
        for _ in range(5 if mode == "short" else 200):
            try:
                self.request.sendall(b"ST,GS,  12450kg\r\n")
            except OSError:
                return
            time.sleep(0.05)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mode):
        socketserver.ThreadingTCPServer.__init__(self, ("127.0.0.1", 0), _StreamHandler)
        self.mode, self.connections = mode, 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


def _wait(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.03)
    return False


class TestTcpScale(unittest.TestCase):
    def test_streaming_indicator(self):
        server = _Server("stream")
        p = scale.TcpScaleProvider("127.0.0.1", server.server_address[1])
        try:
            p.connect()
            self.assertTrue(p.device_fed and p.connected)
            self.assertTrue(_wait(lambda: p.read() is not None))
            r = p.read()
            self.assertEqual((r.weight, r.stable), (12450, True))
            self.assertIn("STABIL", p.status_text())
        finally:
            p.disconnect()
            server.stop()
        self.assertFalse(p.connected)

    def test_poll_command_and_unstable_flag(self):
        server = _Server("poll")
        p = scale.TcpScaleProvider("127.0.0.1", server.server_address[1], poll_cmd="W\\r\\n")
        try:
            p.connect()
            self.assertTrue(_wait(lambda: p.read() is not None))
            self.assertEqual((p.read().weight, p.read().stable), (13000, False))
            self.assertIn("TIDAK STABIL", p.status_text())
        finally:
            p.disconnect()
            server.stop()

    def test_auto_reconnect(self):
        server = _Server("short")
        p = scale.TcpScaleProvider("127.0.0.1", server.server_address[1], retry_seconds=0.1)
        try:
            p.connect()
            self.assertTrue(_wait(lambda: server.connections >= 2, 4.0))     # server menutup, klien menyambung lagi
            self.assertTrue(_wait(lambda: p.read() is not None))
        finally:
            p.disconnect()
            server.stop()

    def test_connection_refused_raises(self):
        server = _Server("stream")
        port = server.server_address[1]
        server.stop()
        with self.assertRaises(OSError):
            scale.TcpScaleProvider("127.0.0.1", port, connect_timeout=1).connect()

    def test_unescape(self):
        self.assertEqual(scale._unescape("W\\r\\n"), b"W\r\n")
        self.assertEqual(scale._unescape(""), b"")

    def test_stream_parser_handles_split_frames(self):
        sp = scale.StreamParser()
        self.assertEqual(sp.feed(b"ST,GS,  124"), [])
        self.assertEqual(sp.feed(b"50kg\r\nUS,GS,  1"), [(12450, True)])
        self.assertEqual(sp.feed(b"3000kg\r\n"), [(13000, False)])


class TestScaleServiceTcp(Base):
    def test_service_uses_tcp_and_falls_back(self):
        server = _Server("stream")
        settings.set_many({"scale_type": "TCP", "tcp_host": "127.0.0.1", "tcp_port": server.server_address[1]})
        svc = scale.ScaleService()
        try:
            svc.configure()
            self.assertTrue(svc.device_fed and svc.healthy() and svc.message == "")
            self.assertTrue(_wait(lambda: svc.read() is not None))
        finally:
            svc.shutdown()
            server.stop()
        settings.set("tcp_port", server.server_address[1])          # server sudah mati
        svc.configure()
        self.assertFalse(svc.device_fed)
        self.assertIn("TCP", svc.message)


class TestLayout(Base):
    def setUp(self):
        super().setUp()
        self.DATA = ticket.sample_data()

    def test_default_layout_content(self):
        items = layout.render_layout(layout.DEFAULT_LAYOUT, self.DATA)
        text = repr(items)
        for needle in ("TM-001", "16.800 KG", "7,00 m³", "TIKET TIMBANGAN", "Proyek Gedung A"):
            self.assertIn(needle, text)
        self.assertNotIn("CETAK ULANG", text)              # show_if reprint
        self.assertNotIn("Supplier", text)                 # baris kosong disembunyikan
        d = dict(self.DATA, reprint=True, truck_code="")
        text = repr(layout.render_layout(layout.DEFAULT_LAYOUT, d))
        self.assertIn("CETAK ULANG", text)
        self.assertNotIn("Kode Truk", text)

    def test_sanitize(self):
        dirty = [{"type": "text", "text": 5, "align": "weird", "size": 99, "bold": "yes", "evil": "x"},
                 {"type": "nope"}, "bukan dict", {"type": "row", "label": "A", "value": "{plate}", "show_if": " "}]
        clean = layout.sanitize(dirty)
        self.assertEqual(clean[0], {"type": "text", "text": "5", "align": "left", "size": 14, "bold": False})
        self.assertEqual(clean[1], {"type": "row", "label": "A", "value": "{plate}"})
        self.assertEqual(layout.sanitize("rusak"), [])
        self.assertEqual(layout.layout_from_json("{bukan json"), [])

    def test_lua_generation_escapes(self):
        lua = layout.layout_to_lua([{"type": "text", "text": 'Dia bilang "hai"\\ baris\nbaru'}])
        self.assertIn('text = "Dia bilang \\"hai\\"\\\\ baris\\nbaru"', lua)
        self.assertIn("function T.render", lua)
        self.assertIn("function T.get_layout", lua)

    def test_default_lua_file_in_sync(self):
        with open(os.path.join(ROOT, "lua", "templates", "ticket.lua"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), layout.layout_to_lua(layout.DEFAULT_LAYOUT))

    def test_model_operations(self):
        m = layout.TemplateModel([])
        self.assertEqual(m.add("text"), 0)
        self.assertEqual(m.add_field("plate"), 1)
        self.assertEqual(m.add("sep", row=0), 0)
        self.assertEqual([e["type"] for e in m.layout], ["sep", "text", "row"])
        self.assertEqual(m.layout[2]["value"], "{plate}")
        self.assertEqual(m.move(2, -1), 1)
        self.assertEqual(m.move(0, -1), 0)                        # sudah di atas
        self.assertEqual([e["type"] for e in m.layout], ["sep", "row", "text"])
        self.assertEqual(m.duplicate(1), 2)
        m.update(2, "label", "Plat kendaraan")
        m.update(2, "show_if", "plate")
        self.assertEqual((m.layout[1]["label"], m.layout[2]["label"], m.layout[2]["show_if"]), ("No. Polisi", "Plat kendaraan", "plate"))
        m.update(2, "show_if", "")
        self.assertNotIn("show_if", m.layout[2])
        with self.assertRaises(KeyError):
            m.update(0, "text", "x")                              # sep tidak punya properti text
        with self.assertRaises(ValueError):
            m.add("tidak-ada")
        m.remove(0)
        self.assertEqual(len(m.layout), 3)
        self.assertEqual(layout.TemplateModel(layout.layout_from_json(m.to_json())).layout, m.layout)

    def test_designer_save_roundtrip_and_render(self):
        m = layout.TemplateModel(layout.DEFAULT_LAYOUT)
        m.update(5, "text", "TIKET KUSTOM")
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            ticket.save_layout(m.layout)
        self.login("admin")
        ticket.save_layout(m.layout)
        self.assertEqual(ticket.get_layout(), m.layout)
        tid = self.full_trx()
        self.assertIn("TIKET KUSTOM", ticket.ticket_html(tid))     # Lua bila ada, Python bila tidak - hasil sama
        with self.assertRaises(UserError):
            ticket.save_layout([])
        ticket.reset_template()
        self.assertEqual(ticket.get_layout(), layout.sanitize(layout.DEFAULT_LAYOUT))
        self.assertIn("TIKET TIMBANGAN", ticket.ticket_html(tid))

    def test_preview_of_unsaved_source_strict(self):
        if lua_engine.get_engine().available:
            self.skipTest("hanya untuk lingkungan tanpa Lua")
        with self.assertRaises(UserError):
            ticket.render_items(self.DATA, source="return {}", strict=True)


@unittest.skipUnless(HAVE_LUPA, "lupa belum terpasang - tes Lua dilewati")
class TestLayoutLua(Base):
    def test_lua_interpreter_matches_python(self):
        eng = lua_engine.get_engine()
        data = ticket.sample_data()
        layouts = [layout.DEFAULT_LAYOUT,
                   [{"type": "text", "text": "A {plate} / {unknown}", "hide_empty": False}, {"type": "text", "text": "{supplier}"},
                    {"type": "row", "label": "S", "value": "{supplier}", "hide_empty": False},
                    {"type": "amount", "label": "X", "value": "{net_text}", "bold": True, "size": 3},
                    {"type": "big", "label": "Y", "value": "{net_text}"},
                    {"type": "text", "text": "reprint", "show_if": "reprint"}, {"type": "text", "text": "kode", "show_if": "truck_code"},
                    {"type": "sep"}, {"type": "space"}, {"type": "logo", "show_if": "has_logo"},
                    {"type": "signature", "left": "L", "right": "R", "left_name": "{operator}", "right_name": ""}]]
        for lay in layouts:
            for variant in (data, dict(data, reprint=True, supplier="PT S", truck_code="", has_logo=True)):
                lua_items = eng.call_source("cmp", layout.layout_to_lua(lay), "render", variant)
                self.assertEqual(lua_items, layout.render_layout(lay, variant))

    def test_get_layout_roundtrip_through_lua(self):
        eng = lua_engine.get_engine()
        lay = layout.sanitize(layout.DEFAULT_LAYOUT)
        self.assertEqual(layout.sanitize(eng.call_source("rt", layout.layout_to_lua(lay), "get_layout")), lay)


if __name__ == "__main__":
    unittest.main()


class TestStorageMove(Base):
    def test_move_data_home_and_lua_dir(self):
        from app.services import storage
        ini = os.path.join(self.tmp, "cfg", "scaler.ini")
        paths.configure(self.tmp, ini_path=ini)
        self.full_trx()
        new_home = os.path.join(self.tmp, "elsewhere")
        storage.move_data_home(new_home)
        copy = sqlite3.connect(os.path.join(new_home, "data", "scaler.db"))
        try:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)    # data ikut tersalin
        finally:
            copy.close()
        self.assertTrue(os.path.isfile(os.path.join(new_home, "lua", "scripts", "rules.lua")))
        self.assertEqual(paths.read_ini(ini)[0]["home"], new_home)
        with self.assertRaises(UserError):
            storage.move_data_home(new_home)                  # tujuan sudah berisi database
        with self.assertRaises(UserError):
            storage.move_data_home(paths.BASE)                # sama dengan folder sekarang
        lua_target = os.path.join(self.tmp, "my_lua")
        storage.set_lua_dir(lua_target)
        self.assertTrue(os.path.isfile(os.path.join(lua_target, "templates", "ticket.lua")))
        self.assertEqual(paths.read_ini(ini)[0]["lua_dir"], lua_target)
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            storage.move_data_home(os.path.join(self.tmp, "x"))


class TestTheme(unittest.TestCase):
    def test_qss_valid_for_both_modes(self):
        import re
        from app.ui import theme
        for tk in (theme.DARK, theme.LIGHT):
            for arrow in ("", "C:/tmp/chevron.png"):
                text = theme.qss(tk, arrow)
                self.assertNotIn("$", text)
                self.assertEqual(text.count("{"), text.count("}"))
                for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
                    for decl in [d for d in body.split(";") if d.strip()]:
                        self.assertTrue(re.match(r"^\s*[a-z-]+\s*:\s*.+$", decl.strip(), re.S), (selector, decl))
        self.assertIn("chevron.png", theme.qss(theme.DARK, "C:/tmp/chevron.png"))

    def test_token_sets_match(self):
        from app.ui import theme
        self.assertEqual(set(theme.DARK), set(theme.LIGHT))
        for tk in (theme.DARK, theme.LIGHT):
            for key, value in tk.items():
                if key != "name":
                    self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", key)
