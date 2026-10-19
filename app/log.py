import logging
import os
from logging.handlers import RotatingFileHandler

from app import paths

_configured = False


def setup():
    global _configured
    if _configured:
        return
    try:
        os.makedirs(paths.LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(os.path.join(paths.LOG_DIR, "scaler.log"),
                                      maxBytes=1000000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except Exception:
        pass
    _configured = True


def get(name):
    return logging.getLogger(name)
