import datetime
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import paths, util                                   # noqa: E402
from app.errors import UserError, PermissionDenied            # noqa: E402
from app.database import db                                   # noqa: E402
from app.authentication import auth                           # noqa: E402
from app.authentication.session import session                # noqa: E402
from app.services import weighing, masterdata, backup, settings  # noqa: E402
from app.weighing import scale                                # noqa: E402
from app.reports import service as reports, export            # noqa: E402
from app.printing import ticket                               # noqa: E402
from app.scripting import lua_engine                          # noqa: E402

try:
    import lupa  # noqa: F401
    HAVE_LUPA = True
except Exception:
    HAVE_LUPA = False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        paths.configure(self.tmp)
        paths.seed_resources()
        db.close()
        lua_engine.reset_engine()
        db.init()
        self.login("admin")

    def tearDown(self):
        db.close()
        session.user = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, username):
        row = db.query_one("SELECT id FROM users WHERE username=?", (username,))
        auth.login(row["id"], username + "123")

    def ids(self):
        cust = db.scalar("SELECT id FROM customers LIMIT 1")
        mat = db.scalar("SELECT id FROM materials WHERE code='K-300'")
        return cust, mat

    def full_trx(self, plate="AE 1234 XY", first=13650, second=30450):
        cust, mat = self.ids()
        r = weighing.start_first(plate, cust, mat, first, destination="Proyek A", driver="Budi", volume=7, create_truck=True)
        weighing.complete_second(r["id"], second)
        return r["id"]


class TestUtil(unittest.TestCase):
    def test_plate(self):
        self.assertEqual(util.normalize_plate("b-1234 xyz"), "B1234XYZ")
        self.assertEqual(util.normalize_plate("B 1234 XYZ"), util.normalize_plate("B1234XYZ"))

    def test_parse_weight(self):
        self.assertEqual(util.parse_weight("12.450 kg"), 12450)
        self.assertEqual(util.parse_weight(" 7850 "), 7850)
        for bad in ("", "abc", "-5", "0 kg x -"):
            if bad == "0 kg x -" or bad in ("", "abc", "-5"):
                with self.assertRaises(UserError):
                    util.parse_weight(bad)

    def test_quantize(self):
        self.assertEqual(util.quantize(12453, 1), 12453)
        self.assertEqual(util.quantize(12453, 5), 12455)
        self.assertEqual(util.quantize(12454, 10), 12450)
        self.assertEqual(util.quantize(12455, 10), 12460)

    def test_format(self):
        self.assertEqual(util.format_weight(12450), "12.450 KG")
        self.assertEqual(util.format_weight(12450, "TON"), "12,45 TON")


class TestAuth(Base):
    def test_hash_and_verify(self):
        h = auth.hash_password("rahasia1")
        self.assertNotIn("rahasia1", h)
        self.assertTrue(auth.verify_password("rahasia1", h))
        self.assertFalse(auth.verify_password("salah", h))
        self.assertNotEqual(h, auth.hash_password("rahasia1"))

    def test_wrong_password(self):
        session.user = None
        row = db.query_one("SELECT id FROM users WHERE username='admin'")
        with self.assertRaises(UserError):
            auth.login(row["id"], "salah")

    def test_permissions(self):
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            auth.create_user("x", "X", "OPERATOR", "abcdef")
        with self.assertRaises(PermissionDenied):
            masterdata.create("customers", {"code": "Z", "name": "Z"})

    def test_user_management(self):
        uid = auth.create_user("Budi", "Budi S", "OPERATOR", "budi123")
        self.assertEqual(db.scalar("SELECT username FROM users WHERE id=?", (uid,)), "budi")
        with self.assertRaises(UserError):
            auth.create_user("budi", "Dup", "OPERATOR", "budi123")
        with self.assertRaises(UserError):
            auth.create_user("pendek", "P", "OPERATOR", "123")
        admin_id = session.user["id"]
        with self.assertRaises(UserError):
            auth.update_user(admin_id, "Administrator", "ADMIN", False)

    def test_must_change(self):
        self.assertTrue(session.user["must_change"])
        auth.change_password(session.user["id"], "baru1234")
        self.assertFalse(session.user["must_change"])
        self.assertEqual(db.scalar("SELECT must_change FROM users WHERE username='admin'"), 0)


class TestWeighing(Base):
    def test_compute(self):
        self.assertEqual(weighing.compute(12450, 7850), (12450, 7850, 4600))
        self.assertEqual(weighing.compute(7850, 12450), (12450, 7850, 4600))

    def test_full_flow(self):
        cust, mat = self.ids()
        r = weighing.start_first("ae 1234 xy", cust, mat, 13650, destination="Proyek A", driver="Budi", volume=7)
        today = datetime.date.today().strftime("%Y%m%d")
        self.assertEqual(r["number"], "TICK-%s-0001" % today)
        open_trx = weighing.find_open("AE1234XY")
        self.assertEqual(open_trx["id"], r["id"])
        self.assertEqual(open_trx["status"], weighing.STATUS_WAITING)
        prev = weighing.preview_second(r["id"], 30450)
        self.assertEqual((prev["gross"], prev["tare"], prev["net"]), (30450, 13650, 16800))
        weighing.complete_second(r["id"], 30450)
        t = weighing.get_transaction(r["id"])
        self.assertEqual(t["status"], weighing.STATUS_COMPLETED)
        self.assertEqual((t["gross_weight"], t["tare_weight"], t["net_weight"]), (30450, 13650, 16800))
        self.assertIsNone(weighing.find_open("AE 1234 XY"))
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM transaction_weights WHERE transaction_id=?", (r["id"],)), 2)

    def test_second_lighter_than_first(self):
        tid = self.full_trx(first=30450, second=13650)
        t = weighing.get_transaction(tid)
        self.assertEqual((t["gross_weight"], t["tare_weight"], t["net_weight"]), (30450, 13650, 16800))

    def test_invalid_weights(self):
        cust, mat = self.ids()
        for bad in (0, -5):
            with self.assertRaises(UserError):
                weighing.start_first("AE 1234 XY", cust, mat, bad)
        with self.assertRaises(UserError):
            weighing.start_first("AE 1234 XY", cust, mat, weighing.MAX_WEIGHT_KG + 1)
        r = weighing.start_first("AE 1234 XY", cust, mat, 13650)
        with self.assertRaises(UserError):
            weighing.complete_second(r["id"], 13650)  # sama dengan timbangan pertama
        with self.assertRaises(UserError):
            weighing.complete_second(r["id"], 0)

    def test_duplicate_open_blocked(self):
        cust, mat = self.ids()
        weighing.start_first("AE 1234 XY", cust, mat, 13650)
        with self.assertRaises(UserError):
            weighing.start_first("ae-1234-xy", cust, mat, 14000)

    def test_cannot_complete_twice(self):
        tid = self.full_trx()
        with self.assertRaises(UserError):
            weighing.complete_second(tid, 20000)

    def test_unknown_truck(self):
        cust, mat = self.ids()
        with self.assertRaises(UserError):
            weighing.start_first("B 9999 ZZ", cust, mat, 10000)
        r = weighing.start_first("B 9999 ZZ", cust, mat, 10000, create_truck=True)
        self.assertEqual(masterdata.truck_by_plate("b9999zz")["plate_display"], "B 9999 ZZ")
        self.assertTrue(r["id"])

    def test_inactive_master_blocked(self):
        cust, mat = self.ids()
        masterdata.toggle_active("customers", cust)
        with self.assertRaises(UserError):
            weighing.start_first("AE 1234 XY", cust, mat, 10000)
        masterdata.toggle_active("customers", cust)
        tid = masterdata.truck_by_plate("AE1234XY")["id"]
        masterdata.toggle_active("trucks", tid)
        with self.assertRaises(UserError):
            weighing.start_first("AE 1234 XY", cust, mat, 10000)

    def test_numbering_sequence_and_rollback(self):
        cust, mat = self.ids()
        a = weighing.start_first("B 1 A", cust, mat, 10000, create_truck=True)
        b = weighing.start_first("B 2 A", cust, mat, 10000, create_truck=True)
        self.assertTrue(a["number"].endswith("-0001"))
        self.assertTrue(b["number"].endswith("-0002"))
        before = db.scalar("SELECT value FROM counters")
        with self.assertRaises(UserError):  # gagal di tengah transaksi -> counter ikut rollback
            weighing.start_first("B 1 A", cust, mat, 10000)
        self.assertEqual(db.scalar("SELECT value FROM counters"), before)

    def test_void_rules(self):
        cust, mat = self.ids()
        waiting = weighing.start_first("B 7 A", cust, mat, 10000, create_truck=True)
        done = self.full_trx()
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            weighing.void_transaction(done, "salah input")
        self.login("supervisor")
        with self.assertRaises(UserError):
            weighing.void_transaction(done, "  ")
        self.assertEqual(weighing.void_transaction(done, "salah input"), weighing.STATUS_VOID)
        self.assertEqual(weighing.void_transaction(waiting["id"], "truk batal"), weighing.STATUS_CANCELLED)
        with self.assertRaises(UserError):
            weighing.void_transaction(done, "lagi")
        self.assertIsNone(weighing.find_open("B 7 A"))

    def test_audit_trail(self):
        self.full_trx()
        actions = [r[0] for r in db.query("SELECT action FROM audit_logs")]
        for a in ("LOGIN", "TIMBANG PERTAMA", "TIMBANG KEDUA"):
            self.assertIn(a, actions)

    def test_list_and_stats(self):
        self.full_trx()
        today = datetime.date.today()
        rows, total = weighing.list_transactions(today, today, "ae1234")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["net_weight"], 16800)
        rows, total = weighing.list_transactions(today, today, "tidak-ada")
        self.assertEqual(total, 0)
        stats = weighing.today_stats()
        self.assertEqual((stats["count"], stats["net_kg"], stats["waiting"]), (1, 16800, 0))

    def test_foreign_keys_enforced(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO transactions(trx_number, truck_id, customer_id, material_id, status, created_at)"
                       " VALUES('X', 999, 999, 999, 'COMPLETED', '2026-01-01 00:00:00')")


class TestMaster(Base):
    def test_unique_and_normalization(self):
        masterdata.create("customers", {"code": "C100", "name": "PT Baru"})
        with self.assertRaises(UserError):
            masterdata.create("customers", {"code": "C100", "name": "Lain"})
        with self.assertRaises(UserError):
            masterdata.create("customers", {"code": "", "name": "Tanpa kode"})
        tid = masterdata.create("trucks", {"plate_display": "b1234xyz", "truck_code": "tm-002"})
        row = masterdata.get("trucks", tid)
        self.assertEqual((row["plate"], row["plate_display"], row["truck_code"]), ("B1234XYZ", "B 1234 XYZ", "TM-002"))
        with self.assertRaises(UserError):
            masterdata.create("trucks", {"plate_display": "B1234XYZ"})
        with self.assertRaises(UserError):
            masterdata.create("trucks", {"plate_display": "B 5 A", "truck_code": "TM-002"})

    def test_search_and_options(self):
        self.assertEqual(masterdata.search_trucks("ae 12"), ["AE 1234 XY"])
        self.assertTrue(masterdata.options("materials"))
        self.assertEqual(masterdata.options("suppliers", optional=True)[0], (0, "(tanpa)"))
        rows = masterdata.list_rows("materials", "K-300")
        self.assertEqual(len(rows), 1)

    def test_deactivate_keeps_history(self):
        tid = self.full_trx()
        trx = weighing.get_transaction(tid)
        masterdata.toggle_active("customers", trx["customer_id"])
        self.assertEqual(weighing.get_transaction(tid)["customer"], trx["customer"])


class TestScaleParser(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(scale.parse_line("ST,GS,  12450kg"), (12450, True))
        self.assertEqual(scale.parse_line("US,GS,  12450kg"), (12450, False))
        self.assertEqual(scale.parse_line("+012450"), (12450, True))
        self.assertEqual(scale.parse_line("12450.6 kg"), (12451, True))
        self.assertEqual(scale.parse_line("-5"), (0, True))
        self.assertIsNone(scale.parse_line(""))
        self.assertIsNone(scale.parse_line("ERR"))

    def test_manual_provider_and_fallback(self):
        s = scale.ScaleService()
        self.assertFalse(s.device_fed)
        self.assertIsNone(s.read())
        self.assertTrue(s.healthy())


class TestBackup(Base):
    def test_backup_restore_roundtrip(self):
        self.full_trx()
        path = os.path.join(self.tmp, "b.db")
        backup.backup_to(path)
        self.assertTrue(os.path.exists(path))
        self.full_trx(plate="B 5 A")
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM transactions"), 2)
        before = backup.restore(path)
        self.assertTrue(os.path.exists(before))
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM transactions"), 1)

    def test_restore_rejects_garbage(self):
        junk = os.path.join(self.tmp, "junk.db")
        with open(junk, "wb") as fh:
            fh.write(b"bukan database")
        with self.assertRaises(UserError):
            backup.restore(junk)

    def test_auto_daily_once(self):
        self.assertIsNotNone(backup.auto_daily())
        self.assertIsNone(backup.auto_daily())


class TestReports(Base):
    def test_reports(self):
        self.full_trx()
        self.full_trx(plate="B 5 A", first=10000, second=25000)
        today = datetime.date.today()
        h, rows, total, ids = reports.run("daily", today, today)
        self.assertEqual((len(rows), total, len(ids)), (2, 16800 + 15000, 2))
        h, rows, total, ids = reports.run("customer", today, today)
        self.assertEqual((len(rows), rows[0][1], total, ids), (1, 2, 31800, None))
        self.assertEqual(rows[0][3], round(31800 / 2400.0, 2))
        h, rows, total, ids = reports.run("truck_history", today, today, "tm-001")
        self.assertEqual(len(rows), 1)
        h, rows, total, ids = reports.run("truck_history", today, today, "ae1234")
        self.assertEqual(len(rows), 1)
        h, rows, total, ids = reports.run("monthly", today, today)
        self.assertEqual(rows[0][2], 31800)
        self.login("operator")
        with self.assertRaises(PermissionDenied):
            reports.run("daily", today, today)

    def test_exports(self):
        self.full_trx()
        today = datetime.date.today()
        h, rows, total, ids = reports.run("daily", today, today)
        csv_path = os.path.join(self.tmp, "r.csv")
        export.export_csv(csv_path, h, rows)
        with open(csv_path, encoding="utf-8-sig") as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 2)
        xlsx = os.path.join(self.tmp, "r.xlsx")
        export.export_xlsx(xlsx, "Harian", h, rows)
        self.assertTrue(os.path.getsize(xlsx) > 0)
        self.assertIn("16.800", export.table_html("T", "S", h, rows))


class TestTicket(Base):
    def test_ticket_html(self):
        tid = self.full_trx()
        html_text = ticket.ticket_html(tid)
        for needle in ("TICK-", "AE 1234 XY", "16.800 KG", "30.450 KG", "13.650 KG", "TIKET TIMBANGAN"):
            self.assertIn(needle, html_text)
        self.assertNotIn("CETAK ULANG", html_text)
        weighing.mark_printed(tid, "PRINT")
        self.assertIn("CETAK ULANG", ticket.ticket_html(tid))
        self.assertEqual(db.scalar("SELECT print_count FROM transactions WHERE id=?", (tid,)), 1)

    def test_html_escaping(self):
        items = [{"type": "text", "text": "<script>x</script> & ok"}]
        out = ticket.items_to_html(items, "A5")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_default_items_shape(self):
        items = ticket.default_items(ticket.sample_data())
        self.assertTrue(all(i["type"] in ticket.ITEM_TYPES for i in items))
        self.assertEqual([i for i in items if i["type"] == "big"][0]["value"], "16.800 KG")

    def test_template_seeded_from_file(self):
        self.assertIn("function T.render", ticket.template_source())


@unittest.skipUnless(HAVE_LUPA, "lupa belum terpasang - tes Lua dilewati")
class TestLua(Base):
    def test_rules_file(self):
        eng = lua_engine.get_engine()
        self.assertTrue(eng.available, eng.error)
        path = os.path.join(ROOT, "lua", "scripts", "rules.lua")
        self.assertEqual(eng.call_file(path, "format_trx_number", "20261018", 7), "TICK-20261018-0007")
        res = eng.call_file(path, "validate_second", {"gross": 30000, "net": 21000})
        self.assertEqual(res["warnings"], {})
        self.assertEqual(res["errors"], {})
        res = eng.call_file(path, "validate_first", {"weight": 300000})
        self.assertEqual(len(res["errors"]), 1)

    def test_max_net_warning_via_service(self):
        rules = os.path.join(paths.LUA_DIR, "scripts", "rules.lua")
        with open(rules, encoding="utf-8") as fh:
            src = fh.read()
        with open(rules, "w", encoding="utf-8") as fh:
            fh.write(src.replace("max_net_kg = 0,", "max_net_kg = 20000,"))
        cust, mat = self.ids()
        r = weighing.start_first("AE 1234 XY", cust, mat, 13650)
        prev = weighing.preview_second(r["id"], 40000)  # netto 26.350 > 20.000
        self.assertEqual(len(prev["warnings"]), 1)

    def test_template_renders_same_as_fallback(self):
        items = ticket.render_items(ticket.sample_data())
        self.assertEqual(items, ticket.default_items(ticket.sample_data()))

    def test_sandbox(self):
        eng = lua_engine.get_engine()
        src = "local M = {} function M.f() return {os = tostring(os), io = tostring(io), req = tostring(require)} end return M"
        res = eng.call_source("t1", src, "f")
        self.assertEqual(res, {"os": "nil", "io": "nil", "req": "nil"})

    def test_runaway_script_is_stopped(self):
        eng = lua_engine.get_engine()
        with self.assertRaises(lua_engine.LuaError):
            eng.call_source("t2", "local M = {} function M.f() while true do end end return M", "f")

    def test_bad_script(self):
        eng = lua_engine.get_engine()
        with self.assertRaises(lua_engine.LuaError):
            eng.check_source("this is not lua")
        with self.assertRaises(lua_engine.LuaError):
            eng.check_source("return 5")

    def test_save_template_validates(self):
        with self.assertRaises(UserError):
            ticket.save_template("garbage ((")
        ticket.save_template(ticket.default_template_source().replace("TIKET TIMBANGAN", "TIKET KUSTOM"))
        self.assertIn("TIKET KUSTOM", ticket.ticket_html(self.full_trx()))
        ticket.reset_template()
        self.assertIn("TIKET TIMBANGAN", ticket.ticket_html(self.full_trx(plate="B 5 A")))


if __name__ == "__main__":
    unittest.main()
