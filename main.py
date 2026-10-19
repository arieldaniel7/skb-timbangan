"""Scaler - aplikasi jembatan timbang offline (Python + PyQt5 + SQLite + Lua).

Pilihan folder (opsional):  python main.py --home D:\\ScalerData --lua-dir D:\\ScalerSkrip
atau env SCALER_HOME / SCALER_LUA_DIR, atau file scaler.ini. Lihat README."""
import sys
import traceback

from app import log, paths


def _excepthook(exc_type, exc, tb):
    log.get("main").error("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
    try:
        from app.ui import widgets as w
        w.error(None, "Terjadi kesalahan tak terduga.\nDetail teknis tersimpan di folder logs.")
    except Exception:
        pass


def _force_password_change():
    from app.errors import UserError
    from app.authentication import auth
    from app.authentication.session import session
    from app.ui import widgets as w
    while True:
        res = w.prompt_fields(None, "Ganti password awal", [
            {"key": "p1", "label": "Password baru (min. 6 karakter)", "required": True, "password": True},
            {"key": "p2", "label": "Ulangi password baru", "required": True, "password": True}])
        if res is None:
            return  # boleh dilewati; akan ditanya lagi saat login berikutnya
        if res["p1"] != res["p2"]:
            w.warn(None, "Kedua password tidak sama.")
            continue
        try:
            auth.change_password(session.user["id"], res["p1"])
            return
        except UserError as exc:
            w.warn(None, str(exc))


def main():
    rest = paths.resolve()                     # --home / --lua-dir / --config / env / scaler.ini
    sys.excepthook = _excepthook
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QDialog

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication([sys.argv[0]] + rest)
    from app.ui import theme
    from app.ui import widgets as w
    theme.apply(app, "dark")

    try:
        paths.seed_resources()                 # salin skrip Lua bawaan ke folder Lua bila belum ada
        log.setup()
    except OSError as exc:
        w.error(None, "Folder data tidak dapat ditulis:\n%s\n\nPilih folder lain dengan --home atau scaler.ini." % exc)
        return 1
    logger = log.get("main")

    from app.errors import UserError
    from app.database import db
    from app.services import backup, settings
    try:
        db.init()
        backup.auto_daily()
        theme.apply(app, settings.get("theme"))
    except UserError as exc:
        w.error(None, str(exc))
        return 1
    except Exception:
        logger.exception("Gagal memulai database")
        w.error(None, "Aplikasi gagal dimulai (database).\nDetail teknis ada di folder logs.")
        return 1

    from app.authentication import auth
    from app.authentication.session import session
    from app.weighing.scale import ScaleService
    from app.ui.login import LoginDialog
    from app.ui.main_window import MainWindow

    scale = ScaleService()
    scale.configure()
    while True:
        dlg = LoginDialog()
        if dlg.exec_() != QDialog.Accepted:
            break
        if session.user["must_change"]:
            _force_password_change()
        win = MainWindow(scale)
        win.showMaximized()
        app.exec_()
        again = win.relogin
        auth.logout()
        win.deleteLater()
        if not again:
            break
    scale.shutdown()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
