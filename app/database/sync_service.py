"""
Sync service: local SQLite (primary) ↔ Turso (cloud backup).

- import_from_turso(): Turso → local on first run (local is empty)
- sync_to_turso(): local → Turso via batched HTTP pipeline calls
- start_background_sync(interval): daemon thread for periodic sync
"""
import shutil
import sqlite3
import threading
import time
import traceback
from datetime import datetime

import requests as _requests
import app.config as cfg

BACKUP_DIR  = cfg.DATA_DIR / "backups"
BACKUP_KEEP = 7  # days of local backups to retain

# FK-dependency order (import & sync must respect this)
_TABLE_ORDER = [
    "categorias", "proveedores", "usuarios", "clientes", "configuracion",
    "productos", "lotes", "ventas", "items_venta",
    "compras", "items_compra", "cortes_caja", "movimientos_stock", "auditoria_log",
]

# Mutable tables — always full-replace sync (stock, prices, configs change in-place)
_FULL_SYNC = frozenset({
    "categorias", "proveedores", "usuarios", "clientes", "configuracion", "productos",
})

# Watermark per table: last id synced to Turso (append-only tables only)
_watermarks: dict[str, int] = {}

_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _local_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(cfg.DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _turso_pipeline_url() -> str:
    return (
        cfg.TURSO_DATABASE_URL
        .replace("libsql://", "https://")
        .rstrip("/") + "/v2/pipeline"
    )


def _turso_headers() -> dict:
    return {
        "Authorization": f"Bearer {cfg.TURSO_AUTH_TOKEN}",
        "Content-Type":  "application/json",
    }


def _py_to_turso(v):
    """Convert Python value to Turso HTTP arg object."""
    if v is None:                return {"type": "null",    "value": None}
    if isinstance(v, bool):      return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):       return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        if v != v:               return {"type": "null",    "value": None}  # NaN
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        import base64
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _turso_batch(stmts: list[dict]) -> None:
    """
    Send multiple SQL statements in one (or a few) HTTP pipeline call(s).
    stmts = [{"sql": "...", "args": [...]}, ...]
    """
    if not stmts:
        return
    BATCH = 200  # statements per HTTP call
    url, hdrs = _turso_pipeline_url(), _turso_headers()

    for i in range(0, len(stmts), BATCH):
        chunk = stmts[i : i + BATCH]
        payload = {
            "requests": [{"type": "execute", "stmt": s} for s in chunk]
            + [{"type": "close"}]
        }
        resp = _requests.post(url, headers=hdrs, json=payload, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:300]}")
        for result in resp.json().get("results", []):
            if result.get("type") == "error":
                msg = result.get("error", {}).get("message", "unknown")
                print(f"[Sync] Turso stmt error: {msg}")


def _turso_read_table(table: str) -> tuple[list[str], list[tuple]]:
    """Read all rows from a Turso table. Returns (col_names, rows_as_python_tuples)."""
    from app.database.turso_http import connect as turso_connect
    tconn = turso_connect(cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN)
    cur = tconn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
    except Exception as e:
        print(f"[Sync] Could not read Turso:{table} — {e}")
        return [], []
    if cur.description is None:
        return [], []
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()  # already Python-typed by TursoCursor._load()
    return cols, rows


# ── Public API ────────────────────────────────────────────────────────────────

def import_from_turso() -> bool:
    """
    One-time import: copy all Turso data into local SQLite.
    Skips if local already has data (usuarios table is non-empty).
    Returns True if import ran.
    """
    lconn = _local_conn()
    try:
        n = lconn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    except Exception:
        n = 0

    if n > 0:
        lconn.close()
        print("[Sync] Local DB has data — skipping Turso import")
        return False

    print("[Sync] Local DB empty — importing from Turso...")
    try:
        lconn.execute("PRAGMA foreign_keys = OFF")
        total = 0
        for table in _TABLE_ORDER:
            try:
                cols, rows = _turso_read_table(table)
                if not cols or not rows:
                    continue
                col_str = ", ".join(cols)
                ph_str  = ", ".join(["?" for _ in cols])
                sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"
                lconn.executemany(sql, rows)
                total += len(rows)
                print(f"[Sync]   {table}: {len(rows)} rows")
            except Exception as e:
                print(f"[Sync]   Warning — {table}: {e}")
        lconn.execute("PRAGMA foreign_keys = ON")
        lconn.commit()
        print(f"[Sync] Import complete — {total} rows total")
        return True
    except Exception as e:
        lconn.rollback()
        print(f"[Sync] Import failed: {e}")
        traceback.print_exc()
        return False
    finally:
        lconn.close()


def sync_to_turso() -> None:
    """
    Push local SQLite data to Turso via batched HTTP pipeline.
    Mutable tables: full INSERT OR REPLACE.
    Append-only tables: only rows with id > last watermark.
    """
    with _lock:
        lconn = _local_conn()
        try:
            synced = 0
            for table in _TABLE_ORDER:
                try:
                    if table in _FULL_SYNC:
                        rows = lconn.execute(f"SELECT * FROM {table}").fetchall()
                    else:
                        last_id = _watermarks.get(table, 0)
                        rows = lconn.execute(
                            f"SELECT * FROM {table} WHERE id > ? ORDER BY id",
                            (last_id,),
                        ).fetchall()

                    if not rows:
                        continue

                    cols    = list(rows[0].keys())
                    col_str = ", ".join(cols)
                    ph_str  = ", ".join(["?" for _ in cols])
                    sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"

                    stmts = [
                        {"sql": sql, "args": [_py_to_turso(v) for v in tuple(row)]}
                        for row in rows
                    ]
                    _turso_batch(stmts)

                    if table not in _FULL_SYNC:
                        _watermarks[table] = max(row["id"] for row in rows)

                    synced += len(rows)
                except Exception as e:
                    print(f"[Sync] Warning — {table}: {e}")

            if synced:
                print(f"[Sync] >> Turso: {synced} rows synced")
        finally:
            lconn.close()


def make_daily_backup() -> bool:
    """
    Copy farmacia.db → backups/farmacia_YYYYMMDD.db once per day.
    Deletes backups older than BACKUP_KEEP days.
    Returns True if backup was created.
    """
    if not cfg.DB_PATH.exists():
        return False

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    dest  = BACKUP_DIR / f"farmacia_{today}.db"

    if dest.exists():
        return False  # already backed up today

    try:
        # Use SQLite backup API via a direct connection for a consistent snapshot
        src  = sqlite3.connect(str(cfg.DB_PATH))
        bkup = sqlite3.connect(str(dest))
        src.backup(bkup)
        bkup.close()
        src.close()
        print(f"[Backup] Saved {dest.name}")
    except Exception as e:
        print(f"[Backup] Failed: {e}")
        return False

    # Purge old backups beyond BACKUP_KEEP
    all_backups = sorted(BACKUP_DIR.glob("farmacia_????????.db"))
    for old in all_backups[:-BACKUP_KEEP]:
        try:
            old.unlink()
            print(f"[Backup] Removed old backup {old.name}")
        except Exception:
            pass

    return True


def start_background_sync(interval: int = 60) -> threading.Thread:
    """Daemon thread: daily backup + sync local → Turso every `interval` seconds."""
    def _loop():
        time.sleep(30)  # let app fully initialize first
        make_daily_backup()
        while True:
            try:
                sync_to_turso()
            except Exception as e:
                print(f"[Sync] Background sync error: {e}")
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="TursoSync")
    t.start()
    print(f"[Sync] Background sync started (every {interval}s)")
    return t
