"""Lua tertanam (lupa) untuk template tiket & aturan bisnis yang bisa diubah tanpa menyentuh kode Python.

Sandbox: tanpa os/io/package/require/debug/load; batas instruksi per panggilan agar script
yang salah tidak membekukan aplikasi. Jika lupa tidak terpasang, aplikasi tetap berjalan dengan
perilaku bawaan (Python)."""
import hashlib
import os

from app import log

logger = log.get(__name__)


class LuaError(Exception):
    pass


_BOOTSTRAP = """
local sethook = debug.sethook
safe_call = function(fn, ...)
  sethook(function() error("batas instruksi script terlampaui", 0) end, "", 5000000)
  local ok, res = pcall(fn, ...)
  sethook()
  if not ok then error(res, 0) end
  return res
end
os = nil; io = nil; package = nil; require = nil; dofile = nil; loadfile = nil
debug = nil; load = nil; loadstring = nil; python = nil
"""


class LuaEngine(object):
    def __init__(self):
        self.available = False
        self.error = ""
        self._modules = {}
        try:
            import lupa
        except Exception as exc:
            self.error = "Modul 'lupa' tidak terpasang (%s)" % exc
            return
        try:
            self._lupa = lupa
            self._lua = lupa.LuaRuntime(unpack_returned_tuples=True, register_eval=False)
            self._loader = self._lua.eval("load")
            self._new_env = self._lua.eval("function() return setmetatable({}, {__index = _G}) end")
            self._lua.execute(_BOOTSTRAP)
            self._safe_call = self._lua.globals()["safe_call"]
            self.available = True
        except Exception as exc:
            self.error = "Lua gagal diinisialisasi: %s" % exc
            logger.exception("Lua init gagal")

    # ---- konversi Python <-> Lua -------------------------------------------------
    def _to_lua(self, obj):
        if isinstance(obj, dict):
            t = self._lua.table()
            for k, v in obj.items():
                t[k] = self._to_lua(v)
            return t
        if isinstance(obj, (list, tuple)):
            t = self._lua.table()
            for i, v in enumerate(obj, 1):
                t[i] = self._to_lua(v)
            return t
        return obj

    def _to_py(self, obj):
        if self._lupa.lua_type(obj) != "table":
            return obj
        keys = list(obj.keys())
        if keys and all(isinstance(k, (int, float)) and float(k).is_integer() for k in keys):
            ints = sorted(int(k) for k in keys)
            if ints == list(range(1, len(ints) + 1)):
                return [self._to_py(obj[i]) for i in ints]
        return dict((k, self._to_py(v)) for k, v in obj.items())

    # ---- memuat & memanggil ---------------------------------------------------------
    def _load(self, source, chunkname):
        env = self._new_env()
        res = self._loader(source, "=" + chunkname, "t", env)
        if isinstance(res, tuple):
            fn, err = res[0], (res[1] if len(res) > 1 else "")
        else:
            fn, err = res, ""
        if fn is None:
            raise LuaError("Script %s tidak valid: %s" % (chunkname, err))
        try:
            mod = self._safe_call(fn)
        except Exception as exc:
            raise LuaError("Script %s error: %s" % (chunkname, exc))
        if self._lupa.lua_type(mod) != "table":
            raise LuaError("Script %s harus diakhiri dengan 'return M' (sebuah table)." % chunkname)
        return mod

    def _call(self, mod, func, args):
        fn = mod[func]
        if fn is None:
            raise LuaError("Fungsi '%s' tidak ada di script." % func)
        try:
            res = self._safe_call(fn, *[self._to_lua(a) for a in args])
        except Exception as exc:
            raise LuaError("Error saat menjalankan %s: %s" % (func, exc))
        return self._to_py(res)

    def _require_available(self):
        if not self.available:
            raise LuaError(self.error or "Lua tidak tersedia")

    def call_file(self, path, func, *args):
        self._require_available()
        stamp = os.path.getmtime(path)
        cached = self._modules.get(path)
        if cached is None or cached[0] != stamp:
            with open(path, "r", encoding="utf-8") as fh:
                mod = self._load(fh.read(), os.path.basename(path))
            self._modules[path] = (stamp, mod)
        else:
            mod = cached[1]
        return self._call(mod, func, args)

    def call_source(self, name, source, func, *args):
        self._require_available()
        stamp = hashlib.md5(source.encode("utf-8")).hexdigest()
        cached = self._modules.get(name)
        if cached is None or cached[0] != stamp:
            mod = self._load(source, name)
            self._modules[name] = (stamp, mod)
        else:
            mod = cached[1]
        return self._call(mod, func, args)

    def check_source(self, source, name="template"):
        """Validasi sintaks + struktur (dipakai editor template sebelum menyimpan)."""
        self._require_available()
        self._load(source, name)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = LuaEngine()
    return _engine


def reset_engine():
    global _engine
    _engine = None
