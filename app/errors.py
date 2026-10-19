class UserError(Exception):
    """Pesan yang aman ditampilkan langsung ke operator (tanpa stack trace)."""


class PermissionDenied(UserError):
    pass
