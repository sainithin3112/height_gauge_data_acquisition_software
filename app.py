import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from queue import Queue, Empty
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

try:
    import serial  # pyserial
except Exception:
    serial = None

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
CFG_PATH = DATA_DIR / "config.json"

DEFAULT_CFG = {
    "serial_port": "COM3",     # "COM3" on Windows, "/dev/ttyUSB0" on Linux
    "baudrate": 9600,
    "bytesize": 8,
    "parity": "N",             # 'N', 'E', 'O'
    "stopbits": 1,
    "timeout": 0.2,            # seconds
    "unit": "mm",
    "decimal_places": 3
}

# -------------------- Config & DB helpers --------------------
def json_load(p: Path):
    import json
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def json_dump(p: Path, obj):
    import json
    p.parent.mkdir(exist_ok=True, parents=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def load_cfg():
    if CFG_PATH.exists():
        try:
            return {**DEFAULT_CFG, **json_load(CFG_PATH)}
        except Exception:
            return DEFAULT_CFG.copy()
    return DEFAULT_CFG.copy()

def save_cfg(cfg):
    json_dump(CFG_PATH, cfg)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_column(table, column, declared_type):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {row["name"] for row in cur.fetchall()}
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declared_type}")
        conn.commit()
    conn.close()

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS pellets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            op_product_lot_no TEXT,
            pellet_no TEXT,
            operator TEXT,
            notes TEXT,
            p1 REAL, p2 REAL, p3 REAL, p4 REAL, p5 REAL,
            avg REAL, min REAL, max REAL,
            done INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()
    # Make sure columns exist on old DBs
    ensure_column("pellets", "op_product_lot_no", "TEXT")

# -------------------- Serial Reader Thread --------------------
class SerialReader(threading.Thread):
    def __init__(self, cfg_getter, queue: Queue):
        super().__init__(daemon=True)
        self._cfg_getter = cfg_getter
        self._queue = queue
        self._stop = threading.Event()
        self._ser = None
        self.last_raw = None
        self.last_error = None
        self.port_open = False

    def _open_port(self):
        if serial is None:
            self.last_error = "pyserial not available"
            return
        cfg = self._cfg_getter()
        try:
            self._ser = serial.Serial(
                port=cfg.get("serial_port", "COM3"),
                baudrate=int(cfg.get("baudrate", 9600)),
                bytesize=int(cfg.get("bytesize", 8)),
                parity=str(cfg.get("parity", "N")),
                stopbits=int(cfg.get("stopbits", 1)),
                timeout=float(cfg.get("timeout", 0.2)),  # accept "0.2" or 0.2
            )
            self.port_open = True
            self.last_error = None
        except Exception as e:
            self._ser = None
            self.port_open = False
            self.last_error = f"open_port: {e}"

    def run(self):
        while not self._stop.is_set():
            if self._ser is None or (serial and not self._ser.is_open):
                self._open_port()
                time.sleep(0.5)
                continue
            try:
                # Many gauges end lines with CR only; try CR then LF
                raw = self._ser.read_until(b"\r", 128)
                if not raw:
                    raw = self._ser.read_until(b"\n", 128)

                line = raw.decode(errors="ignore").strip()
                if line:
                    self.last_raw = line
                    val = parse_value(line)
                    if val is not None:
                        self._queue.put(val)

            except Exception as e:
                self.last_error = f"read: {e}"
                try:
                    if self._ser:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self.port_open = False
                time.sleep(0.5)

    def stop(self):
        self._stop.set()
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass
        self.port_open = False

# -------------------- Parsing --------------------
VAL_RE = re.compile(r'[-+]?\d+(?:\.\d+)?')

def parse_value(s: str):
    s = s.strip()
    if not s:
        return None
    m = VAL_RE.search(s)
    if not m:
        return None
    try:
        val = float(m.group(0))
        if 0.0 <= val <= 50.0:  # sanity bounds in mm
            return val
    except ValueError:
        pass
    return None

# -------------------- App State --------------------
class SessionState:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.active = False
            self.pellet_id = None
            self.next_index = 1  # 1..5
            self.last_value = None
            self.last_time = None

    def start(self, pellet_id):
        with self.lock:
            self.active = True
            self.pellet_id = pellet_id
            self.next_index = 1
            self.last_value = None
            self.last_time = None

    def stop(self):
        self.reset()

session = SessionState()

# -------------------- Flask App --------------------
app = Flask(__name__)
cfg_cache = load_cfg()

reading_queue: Queue = Queue()
reader = SerialReader(lambda: cfg_cache, reading_queue)

def format_val(v):
    if v is None:
        return None
    places = int(cfg_cache.get("decimal_places", 3))
    return f"{v:.{places}f}"

# Use before_serving if available; fallback safely
try:
    decorator = app.before_serving
except AttributeError:
    decorator = app.before_request

@app.errorhandler(Exception)
def _log_errors(e):
    return str(e), 500

@app.before_request
def _ensure_init_once():
    pass

@decorator
def _start_services():
    if getattr(app, "_started", False):
        return
    app._started = True
    init_db()
    if not reader.is_alive():
        reader.start()

@app.route("/")
def index():
    return render_template("index.html")

def _combine_date_time(date_str, time_str, end=False):
    """
    Build ISO timestamp from date + (optional) time.
    If time missing:
       start -> 00:00:00
       end   -> 23:59:59
    """
    if not date_str:
        return None
    if not time_str:
        t = "23:59:59" if end else "00:00:00"
    else:
        t = time_str + (":00" if len(time_str) == 5 else "")
    return f"{date_str}T{t}"

@app.route("/pellets")
def pellets_view():
    # Filters
    q_date  = (request.args.get("date") or "").strip()
    q_start = (request.args.get("start") or "").strip()
    q_end   = (request.args.get("end") or "").strip()
    q_lot   = (request.args.get("op_product_lot_no") or "").strip()
    q_pel   = (request.args.get("pellet_no") or "").strip()
    q_op    = (request.args.get("operator") or "").strip()
    q_done  = (request.args.get("done") or "").strip()  # "", "0", "1"

    start_iso = _combine_date_time(q_date, q_start, end=False) if q_date else ""
    end_iso   = _combine_date_time(q_date, q_end,   end=True)  if q_date else ""

    sql = "SELECT * FROM pellets WHERE 1=1"
    params = []
    if start_iso:
        sql += " AND created_at >= ?"
        params.append(start_iso)
    if end_iso:
        sql += " AND created_at <= ?"
        params.append(end_iso)
    if q_lot:
        sql += " AND (op_product_lot_no LIKE ?)"
        params.append(f"%{q_lot}%")
    if q_pel:
        sql += " AND (pellet_no LIKE ?)"
        params.append(f"%{q_pel}%")
    if q_op:
        sql += " AND (operator LIKE ?)"
        params.append(f"%{q_op}%")
    if q_done in ("0", "1"):
        sql += " AND done=?"
        params.append(int(q_done))

    sql += " ORDER BY id DESC LIMIT 500"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    def to_vm(r):
        delta = None
        if r["max"] is not None and r["min"] is not None:
            delta = (r["max"] - r["min"])
        return {**dict(r), "delta": delta}

    rows_vm = [to_vm(r) for r in rows]
    return render_template(
        "pellets.html",
        rows=rows_vm,
        fmt=format_val,
        q={
            "date": q_date, "start": q_start, "end": q_end,
            "op_product_lot_no": q_lot,
            "pellet_no": q_pel, "operator": q_op, "done": q_done,
        }
    )

@app.route("/api/set_point", methods=["POST"])
def api_set_point():
    """
    Body: { "idx": 1..5, "value": <float> }
    Saves a point into the current active pellet and advances next_index.
    """
    data = request.get_json(force=True, silent=True) or {}
    idx = int(data.get("idx", 0))
    raw = str(data.get("value", "")).strip().replace(",", ".")
    if raw.startswith("."):
        raw = "0" + raw
    try:
        val = float(raw)
    except Exception:
        return jsonify({"ok": False, "error": "invalid value"}), 400
    if not (1 <= idx <= 5):
        return jsonify({"ok": False, "error": "idx must be 1..5"}), 400
    if not session.active or session.pellet_id is None:
        return jsonify({"ok": False, "error": "no active pellet"}), 409

    save_point(session.pellet_id, idx, val)
    if session.next_index == idx and session.next_index < 5:
        session.next_index += 1
    elif session.next_index < idx <= 5:
        session.next_index = min(idx + 1, 6)
    return jsonify({"ok": True, "next_index": session.next_index})


@app.route("/api/finish_pellet", methods=["POST"])
def api_finish_pellet():
    """
    Finalizes averages/min/max and ends the session.
    Client decides whether to start the next pellet (so numbering never skips).
    """
    if not session.active or session.pellet_id is None:
        return jsonify({"ok": False, "error": "no active pellet"}), 409
    pid = session.pellet_id
    finalize_pellet(pid)
    session.stop()
    return jsonify({"ok": True, "finished": pid})

@app.route("/api/serial_status")
def api_serial_status():
    return jsonify({
        "port": cfg_cache.get("serial_port"),
        "baudrate": cfg_cache.get("baudrate"),
        "is_open": getattr(reader, "port_open", False),
        "last_raw": getattr(reader, "last_raw", None),
        "last_error": getattr(reader, "last_error", None),
    })

@app.route("/settings", methods=["GET", "POST"])
def settings():
    global cfg_cache
    if request.method == "POST":
        for k in DEFAULT_CFG.keys():
            if k in request.form:
                v = request.form[k]
                if k in ("baudrate", "bytesize", "stopbits", "decimal_places"):
                    try:
                        v = int(v)
                    except:
                        continue
                elif k == "timeout":
                    try:
                        v = float(v)
                    except:
                        v = DEFAULT_CFG["timeout"]
                cfg_cache[k] = v
        save_cfg(cfg_cache)
        return redirect(url_for("settings"))
    return render_template("settings.html", cfg=cfg_cache)

@app.route("/api/start_pellet", methods=["POST"])
def api_start_pellet():
    data = request.get_json(force=True, silent=True) or {}
    lot       = (data.get("op_product_lot_no") or "").strip()
    pellet_no = (data.get("pellet_no") or "").strip()
    operator  = (data.get("operator") or "").strip()
    notes     = (data.get("notes") or "").strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pellets (created_at, op_product_lot_no, pellet_no, operator, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(timespec="seconds"), lot, pellet_no, operator, notes))
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    session.start(pid)
    return jsonify({"ok": True, "pellet_id": pid})

@app.route("/api/cancel_pellet", methods=["POST"])
def api_cancel_pellet():
    session.stop()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    # drain queue (apply values if active)
    applied = []
    while True:
        try:
            val = reading_queue.get_nowait()
        except Empty:
            break
        session.last_value = val
        session.last_time = datetime.now().isoformat(timespec="seconds")
        applied.append(val)

        if session.active and session.next_index <= 5:
            idx = session.next_index
            save_point(session.pellet_id, idx, val)
            session.next_index += 1
            if session.next_index > 5:
                finalize_pellet(session.pellet_id)
                session.stop()

    return jsonify({
        "active": session.active,
        "pellet_id": session.pellet_id,
        "next_index": session.next_index,
        "last_value": session.last_value,
        "last_time": session.last_time,
        "applied": applied,
        "unit": cfg_cache.get("unit", "mm"),
    })

def save_point(pid: int, idx: int, val: float):
    col = f"p{idx}"
    conn = get_db()
    conn.execute(f"UPDATE pellets SET {col}=? WHERE id=?", (val, pid))
    conn.commit()
    conn.close()

def finalize_pellet(pid: int):
    conn = get_db()
    row = conn.execute("SELECT p1,p2,p3,p4,p5 FROM pellets WHERE id=?", (pid,)).fetchone()
    vals = [row["p1"], row["p2"], row["p3"], row["p4"], row["p5"]]
    nums = [v for v in vals if isinstance(v, (int, float)) and v is not None]
    if nums:
        avg = sum(nums) / len(nums)
        mn = min(nums)
        mx = max(nums)
    else:
        avg = mn = mx = None
    conn.execute(
        "UPDATE pellets SET avg=?, min=?, max=?, done=1 WHERE id=?",
        (avg, mn, mx, pid)
    )
    conn.commit()
    conn.close()

@app.route("/api/export.csv")
def api_export_csv():
    # same filters as /pellets
    q_date  = (request.args.get("date") or "").strip()
    q_start = (request.args.get("start") or "").strip()
    q_end   = (request.args.get("end") or "").strip()
    q_lot   = (request.args.get("op_product_lot_no") or "").strip()
    q_pel   = (request.args.get("pellet_no") or "").strip()
    q_op    = (request.args.get("operator") or "").strip()
    q_done  = (request.args.get("done") or "").strip()

    start_iso = _combine_date_time(q_date, q_start, end=False) if q_date else ""
    end_iso   = _combine_date_time(q_date, q_end,   end=True)  if q_date else ""

    sql = "SELECT * FROM pellets WHERE 1=1"
    params = []
    if start_iso:
        sql += " AND created_at >= ?"
        params.append(start_iso)
    if end_iso:
        sql += " AND created_at <= ?"
        params.append(end_iso)
    if q_lot:
        sql += " AND (op_product_lot_no LIKE ?)"
        params.append(f"%{q_lot}%")
    if q_pel:
        sql += " AND (pellet_no LIKE ?)"
        params.append(f"%{q_pel}%")
    if q_op:
        sql += " AND (operator LIKE ?)"
        params.append(f"%{q_op}%")
    if q_done in ("0", "1"):
        sql += " AND done=?"
        params.append(int(q_done))
    sql += " ORDER BY id ASC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    import csv, io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([
        "id","created_at","op_product_lot_no","pellet_no","operator","notes",
        "p1","p2","p3","p4","p5","avg","min","max","done"
    ])
    for r in rows:
        w.writerow([
            r["id"], r["created_at"], r["op_product_lot_no"],
            r["pellet_no"], r["operator"], r["notes"],
            r["p1"], r["p2"], r["p3"], r["p4"], r["p5"],
            r["avg"], r["min"], r["max"], r["done"]
        ])
    mem = io.BytesIO(out.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv",
                     as_attachment=True, download_name="pellets_export.csv")

if __name__ == "__main__":
    print("-> Starting Flask app on http://127.0.0.1:5000")
    init_db()
    # Avoid reloader (prevents double-open of COM port)
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
