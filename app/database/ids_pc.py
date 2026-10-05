"""
Rango de ids propio por PC para las tablas que se crean en varias cajas a la vez.

Antes cada PC tomaba max(id)+1 de su SQLite local: si dos cajas cobraban entre
un sync y otro, ambas generaban p. ej. la venta id=500 y al subir a Turso una
pisaba a la otra (INSERT OR REPLACE / ON CONFLICT(id)). Al jalar de la nube,
la venta o el retiro de una PC desaparecía o quedaba con items de otra venta,
y la ganancia/capital del Control de Caja "brincaba" (se notaba al abrir
Inventario, que dispara el pull).

Ahora cada PC elige al azar, una sola vez, un bloque de ID_BLOQUE ids
(guardado en DATA_DIR/pc_id.json, que NO se sincroniza) y asigna ids nuevos
solo dentro de su bloque. Los ids viejos (< ID_BLOQUE) quedan como están.
"""
import json
import random
import threading

from sqlalchemy import event, text

import app.config as cfg

ID_BLOQUE = 10_000_000

# Tablas que más de una PC inserta (ventas, dinero, inventario).
TABLAS = frozenset({
    "ventas", "items_venta", "cortes_caja", "retiros_caja", "movimientos_stock",
    "compras", "items_compra", "lotes", "facturas_compra", "auditoria_log", "gastos",
})

_PC_FILE = cfg.DATA_DIR / "pc_id.json"
_lock = threading.Lock()
_ultimo: dict[tuple, int] = {}   # (BD, tabla) → último id usado
_base: int | None = None


def base_pc() -> int:
    """Primer id del bloque de esta PC (n * ID_BLOQUE, n entre 1 y 899)."""
    global _base
    if _base is not None:
        return _base
    n = None
    try:
        if _PC_FILE.exists():
            n = int(json.loads(_PC_FILE.read_text(encoding="utf-8"))["bloque"])
    except Exception:
        n = None
    if not n or n < 1:
        n = random.SystemRandom().randint(1, 899)
        _PC_FILE.write_text(json.dumps({"bloque": n}), encoding="utf-8")
    _base = n * ID_BLOQUE
    return _base


def _siguiente_id(connection, tabla: str) -> int:
    base = base_pc()
    # La caché es por BD: la misma PC puede insertar en la local y en la de otra
    # sucursal (admin administrando otra sucursal) y cada una lleva su propio máximo.
    key = (id(connection.engine), tabla)
    with _lock:
        if key not in _ultimo:
            ultimo = connection.execute(
                text(f"SELECT MAX(id) FROM {tabla} WHERE id >= :a AND id < :b"),
                {"a": base, "b": base + ID_BLOQUE},
            ).scalar()
            _ultimo[key] = ultimo or base
        _ultimo[key] += 1
        return _ultimo[key]


def _before_insert(mapper, connection, target):
    if getattr(target, "id", None) is None:
        target.id = _siguiente_id(connection, mapper.local_table.name)


def instalar(base_cls) -> None:
    """Engancha la asignación de ids a los modelos de TABLAS (idempotente)."""
    for m in base_cls.registry.mappers:
        if m.local_table is not None and m.local_table.name in TABLAS:
            if not event.contains(m.class_, "before_insert", _before_insert):
                event.listen(m.class_, "before_insert", _before_insert)
