"""
Sync service: local SQLite (primary) ↔ Turso (cloud backup).

- import_from_turso(): Turso → local on first run (local is empty)
- sync_to_turso(): local → Turso via batched HTTP pipeline calls
- sync_from_turso(): Turso → local merge (runs every startup + heartbeat)
- start_background_sync(interval): daemon thread for periodic sync
"""
import json
import shutil
import sqlite3
import threading
import time
import traceback
from datetime import datetime

import requests as _requests
import app.config as cfg

BACKUP_DIR     = cfg.DATA_DIR / "backups"
BACKUP_KEEP    = 7  # days of local backups to retain
_WATERMARK_FILE = cfg.DATA_DIR / "watermarks.json"

# FK-dependency order (import & sync must respect this)
_TABLE_ORDER = [
    "categorias", "proveedores", "usuarios", "clientes", "configuracion",
    "productos", "lotes", "ventas", "items_venta",
    "compras", "items_compra", "cortes_caja", "retiros_caja", "movimientos_stock", "auditoria_log",
]

# Mutable tables — always full-replace sync (rows can be updated in-place)
# ventas/compras: estado puede cambiar (completada→cancelada); watermark no capturaría eso
# items_venta incluido para que sync_from_turso los restaure si el DB local se resetea
_FULL_SYNC = frozenset({
    "categorias", "proveedores", "usuarios", "clientes", "configuracion",
    "productos", "lotes", "cortes_caja", "retiros_caja", "ventas", "compras", "items_venta",
})

# Tables that are shared across PCs — never delete rows from Turso by absence
# (each PC may have a subset; deletions happen via soft-delete / purge only)
_NO_TURSO_DELETE = frozenset({"productos", "lotes", "ventas", "items_venta",
                               "compras", "items_compra", "cortes_caja", "retiros_caja"})

# Watermark per table: last id synced to Turso (append-only tables only)
# Persisted to disk so restarts don't re-send the entire history.
def _load_watermarks() -> dict:
    try:
        if _WATERMARK_FILE.exists():
            return json.loads(_WATERMARK_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_watermarks() -> None:
    try:
        _WATERMARK_FILE.write_text(json.dumps(_watermarks), encoding="utf-8")
    except Exception as e:
        print(f"[Sync] Could not persist watermarks: {e}")

_watermarks: dict[str, int] = _load_watermarks()

# RLock: reentrant so sync_to_turso and sync_from_turso can share one lock
# without deadlocking when called sequentially from the same thread.
_lock  = threading.RLock()
_dirty = threading.Event()   # set after any local write → immediate sync


def mark_dirty() -> None:
    """Call after any local SQLite write to trigger immediate Turso sync."""
    _dirty.set()


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
        errors = [
            r.get("error", {}).get("message", "unknown")
            for r in resp.json().get("results", [])
            if r.get("type") == "error"
        ]
        if errors:
            # Log all errors but don't abort — partial sync is better than no sync
            for msg in errors:
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

# Reverse FK order for safe deletion (children before parents)
_PURGE_ORDER = [
    "auditoria_log", "movimientos_stock", "cortes_caja",
    "items_compra", "compras",
    "items_venta", "ventas",
    "lotes", "productos",
    "clientes", "proveedores", "categorias",
]


# Tables for partial purge: ventas + historial + cierres (keeps products/clients/etc.)
_PURGE_VENTAS = [
    "auditoria_log", "movimientos_stock", "cortes_caja",
    "items_venta", "ventas",
]


def _purge_tables(tables: list[str]) -> None:
    with _lock:  # Block background sync during purge to avoid re-sync race
        lconn = _local_conn()
        try:
            lconn.execute("PRAGMA foreign_keys = OFF")
            for table in tables:
                lconn.execute(f"DELETE FROM {table}")
            lconn.commit()
        finally:
            lconn.execute("PRAGMA foreign_keys = ON")
            lconn.close()

        # Reset watermarks for purged tables so they don't re-send deleted rows
        for t in tables:
            _watermarks.pop(t, None)
        _save_watermarks()

        stmts = [{"sql": f"DELETE FROM {t}", "args": []} for t in tables]
        try:
            _turso_batch(stmts)
        except Exception as e:
            print(f"[Purge] Turso error: {e}")


def eliminar_venta(venta_id: int) -> dict:
    """
    Soft-delete a single sale: restore stock, delete movements+items locally and
    in Turso, mark eliminado=1 in both. Safe even when the product no longer exists.
    Returns {"ok": True, "folio": "..."}.
    """
    from app.database.connection import get_db_session
    from app.database.models import Venta, ItemVenta, MovimientoStock, Producto
    from datetime import datetime as _dt

    db = get_db_session()
    try:
        venta = (db.query(Venta)
                 .filter(Venta.id == venta_id, Venta.eliminado.is_not(True))
                 .first())
        if not venta:
            raise ValueError(f"Venta {venta_id} no encontrada o ya eliminada")

        folio = venta.folio or str(venta_id)

        # 1. Restore stock via MovimientoStock records
        movements = (db.query(MovimientoStock)
                     .filter(MovimientoStock.referencia_id == venta_id,
                             MovimientoStock.referencia_tipo == "venta")
                     .all())
        restored = False
        for mov in movements:
            prod = db.query(Producto).filter(Producto.id == mov.producto_id).first()
            if prod and mov.cantidad and mov.cantidad > 0:
                prod.stock += mov.cantidad
                restored = True
            db.delete(mov)

        # 2. Fallback: restore from items when no movements exist
        if not restored:
            items = db.query(ItemVenta).filter(ItemVenta.venta_id == venta_id).all()
            for item in items:
                prod = db.query(Producto).filter(Producto.id == item.producto_id).first()
                if prod and item.cantidad and item.cantidad > 0:
                    prod.stock += item.cantidad

        # 3. Delete items locally
        db.query(ItemVenta).filter(ItemVenta.venta_id == venta_id).delete(
            synchronize_session="fetch"
        )

        # 4. Soft-delete the sale
        now_str = _dt.utcnow().isoformat()
        venta.eliminado = True
        venta.eliminado_en = _dt.utcnow()

        db.commit()

        # 5. Propagate to Turso immediately
        if cfg.TURSO_SYNC:
            stmts = [
                {
                    "sql": (
                        "DELETE FROM movimientos_stock "
                        "WHERE referencia_id = ? AND referencia_tipo = 'venta'"
                    ),
                    "args": [{"type": "integer", "value": str(venta_id)}],
                },
                {
                    "sql": "DELETE FROM items_venta WHERE venta_id = ?",
                    "args": [{"type": "integer", "value": str(venta_id)}],
                },
                {
                    "sql": "UPDATE ventas SET eliminado = 1, eliminado_en = ? WHERE id = ?",
                    "args": [
                        {"type": "text",    "value": now_str},
                        {"type": "integer", "value": str(venta_id)},
                    ],
                },
            ]
            try:
                _turso_batch(stmts)
            except Exception as e:
                print(f"[EliminarVenta] Turso error: {e}")
            mark_dirty()

        return {"ok": True, "folio": folio}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def purgar_ventas_historial_cierres() -> None:
    """Delete ventas, movimientos, auditoría and cortes de caja. Keeps products/clients."""
    _purge_tables(_PURGE_VENTAS)


def purgar_todos_los_datos() -> None:
    """Delete ALL business data (keeps usuarios + configuracion). Local + Turso."""
    _purge_tables(_PURGE_ORDER)


def factory_reset() -> None:
    """Delete EVERYTHING including usuarios and configuracion. Local + Turso."""
    all_tables = list(reversed(_TABLE_ORDER))
    _purge_tables(all_tables)


def import_from_turso() -> bool:
    """
    One-time import: copy all Turso data into local SQLite.
    Skips if local already has data (usuarios table is non-empty).
    Returns True if import ran.
    """
    lconn = _local_conn()
    try:
        # Check both usuarios AND productos: a seeded-but-empty-inventory DB should still import
        n_users = lconn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        n_prod  = lconn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    except Exception:
        n_users = n_prod = 0

    if n_users > 0 and n_prod > 0:
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
    FULL_SYNC tables: upsert all rows + delete from Turso any IDs missing in local.
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
                        stmts: list[dict] = []

                        if not rows:
                            # Skip — explicit purge functions handle clearing Turso.
                            # Never auto-delete cloud data just because local is empty.
                            continue
                        else:
                            cols    = list(rows[0].keys())
                            col_str = ", ".join(cols)
                            ph_str  = ", ".join(["?" for _ in cols])

                            # ventas: monotonic upsert — eliminado=1 can never go back to 0
                            if table == "ventas" and "eliminado" in cols:
                                set_parts = [
                                    "eliminado = MAX(excluded.eliminado, ventas.eliminado)"
                                    if c == "eliminado"
                                    else f"{c} = excluded.{c}"
                                    for c in cols if c != "id"
                                ]
                                upsert = (
                                    f"INSERT INTO ventas ({col_str}) VALUES ({ph_str}) "
                                    f"ON CONFLICT(id) DO UPDATE SET {', '.join(set_parts)}"
                                )
                            else:
                                upsert = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"

                            # Only delete orphaned rows for reference tables (categorias,
                            # usuarios, etc.). For distributed tables (productos, ventas,
                            # lotes…) NEVER delete by absence — another PC may have rows
                            # this PC hasn't pulled yet.
                            if table not in _NO_TURSO_DELETE:
                                ids_str = ", ".join(str(r["id"]) for r in rows)
                                stmts.append({
                                    "sql": f"DELETE FROM {table} WHERE id NOT IN ({ids_str})",
                                    "args": [],
                                })
                            for row in rows:
                                stmts.append({"sql": upsert,
                                              "args": [_py_to_turso(v) for v in tuple(row)]})
                            synced += len(rows)

                        _turso_batch(stmts)

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
                        sql     = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"
                        stmts   = [{"sql": sql, "args": [_py_to_turso(v) for v in tuple(row)]}
                                   for row in rows]
                        _turso_batch(stmts)
                        _watermarks[table] = max(row["id"] for row in rows)
                        synced += len(rows)

                except Exception as e:
                    print(f"[Sync] Warning — {table}: {e}")

            if synced:
                print(f"[Sync] >> Turso: {synced} rows synced")
                _save_watermarks()
        finally:
            lconn.close()


def sync_from_turso() -> int:
    """
    Pull all FULL_SYNC tables from Turso → local SQLite (INSERT OR REPLACE).
    Runs on every startup so that products added on other PCs appear locally.
    Returns total rows merged.
    """
    with _lock:
        lconn = _local_conn()
        try:
            lconn.execute("PRAGMA foreign_keys = OFF")
            total = 0
            for table in _TABLE_ORDER:
                if table not in _FULL_SYNC:
                    continue
                try:
                    cols, rows = _turso_read_table(table)
                    if not cols or not rows:
                        continue
                    col_str = ", ".join(cols)
                    ph_str  = ", ".join(["?" for _ in cols])
                    # For productos: UPSERT protecting imagen_url/descripcion from null overwrites.
                    # Use two-pass: INSERT OR IGNORE for new rows, then UPDATE existing ones.
                    if table == "productos" and "id" in cols:
                        # Pass 1: insert rows that don't exist yet (new products from other PCs)
                        sql_insert = f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({ph_str})"
                        lconn.executemany(sql_insert, rows)
                        # Pass 2: update existing rows — last-writer-wins by actualizado_en.
                        # stock/piezas_sueltas: ALWAYS keep local (never overwritten by pull).
                        # imagen_url/descripcion: keep local if Turso sends null.
                        # All other fields: take Turso value ONLY IF Turso's actualizado_en
                        #   is strictly newer than local — prevents pull from reverting a local
                        #   edit that was pushed to Turso but hasn't propagated yet in the
                        #   Turso read path (HTTP round-trip race).
                        _has_ts = "actualizado_en" in cols
                        set_clause = ", ".join(
                            f"{c}=COALESCE(excluded.{c}, {table}.{c})"
                            if c in ("imagen_url", "descripcion") else
                            f"{c}={table}.{c}"
                            if c in ("stock", "piezas_sueltas") else
                            (
                                f"{c}=CASE WHEN excluded.actualizado_en > {table}.actualizado_en"
                                f" THEN excluded.{c} ELSE {table}.{c} END"
                            ) if _has_ts else
                            f"{c}=excluded.{c}"
                            for c in cols if c != "id"
                        )
                        sql_update = (
                            f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql_update, rows)
                        # Diagnostic: show Turso stock vs local after UPSERT
                        if "stock" in cols:
                            id_idx  = cols.index("id")
                            stk_idx = cols.index("stock")
                            for row in rows:
                                turso_stock = row[stk_idx]
                                local_now = lconn.execute(
                                    f"SELECT stock FROM productos WHERE id=?", (row[id_idx],)
                                ).fetchone()
                                local_stock = local_now[0] if local_now else "?"
                                if str(turso_stock) != str(local_stock):
                                    print(f"[Sync] productos id={row[id_idx]}: Turso={turso_stock} → kept local={local_stock}")
                    elif table == "ventas" and "eliminado" in cols:
                        # Monotonic: eliminado=1 can never go back to 0
                        set_clause = ", ".join(
                            "eliminado = MAX(excluded.eliminado, ventas.eliminado)"
                            if c == "eliminado"
                            else f"{c} = excluded.{c}"
                            for c in cols if c != "id"
                        )
                        sql = (
                            f"INSERT INTO ventas ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql, rows)
                    else:
                        sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"
                        lconn.executemany(sql, rows)
                    total += len(rows)
                    print(f"[Sync] <- Turso {table}: {len(rows)} rows")
                except Exception as e:
                    print(f"[Sync] sync_from_turso warning — {table}: {e}")
            lconn.execute("PRAGMA foreign_keys = ON")
            lconn.commit()
            print(f"[Sync] Pull complete — {total} rows merged from Turso")
            return total
        except Exception as e:
            lconn.rollback()
            print(f"[Sync] sync_from_turso failed: {e}")
            traceback.print_exc()
            return 0
        finally:
            lconn.close()


def force_sync() -> dict:
    """Immediate bidirectional sync: push local → Turso, then pull Turso → local."""
    sync_to_turso()
    sync_from_turso()
    return get_db_stats()


def get_db_stats() -> dict:
    """Row counts per table from local SQLite."""
    lconn = _local_conn()
    try:
        stats = {}
        for table in _TABLE_ORDER:
            try:
                n = lconn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                stats[table] = n
            except Exception:
                stats[table] = -1
        return stats
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
    """Daemon thread: daily backup + bidirectional sync every cycle.

    On write (mark_dirty): push local → Turso immediately, then pull Turso → local.
    Heartbeat every `interval` seconds: pull Turso → local to pick up changes
    made on other PCs.
    """
    def _loop():
        time.sleep(10)   # let app fully initialize
        make_daily_backup()
        # Push local data first — preserves locally-set values (imagen_url, descripcion)
        # before pulling from Turso which may have older null values
        try:
            sync_to_turso()
        except Exception as e:
            print(f"[Sync] Initial push error: {e}")
        # Then pull to get changes from other PCs
        try:
            sync_from_turso()
        except Exception as e:
            print(f"[Sync] Initial pull error: {e}")

        while True:
            # Returns True if event fired (dirty write), False if timed out (heartbeat)
            woke_by_write = _dirty.wait(timeout=interval)
            _dirty.clear()
            try:
                sync_to_turso()
            except Exception as e:
                print(f"[Sync] Push error: {e}")
            # Pull ONLY on heartbeat (timeout), NOT on every write.
            # Pulling after a sale risks fetching Turso's pre-sale value (HTTP race)
            # before our push is visible in Turso. Local stock is authoritative.
            if not woke_by_write:
                try:
                    sync_from_turso()
                except Exception as e:
                    print(f"[Sync] Pull error: {e}")

    t = threading.Thread(target=_loop, daemon=True, name="TursoSync")
    t.start()
    print(f"[Sync] Background sync started (push on write + pull every {interval}s)")
    return t
