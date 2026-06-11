"""
One-time cleanup: delete test/garbage products (IDs 1-5) from local SQLite AND Turso.
Also zeros out any lotes associated with them.
Run: python cleanup_productos_prueba.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import app.config as cfg
from app.database.connection import init_db
import sqlite3

PRODUCT_IDS = [1, 2, 3, 4, 5]

def run_local():
    print(f"[Local] Conectando a {cfg.DB_PATH}")
    conn = sqlite3.connect(str(cfg.DB_PATH))
    cur = conn.cursor()

    # Show what we're deleting
    cur.execute(f"SELECT id, nombre, activo FROM productos WHERE id IN ({','.join('?'*len(PRODUCT_IDS))})", PRODUCT_IDS)
    rows = cur.fetchall()
    if not rows:
        print("[Local] Productos 1-5 no existen en local — OK")
    else:
        print("[Local] Productos encontrados:")
        for r in rows:
            print(f"  id={r[0]}  nombre={r[1]}  activo={r[2]}")

    # Zero out lotes
    cur.execute(f"UPDATE lotes SET cantidad=0 WHERE producto_id IN ({','.join('?'*len(PRODUCT_IDS))})", PRODUCT_IDS)
    print(f"[Local] Lotes zeroed: {cur.rowcount}")

    # Zero product stock and mark inactive
    cur.execute(
        f"UPDATE productos SET activo=0, stock=0, codigo_barras=NULL WHERE id IN ({','.join('?'*len(PRODUCT_IDS))})",
        PRODUCT_IDS,
    )
    print(f"[Local] Productos desactivados: {cur.rowcount}")

    conn.commit()
    conn.close()
    print("[Local] Hecho.")


def run_turso():
    print(f"\n[Turso] Conectando a {cfg.TURSO_DATABASE_URL}")
    from app.database.turso_http import connect
    conn = connect(cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN)
    cur = conn.cursor()

    # Show what exists
    cur.execute(f"SELECT id, nombre, activo FROM productos WHERE id IN ({','.join('?'*len(PRODUCT_IDS))})", PRODUCT_IDS)
    rows = cur.fetchall()
    if not rows:
        print("[Turso] Productos 1-5 no existen en Turso — OK")
    else:
        print("[Turso] Productos encontrados:")
        for r in rows:
            print(f"  id={r[0]}  nombre={r[1]}  activo={r[2]}")

    # Zero out lotes
    cur.execute(f"UPDATE lotes SET cantidad=0 WHERE producto_id IN ({','.join('?'*len(PRODUCT_IDS))})", PRODUCT_IDS)
    print(f"[Turso] Lotes zeroed")

    # Deactivate products
    cur.execute(
        f"UPDATE productos SET activo=0, stock=0, codigo_barras=NULL WHERE id IN ({','.join('?'*len(PRODUCT_IDS))})",
        PRODUCT_IDS,
    )
    print(f"[Turso] Productos desactivados")

    conn.commit()
    conn.close()
    print("[Turso] Hecho.")


if __name__ == "__main__":
    init_db()
    run_local()
    run_turso()
    print("\nLimpieza completada. Reinicia la app para ver los cambios.")
