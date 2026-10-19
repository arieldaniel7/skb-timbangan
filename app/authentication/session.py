"""Sesi login dan matriks izin berbasis role."""
from app.errors import PermissionDenied

_OPERATOR = {"weigh", "print", "view_trx"}
_SUPERVISOR = _OPERATOR | {"reprint", "void", "edit_master", "reports", "edit_trx"}
_ADMIN = _SUPERVISOR | {"manage_users", "settings", "backup", "audit", "edit_template"}

PERMISSIONS = {"OPERATOR": _OPERATOR, "SUPERVISOR": _SUPERVISOR, "ADMIN": _ADMIN}


class _Session(object):
    user = None


session = _Session()


def current_username():
    return session.user["username"] if session.user else "-"


def can(permission):
    user = session.user
    return bool(user) and permission in PERMISSIONS.get(user["role"], ())


def require(permission):
    if not session.user:
        raise PermissionDenied("Silakan login terlebih dahulu.")
    if not can(permission):
        raise PermissionDenied("Anda tidak memiliki izin untuk tindakan ini.")
