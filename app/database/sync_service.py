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
from app.database import ids_pc as _ids_pc

BACKUP_DIR     = cfg.DATA_DIR / "backups"
BACKUP_KEEP    = 7  # days of local backups to retain
_WATERMARK_FILE = cfg.DATA_DIR / "watermarks.json"

# FK-dependency order (import & sync must respect this)
# cfdi_facturas_globales va antes de ventas porque ventas.cfdi_global_id la referencia
# cfdi_facturas_individuales va después de ventas porque ella referencia venta_id
_TABLE_ORDER = [
    "categorias", "proveedores", "usuarios", "clientes", "configuracion",
    "productos", "lotes", "cfdi_facturas_globales", "ventas", "cfdi_facturas_individuales",
    "items_venta", "compras", "items_compra", "facturas_compra", "cortes_caja", "retiros_caja",
    "movimientos_stock", "auditoria_log", "pagos_sat",
    # Historial clínico, agenda, compras/inventario/gastos — antes vivían solo en la BD
    # local de cada PC, nunca sincronizaban (la tabla ni existía en Turso). Orden respeta
    # FKs: pacientes/promociones/pagos_credito/recetas no dependen de nada nuevo aquí;
    # registros_clinicos y citas dependen de pacientes; items_orden_compra depende de
    # ordenes_compra; conteos_inventario depende de sesiones_inventario.
    "pacientes", "promociones", "promociones_productos", "pagos_credito", "recetas", "registros_clinicos", "citas",
    "ordenes_compra", "items_orden_compra", "sesiones_inventario", "conteos_inventario",
    "gastos", "historial_precios",
]

# Mutable tables — always full-replace sync (rows can be updated in-place)
# ventas/compras: estado puede cambiar (completada→cancelada); watermark no capturaría eso
# items_venta incluido para que sync_from_turso los restaure si el DB local se resetea
_FULL_SYNC = frozenset({
    "categorias", "proveedores", "usuarios", "clientes", "configuracion",
    "productos", "lotes", "cortes_caja", "retiros_caja", "ventas", "compras", "items_venta",
    "cfdi_facturas_globales", "cfdi_facturas_individuales", "facturas_compra", "pagos_sat",
    "pacientes", "promociones", "promociones_productos", "pagos_credito", "recetas", "registros_clinicos", "citas",
    "ordenes_compra", "items_orden_compra", "sesiones_inventario", "conteos_inventario",
    "gastos", "historial_precios",
})

# Tables that are shared across PCs — never delete rows from Turso by absence
# (each PC may have a subset; deletions happen via soft-delete / purge only)
_NO_TURSO_DELETE = frozenset({"productos", "lotes", "ventas", "items_venta",
                               "compras", "items_compra", "cortes_caja", "retiros_caja",
                               "cfdi_facturas_globales", "cfdi_facturas_individuales", "facturas_compra",
                               "pacientes", "promociones", "promociones_productos", "pagos_credito", "recetas",
                               "registros_clinicos", "citas", "ordenes_compra", "items_orden_compra",
                               "sesiones_inventario", "conteos_inventario", "gastos", "historial_precios"})

# PUSH optimization for the tables that actually grow without bound (ventas history
# never shrinks). Before this, sync_to_turso() did `SELECT * FROM {table}` and
# re-upserted EVERY row on EVERY local write (mark_dirty fires per commit) — so
# each new sale re-pushed the entire sales history again (O(n^2) growth, this is
# what ran up the Turso row-read/write counters into the billions on a tiny DB).
#
# _TS_INCREMENTAL: rows mutate in place (stock, estado, facturada...), so push only
# rows with actualizado_en > last-pushed timestamp. Safe only for tables already in
# _NO_TURSO_DELETE (no delete-by-absence branch to break by seeing a partial set).
_TS_INCREMENTAL = frozenset({
    "productos", "ventas", "cfdi_facturas_globales", "cfdi_facturas_individuales",
})

# _PUSH_APPEND_ONLY: rows are immutable after insert (deletes are handled explicitly
# elsewhere — see eliminar_venta), so a plain id-watermark is enough, same as the
# non-full-sync tables. Still fully resynced on the PULL side (_FULL_SYNC) so a wiped
# local DB gets it all back.
_PUSH_APPEND_ONLY = frozenset({"items_venta"})

# Tablas de dinero editables (cerrar turno, editar retiro): last-writer-wins por
# actualizado_en en ambos sentidos. Antes era INSERT OR REPLACE ciego — una PC
# con copia vieja reabría turnos cerrados o revertía el tipo de un retiro.
_LWW_CAJA = frozenset({"cortes_caja", "retiros_caja"})


def _lww_upsert_sql(table: str, cols: list) -> str:
    """UPSERT que solo aplica la fila entrante si es más reciente. NULL-safe:
    filas anteriores a la columna actualizado_en cuentan como ''."""
    newer = (f"COALESCE(excluded.actualizado_en, '') > "
             f"COALESCE({table}.actualizado_en, '')")
    set_clause = ", ".join(
        f"{c} = CASE WHEN {newer} THEN excluded.{c} ELSE {table}.{c} END"
        for c in cols if c != "id"
    )
    return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(id) DO UPDATE SET {set_clause}")

# Watermark per table: last id synced to Turso (append-only tables), or last
# actualizado_en synced (ts-incremental tables). Persisted to disk so restarts
# don't re-send the entire history.
def _load_watermarks() -> tuple[dict, dict]:
    try:
        if _WATERMARK_FILE.exists():
            data = json.loads(_WATERMARK_FILE.read_text(encoding="utf-8"))
            if "ids" in data or "ts" in data:
                return data.get("ids", {}), data.get("ts", {})
            return data, {}  # legacy flat {table: id} format
    except Exception:
        pass
    return {}, {}

def _save_watermarks() -> None:
    try:
        _WATERMARK_FILE.write_text(
            json.dumps({"ids": _watermarks, "ts": _ts_watermarks}), encoding="utf-8"
        )
    except Exception as e:
        print(f"[Sync] Could not persist watermarks: {e}")

_watermarks: dict[str, int]
_ts_watermarks: dict[str, str]
_watermarks, _ts_watermarks = _load_watermarks()

# RLock: reentrant so sync_to_turso and sync_from_turso can share one lock
# without deadlocking when called sequentially from the same thread.
_lock  = threading.RLock()
_dirty = threading.Event()   # set after any local write → immediate sync

# Se marca cuando termina el primer ciclo push+pull al arrancar — el modal de
# carga en el frontend espera esta señal antes de dejar entrar al usuario.
initial_sync_done = threading.Event()

# Callbacks fired (in sync thread) after every successful sync_from_turso pull.
_post_sync_hooks: list = []


def register_post_sync(callback) -> None:
    """Register a callable invoked after each Turso pull completes."""
    _post_sync_hooks.append(callback)


def _fire_post_sync() -> None:
    for cb in _post_sync_hooks:
        try:
            cb()
        except Exception as e:
            print(f"[Sync] post-sync hook error: {e}")


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


def _turso_batch(stmts: list[dict]) -> int:
    """
    Send multiple SQL statements in one (or a few) HTTP pipeline call(s).
    stmts = [{"sql": "...", "args": [...]}, ...]
    """
    if not stmts:
        return 0
    n_errors = 0
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
            n_errors += len(errors)
    return n_errors


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
    "items_compra", "compras", "facturas_compra",
    "cfdi_facturas_individuales", "items_venta", "ventas", "cfdi_facturas_globales",
    "lotes", "productos",
    "clientes", "proveedores", "categorias",
]


# Tables for partial purge: ventas + historial + cierres (keeps products/clients/etc.)
_PURGE_VENTAS = [
    "auditoria_log", "movimientos_stock", "cortes_caja",
    "cfdi_facturas_individuales", "items_venta", "ventas",
]


def _purge_tables(tables: list[str]) -> None:
    with _lock:  # Block background sync during purge to avoid re-sync race
        lconn = _local_conn()
        try:
            lconn.execute("PRAGMA foreign_keys = OFF")
            for table in tables:
                lconn.execute(f"DELETE FROM {table}")
            if "productos" in tables:
                # Sin productos no hay stock acordado con la nube (ver sync_stock_base).
                lconn.execute(_BASE_DDL)
                lconn.execute("DELETE FROM sync_stock_base")
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


def eliminar_venta(venta_id: int, restaurar_stock: bool = True) -> dict:
    """
    Soft-delete a single sale: delete movements+items locally and in Turso,
    mark eliminado=1 in both. Safe even when the product no longer exists.
    Returns {"ok": True, "folio": "..."}.

    restaurar_stock=False: no le suma nada de vuelta al stock del producto —
    para limpiar ventas de prueba/mal capturadas cuyo inventario físico el
    usuario ya sabe que está correcto tal cual, y restaurar volvería a
    inflarlo con unidades que en realidad nunca salieron de verdad.
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

        # 1. Reponer stock desde items_venta — su cantidad YA está neta de
        # devoluciones parciales (antes se reponía desde los movimientos de la
        # venta original y una venta con devolución parcial se reponía dos
        # veces), y cada línea sabe si fue pieza o caja (antes las piezas
        # volvían como cajas completas).
        from app.api.routes.pos_routes import item_es_pieza, reponer_stock
        if restaurar_stock:
            for item in db.query(ItemVenta).filter(ItemVenta.venta_id == venta_id).all():
                prod = db.query(Producto).filter(Producto.id == item.producto_id).first()
                if prod and item.cantidad and item.cantidad > 0:
                    reponer_stock(prod, item.cantidad, item_es_pieza(item, prod))
        for mov in (db.query(MovimientoStock)
                    .filter(MovimientoStock.referencia_id == venta_id,
                            MovimientoStock.referencia_tipo == "venta")
                    .all()):
            db.delete(mov)

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
    with _lock:  # prevent race with background sync thread that starts concurrently
        lconn = _local_conn()
        try:
            # Check both usuarios AND productos
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


_sucursal_ok = False


def _sucursal_coincide() -> bool:
    """Seguro anti-cruce: esta PC solo sincroniza con la BD de SU sucursal.
    Si alguien cambia la URL de Turso a la de otra sucursal en una PC con
    datos, el push subiría las ventas/inventario de una sucursal a la otra.
    Compara configuracion.sucursal_clave de la nube con la de setup.json.
    Una BD de nube sin clave (la matriz antes de esta versión) se acepta y
    queda marcada con la clave local en el siguiente push."""
    global _sucursal_ok
    if _sucursal_ok:
        return True
    try:
        cols, rows = _turso_read_table("configuracion")
    except Exception:
        return False  # sin red: no sincronizar a ciegas
    if not cols:
        return False  # no se pudo leer (sin red / error): reintentar en el próximo ciclo
    if "clave" in cols and "valor" in cols:
        ci, vi = cols.index("clave"), cols.index("valor")
        nube = next((r[vi] for r in rows if r[ci] == "sucursal_clave"), None)
        if nube and str(nube).strip().lower() != cfg.SUCURSAL_CLAVE:
            print(f"[Sync] BLOQUEADO: esta PC es de la sucursal '{cfg.SUCURSAL_CLAVE}' pero la "
                  f"BD de la nube es de '{nube}'. Revisa la URL de Turso en Configuración.")
            return False
    _sucursal_ok = True
    return True


def sync_to_turso(only_incremental: bool = False) -> None:
    """
    Push local SQLite data to Turso via batched HTTP pipeline.
    TS_INCREMENTAL tables (productos, ventas, cfdi_*): only rows changed since the
    last actualizado_en watermark — these grow forever, a full resend on every
    write would be O(n^2) over the table's lifetime.
    PUSH_APPEND_ONLY (items_venta) + other non-full tables: only rows with
    id > last watermark.
    Remaining FULL_SYNC tables (small/reference-ish): upsert all rows + delete
    from Turso any IDs missing in local.

    only_incremental=True skips the FULL_SYNC branch entirely (no `SELECT *`
    over tables like lotes/cortes_caja/compras/citas/gastos/historial_precios).
    Used for the "push right after a write" call so that cobrar una venta no
    tenga que releer y resubir tablas enteras que no cambiaron — esas tablas
    igual se sincronizan completas en cada latido (ver start_background_sync).
    """
    if not _sucursal_coincide():
        return
    with _lock:
        lconn = _local_conn()
        try:
            synced = 0
            try:
                _push_tombstones(lconn)
            except Exception as e:
                print(f"[Sync] sync_borrados push warning: {e}")
            for table in _TABLE_ORDER:
                try:
                    if table == "productos":
                        # Stock por deltas + LWW en lo demás (ver _push_productos).
                        synced += _push_productos(lconn)

                    elif table in _TS_INCREMENTAL:
                        last_ts = _ts_watermarks.get(table, "")
                        rows = lconn.execute(
                            f"SELECT * FROM {table} WHERE actualizado_en > ? ORDER BY actualizado_en",
                            (last_ts,),
                        ).fetchall()

                        if not rows:
                            continue

                        cols    = list(rows[0].keys())
                        col_str = ", ".join(cols)
                        ph_str  = ", ".join(["?" for _ in cols])
                        ts_idx  = cols.index("actualizado_en")

                        if table == "ventas":
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
                        elif table in ("cfdi_facturas_globales", "cfdi_facturas_individuales"):
                            set_parts = [
                                f"{c} = CASE WHEN excluded.actualizado_en > {table}.actualizado_en "
                                f"THEN excluded.{c} ELSE {table}.{c} END"
                                for c in cols if c != "id"
                            ]
                            upsert = (
                                f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                                f"ON CONFLICT(id) DO UPDATE SET {', '.join(set_parts)}"
                            )
                        else:  # (productos tiene su propia rama arriba)
                            upsert = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"

                        stmts = [{"sql": upsert, "args": [_py_to_turso(v) for v in tuple(row)]}
                                  for row in rows]
                        _turso_batch(stmts)
                        # Tope en el reloj local — ver el comentario en _push_productos.
                        _ts_watermarks[table] = max(last_ts, min(max(row[ts_idx] for row in rows), _ahora_ts()))
                        synced += len(rows)

                    elif table in _FULL_SYNC and table not in _PUSH_APPEND_ONLY:
                        if only_incremental:
                            continue
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
                            # cfdi_facturas_globales/individuales: last-writer-wins por
                            # actualizado_en — sin esto, una PC con copia vieja (ej. antes
                            # de que otra PC cancelara el CFDI) puede "resucitar" un estado
                            # ya superado con cada push periódico.
                            elif table in ("cfdi_facturas_globales", "cfdi_facturas_individuales", "pagos_sat") and "actualizado_en" in cols:
                                set_parts = [
                                    f"{c} = CASE WHEN excluded.actualizado_en > {table}.actualizado_en "
                                    f"THEN excluded.{c} ELSE {table}.{c} END"
                                    for c in cols if c != "id"
                                ]
                                upsert = (
                                    f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                                    f"ON CONFLICT(id) DO UPDATE SET {', '.join(set_parts)}"
                                )
                            elif table in _LWW_CAJA and "actualizado_en" in cols:
                                upsert = _lww_upsert_sql(table, cols)
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
                            borrados = _tombstones(lconn, table) if table in _NO_TURSO_DELETE else set()
                            if borrados:
                                rows = [r for r in rows if r["id"] not in borrados]
                                ids_b = ", ".join(str(i) for i in sorted(borrados))
                                stmts.append({"sql": f"DELETE FROM {table} WHERE id IN ({ids_b})",
                                              "args": []})
                            for row in rows:
                                stmts.append({"sql": upsert,
                                              "args": [_py_to_turso(v) for v in tuple(row)]})
                            synced += len(rows)

                        _turso_batch(stmts)

                    else:
                        # Dos rangos (ver ids_pc.py): ids viejos (< ID_BLOQUE) con el
                        # watermark de siempre, e ids del bloque de ESTA PC con el suyo.
                        # Nunca un watermark global: tras jalar items_venta de otra PC
                        # (ids de su bloque) el watermark saltaba por encima del bloque
                        # propio y las ventas nuevas de esta PC ya no se subían.
                        base = _ids_pc.base_pc()
                        key_pc = f"{table}@pc"
                        last_id = _watermarks.get(table, 0)
                        last_pc = max(_watermarks.get(key_pc, base), base)
                        rows = lconn.execute(
                            f"SELECT * FROM {table} WHERE (id > ? AND id < ?) "
                            f"OR (id > ? AND id < ?) ORDER BY id",
                            (last_id, _ids_pc.ID_BLOQUE, last_pc, base + _ids_pc.ID_BLOQUE),
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
                        viejos = [row["id"] for row in rows if row["id"] < _ids_pc.ID_BLOQUE]
                        propios = [row["id"] for row in rows if row["id"] >= _ids_pc.ID_BLOQUE]
                        if viejos:
                            _watermarks[table] = max(viejos)
                        if propios:
                            _watermarks[key_pc] = max(propios)
                        synced += len(rows)

                except Exception as e:
                    print(f"[Sync] Warning — {table}: {e}")

            if synced:
                print(f"[Sync] >> Turso: {synced} rows synced")
                _save_watermarks()
        finally:
            lconn.close()


def upsert_ids_to_turso(table: str, ids: list[int]) -> None:
    """
    Explicit, immediate upsert of specific row ids to Turso.
    For tables in _PUSH_APPEND_ONLY (id-watermark push, "rows are immutable
    after insert"): if a row is mutated AFTER its id already crossed the
    watermark, the periodic sync_to_turso() will never see it again — it only
    looks at id > last_watermark. Used e.g. by registrar_devolucion (partial
    return), which adjusts an existing items_venta row's cantidad/subtotal
    long after that row was created/synced — without this, Turso keeps the
    stale pre-return quantity forever.
    """
    if not ids:
        return
    with _lock:
        lconn = _local_conn()
        try:
            ids_str = ", ".join(str(int(i)) for i in ids)
            rows = lconn.execute(f"SELECT * FROM {table} WHERE id IN ({ids_str})").fetchall()
        finally:
            lconn.close()
        if not rows:
            return
        cols    = list(rows[0].keys())
        col_str = ", ".join(cols)
        ph_str  = ", ".join(["?" for _ in cols])
        sql     = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"
        stmts   = [{"sql": sql, "args": [_py_to_turso(v) for v in tuple(row)]} for row in rows]
        _turso_batch(stmts)


_COSTOS_TURSO_MARK = cfg.DATA_DIR / "costos_items_venta_turso_v3.done"


def reparar_costos_turso() -> None:
    """
    Una sola vez por PC: re-sube a Turso el costo_unitario de TODOS los
    items_venta locales que ya lo tienen. El push normal de items_venta es
    append-only por id, así que las filas que ya estaban en Turso antes de
    congelar el costo se quedaron allá con 0 para siempre — y cada pull las
    regresaba en 0 a todas las PCs. Solo actualiza la columna de costo (nunca
    cantidad/subtotal). Solo marca como hecho si Turso no reportó errores.
    """
    if _COSTOS_TURSO_MARK.exists():
        return
    with _lock:
        lconn = _local_conn()
        try:
            rows = lconn.execute(
                "SELECT id, costo_unitario FROM items_venta WHERE COALESCE(costo_unitario, 0) <> 0"
            ).fetchall()
        finally:
            lconn.close()
        # Sube el costo local aunque Turso tenga otro distinto de 0: la migración
        # v2 también corrige líneas de pieza que traían el costo de la caja entera.
        sql = ("UPDATE items_venta SET costo_unitario = ? "
               "WHERE id = ? AND COALESCE(costo_unitario, 0) <> ?")
        errores = _turso_batch([
            {"sql": sql, "args": [_py_to_turso(float(r["costo_unitario"])), _py_to_turso(r["id"]),
                                  _py_to_turso(float(r["costo_unitario"]))]}
            for r in rows
        ])
    if errores:
        print(f"[Sync] reparar_costos_turso: {errores} errores — se reintenta en el próximo arranque")
        return
    _COSTOS_TURSO_MARK.write_text("1", encoding="utf-8")
    print(f"[Sync] reparar_costos_turso: {len(rows)} costos de items_venta subidos a Turso")


# ── Borrados que viajan entre PCs ────────────────────────────────────────────
# Las tablas de _NO_TURSO_DELETE nunca se borran "por ausencia", así que un
# borrado hecho en una PC no llegaba a las demás: la otra PC seguía teniendo la
# fila y la volvía a subir en su push completo → el retiro/gasto borrado
# "resucitaba". Cada borrado se anota en sync_borrados (local y en Turso, solo
# se agregan filas, nunca se quitan); el push nunca sube esos ids y el pull
# los elimina localmente.
_TOMB_DDL = ("CREATE TABLE IF NOT EXISTS sync_borrados ("
             "tabla TEXT NOT NULL, id INTEGER NOT NULL, PRIMARY KEY (tabla, id))")
_TOMB_INSERT = "INSERT OR IGNORE INTO sync_borrados (tabla, id) VALUES (?, ?)"


def _tombstones(lconn, table: str) -> set:
    lconn.execute(_TOMB_DDL)
    return {r[0] for r in lconn.execute("SELECT id FROM sync_borrados WHERE tabla = ?", (table,))}


def _push_tombstones(lconn) -> None:
    lconn.execute(_TOMB_DDL)
    rows = lconn.execute("SELECT tabla, id FROM sync_borrados").fetchall()
    _turso_batch([{"sql": _TOMB_DDL, "args": []}] + [
        {"sql": _TOMB_INSERT, "args": [_py_to_turso(t), _py_to_turso(i)]} for t, i in rows
    ])


def _pull_tombstones(lconn) -> None:
    lconn.execute(_TOMB_DDL)
    cols, rows = _turso_read_table("sync_borrados")
    if cols and rows:
        lconn.executemany(_TOMB_INSERT, [tuple(r) for r in rows])


# ── Stock de productos: merge por DELTAS, no last-writer-wins ────────────────
# Antes el stock viajaba como valor absoluto dentro de la fila de productos, con
# last-writer-wins por actualizado_en. Eso perdía ventas ("hay veces que no se
# descuenta"):
#   - PC A vende 1 (10→9) y PC B vende 2 (10→8) antes de sincronizar: gana la
#     última en subir y la nube queda en 8 en vez de 7.
#   - PC A vende 4 (10→6); PC B, con copia vieja (10), edita el precio: su fila
#     es "más nueva" y sube stock=10 → la venta de A desaparece en todas las PCs.
#   - Reloj de otra PC (o de la app web en UTC) adelantado: la fila de la nube
#     queda "en el futuro" y cada pull pisaba el stock recién vendido aquí.
# Ahora cada PC guarda en sync_stock_base el último stock que acordó con la nube
# (al subir o al bajar). Al subir manda solo la diferencia (local - base) como
# "stock = stock + delta"; al bajar aplica local = nube + (local - base). Así las
# ventas/compras de varias PCs se suman, sin importar timestamps ni relojes.
_BASE_DDL = ("CREATE TABLE IF NOT EXISTS sync_stock_base ("
             "producto_id INTEGER PRIMARY KEY, stock INTEGER, piezas INTEGER)")
_BASE_UPSERT = "INSERT OR REPLACE INTO sync_stock_base (producto_id, stock, piezas) VALUES (?, ?, ?)"
_STOCK_COLS = ("stock", "piezas_sueltas")


def _ts_sql(expr: str) -> str:
    """Timestamp comparable como texto: NULL → '' y 'T' (ISO) → ' ' (formato de
    SQLAlchemy). Sin esto, '2026-10-04T10:00' > '2026-10-04 23:00' (la 'T' pesa
    más que el espacio) y una fila con formato ISO siempre parecía más nueva."""
    return f"REPLACE(COALESCE({expr}, ''), 'T', ' ')"


def _ahora_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _push_productos(lconn) -> int:
    """Sube productos: columnas normales con last-writer-wins por actualizado_en,
    y el stock como delta contra sync_stock_base (ver arriba)."""
    lconn.execute(_BASE_DDL)
    last_ts = _ts_watermarks.get("productos", "")
    # Además de lo editado desde el último push (watermark), sube todo producto
    # cuyo stock difiere de su base — así una venta nunca se queda sin subir
    # aunque su actualizado_en quede detrás del watermark (reloj desfasado).
    rows = lconn.execute(
        "SELECT p.*, b.producto_id AS _b_id, b.stock AS _b_stock, b.piezas AS _b_piezas "
        "FROM productos p LEFT JOIN sync_stock_base b ON b.producto_id = p.id "
        "WHERE p.actualizado_en > ? OR (b.producto_id IS NOT NULL AND "
        "(COALESCE(p.stock, 0) <> COALESCE(b.stock, 0) "
        " OR COALESCE(p.piezas_sueltas, 0) <> COALESCE(b.piezas, 0))) "
        "ORDER BY p.actualizado_en",
        (last_ts,),
    ).fetchall()
    if not rows:
        return 0

    cols = [c for c in rows[0].keys() if not c.startswith("_b_")]
    col_str = ", ".join(cols)
    ph_str = ", ".join("?" for _ in cols)
    newer = f"{_ts_sql('excluded.actualizado_en')} > {_ts_sql('productos.actualizado_en')}"

    def _upsert(lww_stock: bool) -> str:
        sets = []
        for c in cols:
            if c == "id":
                continue
            if c in _STOCK_COLS and not lww_stock:
                continue  # el stock lo mueve el UPDATE por delta de abajo
            sets.append(f"{c} = CASE WHEN {newer} THEN excluded.{c} ELSE productos.{c} END")
        return (f"INSERT INTO productos ({col_str}) VALUES ({ph_str}) "
                f"ON CONFLICT(id) DO UPDATE SET {', '.join(sets)}")

    sql_con_base = _upsert(lww_stock=False)
    # Sin base (primera sincronización tras actualizar, o producto nuevo): el
    # stock viaja como antes, pero con last-writer-wins en vez de pisar a ciegas.
    sql_sin_base = _upsert(lww_stock=True)
    sql_delta = ("UPDATE productos SET stock = MAX(0, COALESCE(stock, 0) + ?), "
                 "piezas_sueltas = MAX(0, COALESCE(piezas_sueltas, 0) + ?) WHERE id = ?")

    synced = 0
    CHUNK = 90  # ≤ 2 sentencias por producto → cabe en un solo request de _turso_batch
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        stmts, bases = [], []
        for r in chunk:
            stock, piezas = r["stock"] or 0, r["piezas_sueltas"] or 0
            vals = [r[c] for c in cols]
            if r["_b_id"] is not None:
                b_stock, b_piezas = r["_b_stock"] or 0, r["_b_piezas"] or 0
                # Si la fila no existe en la nube se inserta con la base y el
                # delta la lleva al valor local; si existe, solo se suma el delta.
                vals[cols.index("stock")] = b_stock
                if "piezas_sueltas" in cols:
                    vals[cols.index("piezas_sueltas")] = b_piezas
                stmts.append({"sql": sql_con_base, "args": [_py_to_turso(v) for v in vals]})
                d_stock, d_piezas = stock - b_stock, piezas - b_piezas
                if d_stock or d_piezas:
                    stmts.append({"sql": sql_delta, "args": [
                        _py_to_turso(d_stock), _py_to_turso(d_piezas), _py_to_turso(r["id"])]})
            else:
                stmts.append({"sql": sql_sin_base, "args": [_py_to_turso(v) for v in vals]})
            bases.append((r["id"], stock, piezas))
        _turso_batch(stmts)  # si falla la red lanza excepción → la base no avanza y se reintenta
        # La base es el valor LEÍDO y ya subido (no el actual): si una venta entró
        # mientras tanto, su delta sale en el siguiente push.
        lconn.executemany(_BASE_UPSERT, bases)
        lconn.commit()
        synced += len(chunk)

    ts_vals = [r["actualizado_en"] for r in rows if r["actualizado_en"]]
    if ts_vals:
        # Nunca adelantar el watermark más allá del reloj local: una fila jalada de
        # una PC con reloj adelantado lo dejaba "en el futuro" y las ediciones de
        # esta PC dejaban de subirse hasta que el reloj la alcanzara.
        _ts_watermarks["productos"] = max(last_ts, min(max(ts_vals), _ahora_ts()))
    return synced


def _merge_stock_pull(lconn, cols: list, rows: list) -> None:
    """Pull de stock: local = nube + (local - base) para productos con base; luego
    la base pasa a ser el valor de la nube. Corre dentro de la transacción del pull
    (ya con el lock de escritura de SQLite), así que ninguna venta se cuela a medias."""
    if "id" not in cols or "stock" not in cols:
        return
    id_i, st_i = cols.index("id"), cols.index("stock")
    pz_i = cols.index("piezas_sueltas") if "piezas_sueltas" in cols else None
    nube = [(r[id_i], r[st_i] or 0, (r[pz_i] or 0) if pz_i is not None else 0) for r in rows]
    base_sub = "(SELECT COALESCE({c}, 0) FROM sync_stock_base WHERE producto_id = productos.id)"
    lconn.executemany(
        "UPDATE productos SET "
        f"stock = MAX(0, ? + COALESCE(stock, 0) - {base_sub.format(c='stock')}), "
        f"piezas_sueltas = MAX(0, ? + COALESCE(piezas_sueltas, 0) - {base_sub.format(c='piezas')}) "
        "WHERE id = ? AND EXISTS (SELECT 1 FROM sync_stock_base WHERE producto_id = productos.id)",
        [(s, p, i) for i, s, p in nube],
    )
    lconn.executemany(_BASE_UPSERT, nube)


def delete_ids_from_turso(table: str, ids: list[int]) -> None:
    """
    Explicit, immediate delete of specific row ids in Turso.
    Used for admin-initiated deletes (e.g. purging an errored CFDI attempt) on
    tables listed in _NO_TURSO_DELETE, where the periodic full-sync deliberately
    never deletes by absence (since another PC's local DB may still have rows
    this PC hasn't pulled yet). Here the ids are explicitly known-bad and the
    delete is intentional, not inferred from a diff — safe to push directly.
    """
    if not ids:
        return
    with _lock:
        if table in _NO_TURSO_DELETE:
            lconn = _local_conn()
            try:
                lconn.execute(_TOMB_DDL)
                lconn.executemany(_TOMB_INSERT, [(table, int(i)) for i in ids])
                lconn.commit()
            finally:
                lconn.close()
            _turso_batch([{"sql": _TOMB_DDL, "args": []}] +
                         [{"sql": _TOMB_INSERT, "args": [_py_to_turso(table), _py_to_turso(int(i))]}
                          for i in ids])
        ids_str = ", ".join(str(int(i)) for i in ids)
        _turso_batch([{"sql": f"DELETE FROM {table} WHERE id IN ({ids_str})", "args": []}])


def sync_from_turso() -> int:
    """
    Pull all FULL_SYNC tables from Turso → local SQLite (INSERT OR REPLACE).
    Runs on every startup so that products added on other PCs appear locally.
    Returns total rows merged.
    """
    if not _sucursal_coincide():
        return 0
    with _lock:
        lconn = _local_conn()
        try:
            lconn.execute("PRAGMA foreign_keys = OFF")
            total = 0
            try:
                _pull_tombstones(lconn)
            except Exception as e:
                print(f"[Sync] sync_borrados pull warning: {e}")
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
                        # Pass 2: update existing rows — last-writer-wins by actualizado_en
                        # (comparado con _ts_sql: NULL/'T' normalizados).
                        # stock/piezas_sueltas NO van por LWW cuando el producto ya tiene
                        # base en sync_stock_base: se combinan por delta en
                        # _merge_stock_pull (antes un pull con fila "más nueva" de otra PC
                        # pisaba la venta que se acababa de hacer aquí).
                        # imagen_url/descripcion: keep local if Turso sends null.
                        lconn.execute(_BASE_DDL)
                        _has_ts = "actualizado_en" in cols
                        _newer = (f"{_ts_sql('excluded.actualizado_en')} > "
                                  f"{_ts_sql(table + '.actualizado_en')}")
                        _lww = "{c}=CASE WHEN " + _newer + " THEN excluded.{c} ELSE " + table + ".{c} END"
                        _con_base = ("EXISTS (SELECT 1 FROM sync_stock_base "
                                     "WHERE producto_id = " + table + ".id)")
                        set_clause = ", ".join(
                            (
                                f"{c}=CASE WHEN {_con_base} THEN {table}.{c}"
                                f" WHEN {_newer} THEN excluded.{c} ELSE {table}.{c} END"
                            ) if _has_ts and c in _STOCK_COLS else
                            _lww.format(c=c) if _has_ts else
                            f"{c}=COALESCE(excluded.{c}, {table}.{c})"
                            if c in ("imagen_url", "descripcion") else
                            f"{c}=excluded.{c}"
                            for c in cols if c != "id"
                        )
                        sql_update = (
                            f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql_update, rows)
                        # Stock: local = nube + (pendiente local); la base pasa a la nube.
                        _merge_stock_pull(lconn, cols, rows)
                    elif table == "ventas" and "eliminado" in cols:
                        # eliminado: monotonic, nunca retrocede de 1 a 0.
                        # facturada/cfdi_global_id (y demás campos mutables): last-writer-wins
                        # por actualizado_en, igual que productos — sin esto, un pull podía
                        # pisar con una copia vieja de Turso el "facturada=True" que se acaba
                        # de poner localmente al timbrar un CFDI (bug real detectado en producción:
                        # ventas quedaban desvinculadas de su factura tras un pull).
                        _has_ts = "actualizado_en" in cols
                        set_clause = ", ".join(
                            "eliminado = MAX(excluded.eliminado, ventas.eliminado)"
                            if c == "eliminado"
                            else (
                                f"{c}=CASE WHEN excluded.actualizado_en > ventas.actualizado_en"
                                f" THEN excluded.{c} ELSE ventas.{c} END"
                            ) if _has_ts and c != "actualizado_en"
                            else (
                                # Nunca bajar el timestamp local: una venta editada aquí
                                # (devolución) que aún no se subía quedaba bajo el
                                # watermark y jamás llegaba a la otra PC.
                                "actualizado_en = MAX(COALESCE(excluded.actualizado_en, ''),"
                                " COALESCE(ventas.actualizado_en, ''))"
                            ) if c == "actualizado_en"
                            else f"{c} = excluded.{c}"
                            for c in cols if c != "id"
                        )
                        sql = (
                            f"INSERT INTO ventas ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql, rows)
                    elif table in ("cfdi_facturas_globales", "cfdi_facturas_individuales", "pagos_sat") and "actualizado_en" in cols:
                        # Mismo criterio last-writer-wins que ventas/productos — evita que
                        # un pull resucite un estado ("timbrada") ya cancelado localmente.
                        set_clause = ", ".join(
                            f"{c}=CASE WHEN excluded.actualizado_en > {table}.actualizado_en"
                            f" THEN excluded.{c} ELSE {table}.{c} END"
                            for c in cols if c != "id"
                        )
                        sql = (
                            f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql, rows)
                    elif table == "configuracion" and "actualizado_en" in cols:
                        # Mismo criterio last-writer-wins — sin esto, un pull podía pisar con
                        # una copia vieja de Turso credenciales (Factura.com, etc.) recién
                        # guardadas localmente (bug real: la llave de Factura.com quedaba
                        # revertida a un valor viejo cada vez que la app sincronizaba).
                        # Conflicto por "clave" (única), no "id" — el id puede diferir entre
                        # el registro local y el de Turso para la misma configuración.
                        set_clause = ", ".join(
                            f"{c}=CASE WHEN excluded.actualizado_en > configuracion.actualizado_en"
                            f" THEN excluded.{c} ELSE configuracion.{c} END"
                            for c in cols if c not in ("id", "clave")
                        )
                        sql = (
                            f"INSERT INTO {table} ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(clave) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql, rows)
                    elif table == "items_venta" and "costo_unitario" in cols:
                        # items_venta se sube por watermark de id (append-only), así que
                        # Turso conserva costo_unitario=0 en las filas subidas ANTES de
                        # que existiera esa columna. Con INSERT OR REPLACE, cada pull
                        # pisaba el costo congelado local con ese 0 → la ganancia y el
                        # capital de inversión del Control de Caja "brincaban" solos
                        # (se notaba al editar inventario, que dispara la sincronización).
                        # Un costo local ya congelado nunca se reemplaza por el de Turso.
                        # Igual con cantidad/subtotal/descuento: solo BAJAN (devoluciones
                        # parciales), así que una copia vieja de Turso no puede regresar
                        # la cantidad previa a una devolución local aún no subida.
                        def _col_items(c):
                            if c == "costo_unitario":
                                return ("costo_unitario = CASE WHEN COALESCE(items_venta.costo_unitario, 0) <> 0"
                                        " THEN items_venta.costo_unitario ELSE excluded.costo_unitario END")
                            if c in ("cantidad", "subtotal", "descuento"):
                                return f"{c} = MIN(excluded.{c}, items_venta.{c})"
                            return f"{c} = excluded.{c}"
                        set_clause = ", ".join(_col_items(c) for c in cols if c != "id")
                        sql = (
                            f"INSERT INTO items_venta ({col_str}) VALUES ({ph_str}) "
                            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
                        )
                        lconn.executemany(sql, rows)
                    elif table in _LWW_CAJA and "actualizado_en" in cols:
                        lconn.executemany(_lww_upsert_sql(table, cols), rows)
                    else:
                        sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({ph_str})"
                        lconn.executemany(sql, rows)
                    total += len(rows)
                    print(f"[Sync] <- Turso {table}: {len(rows)} rows")
                except Exception as e:
                    print(f"[Sync] sync_from_turso warning — {table}: {e}")
            # Quitar localmente las filas borradas en cualquier PC (ver sync_borrados).
            for table in _NO_TURSO_DELETE:
                borrados = _tombstones(lconn, table)
                if borrados:
                    ids_b = ", ".join(str(i) for i in sorted(borrados))
                    lconn.execute(f"DELETE FROM {table} WHERE id IN ({ids_b})")
            lconn.execute("PRAGMA foreign_keys = ON")
            lconn.commit()
            print(f"[Sync] Pull complete — {total} rows merged from Turso")
            _fire_post_sync()
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
    push_err = pull_err = None
    try:
        sync_to_turso()
    except Exception as e:
        push_err = str(e)
        print(f"[Sync] force_sync push error: {e}")
    try:
        sync_from_turso()
    except Exception as e:
        pull_err = str(e)
        print(f"[Sync] force_sync pull error: {e}")
    stats = get_db_stats()
    if push_err or pull_err:
        stats["_error"] = (push_err or "") + (" | " + pull_err if pull_err else "")
    return stats


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


_img_cache_running = threading.Event()

# Estado consultado por /admin/image-sync-status para mostrar el spinner de
# "sincronizando fotos" en el header (solo admin, ver app/web/index.html) —
# así se ve si está bajando fotos ahora mismo, cuántas van, y cuándo terminó
# la última pasada, en vez de que la descarga en segundo plano sea invisible.
_image_sync_state_lock = threading.Lock()
_image_sync_state = {
    "running": False,
    "done": 0,
    "total": 0,
    "last_downloaded": 0,
    "last_run_at": None,
}


def get_image_sync_state() -> dict:
    with _image_sync_state_lock:
        return dict(_image_sync_state)


def _sync_product_images_bg() -> None:
    """Descarga en un hilo aparte (nunca bloquea el latido de sync) las fotos de
    producto que están en Cloudinary pero de las que este equipo todavía no
    tiene copia local — ver cloudinary_service.sync_product_images_locally.
    _img_cache_running evita que se disparen varias pasadas encimadas si el
    heartbeat vuelve a cumplirse mientras la anterior sigue bajando fotos."""
    if _img_cache_running.is_set():
        return
    _img_cache_running.set()
    with _image_sync_state_lock:
        _image_sync_state.update(running=True, done=0, total=0)
    try:
        from app.services.cloudinary_service import sync_product_images_locally

        def _progress(done, total):
            with _image_sync_state_lock:
                _image_sync_state.update(done=done, total=total)

        n = sync_product_images_locally(progress_cb=_progress)
        if n:
            print(f"[Sync] {n} imagen(es) de producto descargadas para respaldo local")
        with _image_sync_state_lock:
            _image_sync_state["last_downloaded"] = n
            _image_sync_state["last_run_at"] = datetime.now().isoformat()
    except Exception as e:
        print(f"[Sync] Error cacheando imágenes de producto: {e}")
    finally:
        _img_cache_running.clear()
        with _image_sync_state_lock:
            _image_sync_state["running"] = False


def sync_now() -> None:
    """Fuerza un pull de Turso + descarga de imágenes pendientes de inmediato,
    sin esperar al latido — usado por el botón "Actualizar ahora" del admin
    (ver /admin/sync-now) para no depender de los ~180s del heartbeat."""
    def _run():
        try:
            sync_from_turso()
        except Exception as e:
            print(f"[Sync] sync_now pull error: {e}")
        _sync_product_images_bg()

    threading.Thread(target=_run, daemon=True, name="ManualSync").start()


# Watermark propio (no confundir con el de _TS_INCREMENTAL, que es para el PUSH
# local→Turso) para el chequeo rápido de fotos nuevas: solo lee filas de
# productos cuyo actualizado_en avanzó desde la última vez, en vez de releer
# la tabla completa como hace sync_from_turso(). Así se puede correr cada
# pocos segundos sin multiplicar el costo de lecturas en Turso.
_IMG_WATERMARK_KEY = "_productos_imagen_pull"


def _check_new_product_images() -> int:
    """Pull barato: solo productos cuyo actualizado_en avanzó desde la última
    pasada (por eso puede correr cada ~12s sin pesar en Turso, a diferencia
    del latido de 180s que relee tablas completas). Detecta fotos subidas en
    otras PCs, actualiza imagen_url en la BD local y dispara la descarga de
    esa foto al instante. Devuelve cuántos productos cambiaron."""
    if not (cfg.TURSO_DATABASE_URL and cfg.TURSO_AUTH_TOKEN):
        return 0
    last = _ts_watermarks.get(_IMG_WATERMARK_KEY, "1970-01-01 00:00:00")
    try:
        from app.database.turso_http import connect as turso_connect
        tconn = turso_connect(cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN)
        cur = tconn.cursor()
        cur.execute(
            "SELECT id, imagen_url, actualizado_en FROM productos "
            "WHERE actualizado_en > ? ORDER BY actualizado_en",
            (last,),
        )
        rows = cur.fetchall()
    except Exception as e:
        print(f"[Sync] Chequeo rápido de fotos falló (se reintenta en el próximo ciclo): {e}")
        return 0
    if not rows:
        return 0

    with _lock:
        lconn = _local_conn()
        try:
            for pid, url, ts in rows:
                # Mismo criterio last-writer-wins que sync_from_turso: solo pisa
                # imagen_url local si el cambio de Turso es más nuevo — así una
                # edición hecha en ESTA pc (todavía sin llegar a Turso) no se
                # pierde si el pull corre justo en medio.
                lconn.execute(
                    "UPDATE productos SET imagen_url = ?, actualizado_en = ? "
                    "WHERE id = ? AND (actualizado_en IS NULL OR actualizado_en < ?)",
                    (url, ts, pid, ts),
                )
            lconn.commit()
        finally:
            lconn.close()

    _ts_watermarks[_IMG_WATERMARK_KEY] = rows[-1][2]
    _save_watermarks()
    threading.Thread(target=_sync_product_images_bg, daemon=True, name="ImgCache").start()
    return len(rows)


def start_image_watch(interval: int = 12) -> threading.Thread:
    """Hilo aparte del latido principal (start_background_sync) — solo vigila
    fotos de producto nuevas/cambiadas en Turso cada `interval` segundos, con
    una consulta barata (ver _check_new_product_images). Así "se ve la foto en
    las demás PCs" en segundos en vez de esperar el latido pesado de 180s,
    sin necesidad de infraestructura nueva (WebSockets/Redis) ni costo extra
    de Turso — se decidió así explícitamente en vez de un canal en tiempo real."""
    def _loop():
        time.sleep(15)  # dejar que termine el sync inicial primero
        while True:
            try:
                _check_new_product_images()
            except Exception as e:
                print(f"[Sync] Error en chequeo rápido de fotos: {e}")
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="ImgWatch")
    t.start()
    return t


_bg_thread: threading.Thread | None = None


def asegurar_background_sync(interval: int = 180) -> None:
    """Arranca el hilo de sync si no está corriendo — para cuando una sucursal
    que trabajaba solo local se conecta a la nube sin reiniciar el programa."""
    if _bg_thread is None or not _bg_thread.is_alive():
        start_background_sync(interval=interval)


def start_background_sync(interval: int = 30) -> threading.Thread:
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
        try:
            reparar_costos_turso()
        except Exception as e:
            print(f"[Sync] reparar_costos_turso error: {e}")
        # Then pull to get changes from other PCs
        try:
            sync_from_turso()
        except Exception as e:
            print(f"[Sync] Initial pull error: {e}")
        initial_sync_done.set()
        threading.Thread(target=_sync_product_images_bg, daemon=True, name="ImgCache").start()

        while True:
            # Returns True if event fired (dirty write), False if timed out (heartbeat)
            woke_by_write = _dirty.wait(timeout=interval)
            _dirty.clear()
            if woke_by_write:
                # One sale/edit = several commits (venta + items_venta + stock update
                # + movimiento) → several mark_dirty() calls in a row. Without this,
                # each one triggered its own sync_to_turso() pass. Coalesce the burst
                # into a single push.
                time.sleep(3)
                _dirty.clear()
            try:
                # Push disparado por una escritura: solo tablas incrementales
                # (ventas, productos, movimientos_stock...) — nunca relee/resube
                # tablas completas como lotes/cortes_caja/compras/citas/gastos en
                # cada venta, eso ya volvía cada cobro más lento y gastaba lecturas
                # de Turso sin necesidad a medida que esas tablas crecían. Esas
                # tablas se sincronizan completas en el latido de abajo.
                sync_to_turso(only_incremental=woke_by_write)
            except Exception as e:
                print(f"[Sync] Push error: {e}")
            # Pull ONLY on heartbeat (timeout), NOT on every write.
            # Pulling after a sale risks fetching Turso's pre-sale value (HTTP race)
            # before our push is visible in Turso. Local stock is authoritative.
            if not woke_by_write:
                try:
                    sync_from_turso()
                    threading.Thread(target=_sync_product_images_bg, daemon=True, name="ImgCache").start()
                except Exception as e:
                    print(f"[Sync] Pull error: {e}")

    global _bg_thread
    t = threading.Thread(target=_loop, daemon=True, name="TursoSync")
    t.start()
    _bg_thread = t
    print(f"[Sync] Background sync started (push on write + pull every {interval}s)")
    return t
