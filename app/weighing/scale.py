"""Abstraksi timbangan.UI tidak pernah menyentuh COM port langsung:

    UI -> ScaleService -> ScaleProvider (Manual | Serial | TCP)
"""
import codecs
import re
import socket
import threading
import time

from app import log
from app.services import settings

logger = log.get(__name__)

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_UNSTABLE = re.compile(r"\bUS\b", re.IGNORECASE)


class Reading(object):
    def __init__(self, weight, stable, timestamp):
        self.weight, self.stable, self.timestamp = weight, stable, timestamp


def parse_line(line):
    """Parser generik satu baris indikator -> (kg:int, stabil:bool) atau None.

    Mengambil angka pertama pada baris; token 'US' berarti tidak stabil (format umum 'ST,GS,  12450kg').
    Sesuaikan fungsi ini bila format indikator Anda berbeda."""
    text = (line or "").strip()
    if not text:
        return None
    m = _NUMBER.search(text)
    if not m:
        return None
    try:
        value = float(m.group(0))
    except ValueError:
        return None
    return max(0, int(round(value))), not _UNSTABLE.search(text)


class StreamParser(object):
    """Pecah aliran byte dari indikator menjadi baris, lalu parse. Dipakai Serial dan TCP."""

    def __init__(self):
        self._buf = ""

    def feed(self, data):
        self._buf += data.decode("ascii", "ignore") if isinstance(data, bytes) else data
        if len(self._buf) > 4000:
            self._buf = self._buf[-500:]
        parts = re.split(r"[\r\n]+", self._buf)
        self._buf = parts.pop()
        return [p for p in (parse_line(line) for line in parts) if p]


class ScaleProvider(object):
    name = "Provider"
    device_fed = False      # True bila berat berasal dari perangkat (serial/TCP): input manual dikunci, wajib stabil

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        pass

    @property
    def connected(self):
        return False

    def read(self):
        """Reading terbaru atau None bila tidak ada data."""
        return None

    def status_text(self):
        return ""


class ManualScaleProvider(ScaleProvider):
    name = "Manual"

    def connect(self):
        pass

    @property
    def connected(self):
        return True

    def status_text(self):
        return "Mode manual - ketik berat dengan keyboard"


class SerialScaleProvider(ScaleProvider):
    device_fed = True
    STALE_SECONDS = 3.0

    def __init__(self, port, baud=9600, databits=8, parity="None", stopbits=1):
        self.port, self.baud, self.databits, self.stopbits = port, baud, databits, stopbits
        self.parity = {"None": "N", "Even": "E", "Odd": "O"}.get(parity, "N")
        self._ser = None
        self._last = None
        self._failed = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.name = "Serial " + port

    def connect(self):
        import serial  # pyserial
        self._ser = serial.Serial(port=self.port, baudrate=self.baud, bytesize=self.databits, parity=self.parity,
                                  stopbits=self.stopbits, timeout=0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scale-reader", daemon=True)
        self._thread.start()

    def _loop(self):
        parser = StreamParser()
        while not self._stop.is_set():
            try:
                data = self._ser.read(64)
            except Exception:
                logger.exception("Pembacaan serial gagal")
                self._failed = True
                return
            if not data:
                continue
            for weight, stable in parser.feed(data):
                with self._lock:
                    self._last = Reading(weight, stable, time.time())

    def disconnect(self):
        self._stop.set()
        try:
            if self._ser is not None and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass

    @property
    def connected(self):
        return self._ser is not None and bool(self._ser.is_open) and not self._failed

    def read(self):
        with self._lock:
            last = self._last
        if last is None or time.time() - last.timestamp > self.STALE_SECONDS:
            return None
        return last

    def status_text(self):
        if not self.connected:
            return "Timbangan terputus"
        r = self.read()
        if r is None:
            return "Terhubung (%s) - belum ada data" % self.port
        return "Terhubung (%s) - %s" % (self.port, "STABIL" if r.stable else "TIDAK STABIL")


def _unescape(text):
    """'W\\r\\n' (diketik di pengaturan) -> b'W\r\n'."""
    if not text:
        return b""
    try:
        return codecs.decode(text, "unicode_escape").encode("latin-1", "ignore")
    except Exception:
        return text.encode("ascii", "ignore")


class TcpScaleProvider(ScaleProvider):
    """Indikator timbangan lewat TCP/IP (konverter serial-ke-ethernet atau indikator berjaringan).

    Sambungan pertama harus berhasil (kesalahan konfigurasi langsung terlihat); bila putus di tengah jalan,
    thread latar mencoba menyambung kembali otomatis. poll_cmd (opsional) dikirim tiap 0,5 detik untuk
    indikator yang hanya menjawab bila diminta."""
    device_fed = True
    STALE_SECONDS = 3.0

    def __init__(self, host, port, poll_cmd="", connect_timeout=3.0, retry_seconds=2.0):
        self.host, self.port = host, int(port)
        self.poll_cmd = _unescape(poll_cmd)
        self.connect_timeout, self.retry_seconds = connect_timeout, retry_seconds
        self.name = "TCP %s:%s" % (host, port)
        self._sock = None
        self._connected = False
        self._last = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def connect(self):
        self._open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scale-tcp", daemon=True)
        self._thread.start()

    def _open(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        sock.settimeout(0.5)
        self._sock = sock
        self._connected = True

    def _drop(self):
        self._connected = False
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _loop(self):
        parser = StreamParser()
        last_poll = 0.0
        while not self._stop.is_set():
            if self._sock is None:
                try:
                    self._open()
                    parser = StreamParser()
                except OSError as exc:
                    logger.warning("TCP timbangan %s:%s belum tersambung: %s", self.host, self.port, exc)
                    self._stop.wait(self.retry_seconds)
                    continue
            try:
                if self.poll_cmd and time.time() - last_poll >= 0.5:
                    self._sock.sendall(self.poll_cmd)
                    last_poll = time.time()
                data = self._sock.recv(256)
                if not data:
                    raise OSError("koneksi ditutup oleh timbangan")
            except socket.timeout:
                continue
            except (OSError, AttributeError) as exc:
                if self._stop.is_set():
                    break                       # sengaja diputus (disconnect), bukan gangguan
                logger.warning("TCP timbangan terputus: %s", exc)
                self._drop()
                self._stop.wait(self.retry_seconds)
                continue
            for weight, stable in parser.feed(data):
                with self._lock:
                    self._last = Reading(weight, stable, time.time())

    def disconnect(self):
        self._stop.set()
        self._drop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(1.5)

    @property
    def connected(self):
        return self._connected

    def read(self):
        with self._lock:
            last = self._last
        if last is None or time.time() - last.timestamp > self.STALE_SECONDS:
            return None
        return last

    def status_text(self):
        if not self._connected:
            return "Timbangan TCP terputus - mencoba menyambung kembali"
        r = self.read()
        where = "%s:%s" % (self.host, self.port)
        if r is None:
            return "Terhubung (%s) - belum ada data" % where
        return "Terhubung (%s) - %s" % (where, "STABIL" if r.stable else "TIDAK STABIL")


class ScaleService(object):
    def __init__(self):
        self.provider = ManualScaleProvider()
        self.message = ""

    def configure(self):
        """Baca pengaturan; bila serial gagal, jatuh ke mode manual dengan pesan yang jelas."""
        self.provider.disconnect()
        self.message = ""
        kind = settings.get("scale_type")
        if kind == "TCP":
            try:
                p = TcpScaleProvider(settings.get("tcp_host"), settings.get_int("tcp_port", 4001),
                                     settings.get("tcp_poll_cmd"))
                p.connect()
                self.provider = p
                return
            except Exception:
                logger.exception("Tidak dapat terhubung ke timbangan TCP")
                self.message = "Tidak dapat terhubung ke timbangan TCP. Aplikasi berjalan dalam mode manual."
        elif kind == "Serial":
            try:
                p = SerialScaleProvider(settings.get("com_port"), settings.get_int("baud", 9600),
                                        settings.get_int("databits", 8), settings.get("parity"),
                                        settings.get_int("stopbits", 1))
                p.connect()
                self.provider = p
                return
            except Exception:
                logger.exception("Tidak dapat membuka timbangan serial")
                self.message = "Tidak dapat terhubung ke timbangan. Aplikasi berjalan dalam mode manual."
        self.provider = ManualScaleProvider()

    @property
    def device_fed(self):
        return self.provider.device_fed

    def read(self):
        return self.provider.read()

    def status_text(self):
        return self.message or self.provider.status_text()

    def healthy(self):
        return self.provider.connected

    def shutdown(self):
        self.provider.disconnect()
