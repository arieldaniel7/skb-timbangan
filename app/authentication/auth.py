"""Autentikasi lokal: PBKDF2-HMAC-SHA256 (hashlib, kompatibel Windows 7) + manajemen pengguna."""
import base64
import hashlib
import hmac
import os

from app import util
from app.errors import UserError
from app.database import db
from app.authentication.session import session, require
from app.services import audit

ITERATIONS = 100000
ROLES = ("OPERATOR", "SUPERVISOR", "ADMIN")


def hash_password(password, iterations=ITERATIONS):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, base64.b64encode(salt).decode("ascii"),
                                       base64.b64encode(dk).decode("ascii"))


def verify_password(password, stored):
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(got, base64.b64decode(digest))
    except Exception:
        return False


def _check_password_rules(password):
    if len(password or "") < 6:
        raise UserError("Password minimal 6 karakter.")


def login_choices():
    """Daftar operator aktif untuk layar login (tanpa data sensitif)."""
    return [(r["id"], "%s (%s)" % (r["full_name"], r["username"]))
            for r in db.query("SELECT id, username, full_name FROM users WHERE active=1 ORDER BY full_name")]


def login(user_id, password):
    row = db.query_one("SELECT * FROM users WHERE id=? AND active=1", (user_id,))
    if row is None or not verify_password(password, row["password_hash"]):
        audit.log("LOGIN GAGAL", "users", user_id)
        raise UserError("Password salah.")
    session.user = {"id": row["id"], "username": row["username"], "full_name": row["full_name"],
                    "role": row["role"], "must_change": bool(row["must_change"])}
    audit.log("LOGIN", "users", row["id"])
    return session.user


def logout(reason="LOGOUT"):
    if session.user:
        audit.log(reason, "users", session.user["id"])
    session.user = None


def change_password(user_id, new_password):
    if not session.user:
        raise UserError("Silakan login terlebih dahulu.")
    if user_id != session.user["id"]:
        require("manage_users")
    _check_password_rules(new_password)
    db.execute("UPDATE users SET password_hash=?, must_change=?, updated_at=? WHERE id=?",
               (hash_password(new_password), 0 if user_id == session.user["id"] else 1, util.now_str(), user_id))
    if user_id == session.user["id"]:
        session.user["must_change"] = False
    audit.log("GANTI PASSWORD", "users", user_id)


def list_users():
    require("manage_users")
    return db.query("SELECT id, username, full_name, role, active FROM users ORDER BY username")


def create_user(username, full_name, role, password):
    require("manage_users")
    username = (username or "").strip().lower()
    if not username or not (full_name or "").strip():
        raise UserError("Username dan nama lengkap wajib diisi.")
    if role not in ROLES:
        raise UserError("Role tidak valid.")
    _check_password_rules(password)
    if db.scalar("SELECT COUNT(*) FROM users WHERE username=?", (username,)):
        raise UserError("Username sudah dipakai.")
    cur = db.execute("INSERT INTO users(username, full_name, password_hash, role, active, must_change, created_at) "
                     "VALUES(?,?,?,?,1,1,?)", (username, full_name.strip(), hash_password(password), role, util.now_str()))
    audit.log("TAMBAH PENGGUNA", "users", cur.lastrowid, None, "%s / %s" % (username, role))
    return cur.lastrowid


def update_user(user_id, full_name, role, active):
    require("manage_users")
    if role not in ROLES:
        raise UserError("Role tidak valid.")
    if user_id == session.user["id"] and (not active or role != "ADMIN"):
        raise UserError("Anda tidak dapat menonaktifkan atau menurunkan role akun Anda sendiri.")
    old = db.query_one("SELECT role, active FROM users WHERE id=?", (user_id,))
    if old is None:
        raise UserError("Pengguna tidak ditemukan.")
    db.execute("UPDATE users SET full_name=?, role=?, active=?, updated_at=? WHERE id=?",
               (full_name.strip(), role, 1 if active else 0, util.now_str(), user_id))
    audit.log("UBAH PENGGUNA", "users", user_id, "%s/%s" % (old["role"], old["active"]), "%s/%s" % (role, 1 if active else 0))
