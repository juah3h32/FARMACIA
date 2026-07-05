from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from app.database.models import Base, Categoria, Configuracion, Usuario, RolUsuario
import app.config as cfg


def _on_local_commit(session):
    """After any SQLAlchemy commit, signal the Turso sync thread to wake up."""
    if cfg.TURSO_SYNC:
        try:
            from app.database.sync_service import mark_dirty
            mark_dirty()
        except Exception:
            pass


def _build_engine():
    if cfg.USE_TURSO:
        try:
            from app.database.turso_http import connect as turso_connect

            def _creator():
                return turso_connect(cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN)

            return create_engine(
                "sqlite://",
                creator=_creator,
                poolclass=NullPool,
                echo=False,
            )
        except Exception as e:
            print(f"[FarmaciaPOS] Error conectando a Turso: {e} — usando SQLite local")

    # Local SQLite with WAL mode + 30s busy-timeout so concurrent sync threads
    # don't cause "database is locked" when the user writes at the same time.
    eng = create_engine(
        cfg.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )

    @event.listens_for(eng, "connect")
    def _set_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")    # concurrent reads + single writer
        cur.execute("PRAGMA synchronous=NORMAL")  # safe + fast with WAL
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")  # 30s wait before "database is locked"
        cur.close()

    return eng


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Trigger Turso sync after every local write
event.listen(SessionLocal, "after_commit", _on_local_commit)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    return SessionLocal()


def _migrate():
    """Add new columns to existing tables without dropping data."""
    # Create retiros_caja table if it doesn't exist yet
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS retiros_caja ("
                "id INTEGER PRIMARY KEY, "
                "corte_id INTEGER REFERENCES cortes_caja(id), "
                "usuario_id INTEGER NOT NULL REFERENCES usuarios(id), "
                "monto REAL NOT NULL, "
                "concepto TEXT, "
                "creado_en DATETIME)"
            ))
            conn.commit()
        except Exception:
            pass

    new_cols = [
        ("productos", "presentacion",       "VARCHAR(50)"),
        ("productos", "concentracion",      "VARCHAR(50)"),
        ("productos", "contenido",          "VARCHAR(50)"),
        ("productos", "imagen_url",         "VARCHAR(500)"),
        ("productos", "descripcion",        "TEXT"),
        ("productos", "venta_fraccionada",  "BOOLEAN DEFAULT 0"),
        ("productos", "unidades_por_caja",  "INTEGER DEFAULT 1"),
        ("productos", "precio_pieza",       "REAL DEFAULT 0.0"),
        ("productos", "unidad_pieza",       "VARCHAR(30) DEFAULT 'pieza'"),
        ("productos", "unidad_caja",        "VARCHAR(30) DEFAULT 'caja'"),
        ("productos", "piezas_sueltas",     "INTEGER DEFAULT 0"),
        ("usuarios",  "foto_url",           "TEXT"),
        ("pacientes", "cliente_id",         "INTEGER"),
        ("ventas",    "eliminado",          "INTEGER NOT NULL DEFAULT 0"),
        ("ventas",    "eliminado_en",       "TEXT"),
        ("retiros_caja", "tipo",            "VARCHAR(20) DEFAULT 'personal'"),
        ("cortes_caja",  "total_costo",      "REAL DEFAULT 0.0"),
        ("clientes",     "puntos_acumulados", "REAL DEFAULT 0.0"),
        ("clientes",     "puntos_canjeados",  "REAL DEFAULT 0.0"),
        ("productos",    "grupo_terapeutico", "VARCHAR(100)"),
        ("clientes",     "notas_internas",    "TEXT"),
        ("ventas",       "facturada",         "INTEGER NOT NULL DEFAULT 0"),
        ("ventas",       "cfdi_global_id",    "INTEGER"),
        ("ventas",       "actualizado_en",    "TEXT"),
        ("cfdi_facturas_globales", "xml_url", "VARCHAR(500)"),
        ("cfdi_facturas_globales", "pdf_url", "VARCHAR(500)"),
        ("facturas_compra",        "xml_url", "VARCHAR(500)"),
        ("facturas_compra",        "pdf_url", "VARCHAR(500)"),
    ]
    # Local SQLite — collect only columns actually added (new installs / upgrades)
    added: list[tuple] = []
    with engine.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
                added.append((table, col, col_type))
            except Exception:
                pass  # column already exists — skip

    # Tables added after the initial schema — must exist in Turso too, not just local.
    # sync_service.py syncs rows assuming the table is already there; CREATE TABLE IF NOT
    # EXISTS here is what actually creates it in the cloud (desktop app never runs
    # Base.metadata.create_all against Turso — that only happens on Vercel).
    new_tables_ddl = [
        "CREATE TABLE IF NOT EXISTS cfdi_facturas_globales ("
        "id INTEGER PRIMARY KEY, mes INTEGER NOT NULL, anio INTEGER NOT NULL, "
        "subtotal REAL DEFAULT 0.0, iva REAL DEFAULT 0.0, total REAL DEFAULT 0.0, "
        "num_ventas INTEGER DEFAULT 0, estado VARCHAR(20) DEFAULT 'timbrada', "
        "facturama_id VARCHAR(50), uuid_fiscal VARCHAR(50), serie VARCHAR(10), folio VARCHAR(20), "
        "xml_path VARCHAR(300), pdf_path VARCHAR(300), xml_url VARCHAR(500), pdf_url VARCHAR(500), "
        "error_mensaje TEXT, usuario_id INTEGER REFERENCES usuarios(id), "
        "creado_en DATETIME, cancelado_en DATETIME)",
        "CREATE TABLE IF NOT EXISTS facturas_compra ("
        "id INTEGER PRIMARY KEY, proveedor_id INTEGER REFERENCES proveedores(id), "
        "proveedor_nombre VARCHAR(150) NOT NULL, proveedor_rfc VARCHAR(20), "
        "folio_fiscal VARCHAR(50), fecha_factura DATE NOT NULL, "
        "subtotal REAL DEFAULT 0.0, iva REAL DEFAULT 0.0, total REAL NOT NULL, concepto TEXT, "
        "xml_path VARCHAR(300), pdf_path VARCHAR(300), xml_url VARCHAR(500), pdf_url VARCHAR(500), "
        "usuario_id INTEGER REFERENCES usuarios(id), creado_en DATETIME)",
    ]

    # Turso cloud — always attempt every ALTER TABLE (ignore "column already exists" errors).
    # We cannot rely on `added` here because columns added manually to local DB won't be
    # in `added`, yet Turso may still be missing them.
    if cfg.TURSO_SYNC:
        from app.database.sync_service import _turso_pipeline_url, _turso_headers
        import requests as _req
        url, hdrs = _turso_pipeline_url(), _turso_headers()
        try:
            payload = {
                "requests": [
                    {"type": "execute", "stmt": {"sql": ddl, "args": []}}
                    for ddl in new_tables_ddl
                ] + [
                    {"type": "execute", "stmt": {"sql": f"ALTER TABLE {t} ADD COLUMN {c} {ct}", "args": []}}
                    for t, c, ct in new_cols
                ] + [{"type": "close"}]
            }
            _req.post(url, headers=hdrs, json=payload, timeout=15)
        except Exception:
            pass  # network error — safe to ignore, columns get created on next migration run


def init_db():
    # Always run create_all — it's idempotent (creates only missing tables)
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_initial_data()
    _normalizar_nombres_productos()
    _actualizar_info_farmacia_v2()
    _recalcular_cortes_v1()
    _recalcular_cortes_v2()


def _actualizar_info_farmacia_v2():
    """One-time: push corrected pharmacy address/name to existing DBs."""
    with get_db() as db:
        if db.query(Configuracion).filter(
            Configuracion.clave == "farmacia_info_v2"
        ).first():
            return
        for clave, valor in [
            ("farmacia_nombre",    cfg.PHARMACY_NAME),
            ("farmacia_direccion", cfg.PHARMACY_ADDRESS),
        ]:
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = valor
        db.add(Configuracion(clave="farmacia_info_v2", valor="1"))


def _normalizar_nombres_productos():
    """One-time migration: uppercase nombre, nombre_generico, marca for all products."""
    from app.database.models import Producto
    with get_db() as db:
        # Guard: only run once — skip if flag already set
        if db.query(Configuracion).filter(
            Configuracion.clave == "nombres_normalizados_v2"
        ).first():
            return
        prods = db.query(Producto).all()
        for p in prods:
            if p.nombre:
                p.nombre = p.nombre.strip().upper()
            if p.nombre_generico:
                p.nombre_generico = p.nombre_generico.strip().upper()
            if p.marca:
                p.marca = p.marca.strip().upper()
        db.add(Configuracion(clave="nombres_normalizados_v2", valor="1"))


def _seed_initial_data():
    with get_db() as db:
        # Batch-check existing usernames (1 query instead of 2)
        existing_users = {u.username for u in db.query(Usuario.username).all()}

        if "admin" not in existing_users:
            from app.auth.auth_service import hash_password
            db.add(Usuario(
                username="admin",
                password_hash=hash_password("admin123"),
                nombre="Administrador",
                rol=RolUsuario.admin,
            ))

        if "cajero" not in existing_users:
            from app.auth.auth_service import hash_password as _hp2
            db.add(Usuario(
                username="cajero",
                password_hash=_hp2("cajero123"),
                nombre="Cajero Prueba",
                rol=RolUsuario.cajero,
            ))

        # Batch-check existing categories (1 query instead of 10)
        categorias_default = [
            "Medicamentos Generales", "Antibióticos", "Vitaminas y Suplementos",
            "Cuidado Personal",       "Material de Curación", "Productos de Bebé",
            "Medicamentos Controlados", "Dermatología",       "Oftalmología",
            "Anticonceptivos",
        ]
        existing_cats = {c.nombre for c in db.query(Categoria.nombre).all()}
        for nombre in categorias_default:
            if nombre not in existing_cats:
                db.add(Categoria(nombre=nombre))

        # Batch-check existing config keys (1 query instead of 11)
        from app.auth.auth_service import hash_password as _hp
        configs_default = {
            "farmacia_nombre":          cfg.PHARMACY_NAME,
            "farmacia_direccion":       cfg.PHARMACY_ADDRESS,
            "farmacia_telefono":        cfg.PHARMACY_PHONE,
            "farmacia_rfc":             cfg.PHARMACY_RFC,
            "tasa_iva":                 str(cfg.TAX_RATE),
            "stock_minimo_alerta":      str(cfg.LOW_STOCK_THRESHOLD),
            "dias_vencimiento_alerta":  str(cfg.EXPIRY_ALERT_DAYS),
            "impresora_tipo":           "usb",
            "impresora_puerto":         "COM1",
            "impresora_ancho":          "32",
            "api_activa":               "true",
            "purge_password_hash":      _hp("171215"),
            "turno_auto_activo":        "false",
            "turno_auto_inicio":        "09:00",
            "turno_auto_fin":           "21:00",
        }
        existing_cfg = {c.clave for c in db.query(Configuracion.clave).all()}
        for clave, valor in configs_default.items():
            if clave not in existing_cfg:
                db.add(Configuracion(clave=clave, valor=valor))


def _recalcular_cortes_v1():
    """
    One-time migration:
    1. Recalculate stored totals for all closed cortes from actual ventas.
    2. For ventas NOT covered by any corte period, create synthetic daily cortes.
    This repairs data from before the corte system was in use.
    """
    with get_db() as db:
        if db.query(Configuracion).filter(Configuracion.clave == "recalculo_cortes_v1").first():
            return

        from datetime import date as _date, timedelta as _td
        from collections import defaultdict
        from app.database.models import (
            CortesCaja, Venta, EstadoVenta, MetodoPago, ItemVenta, Producto as _Prod
        )

        # ── Step 1: Recalculate stored totals for all closed cortes ──────────
        closed_cortes = db.query(CortesCaja).filter(CortesCaja.cerrado_en != None).all()
        covered_intervals = []
        for c in closed_cortes:
            if not c.abierto_en or not c.cerrado_en:
                continue
            ventas = db.query(Venta).filter(
                Venta.creado_en >= c.abierto_en,
                Venta.creado_en <= c.cerrado_en,
                Venta.estado == EstadoVenta.completada,
                Venta.eliminado.is_not(True),
            ).all()
            ef = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.efectivo)
            tj = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.tarjeta)
            tr = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.transferencia)
            tv = ef + tj + tr
            vids = [v.id for v in ventas]
            if vids:
                cost_rows = (
                    db.query(ItemVenta.cantidad, _Prod.precio_compra)
                    .join(_Prod, ItemVenta.producto_id == _Prod.id)
                    .filter(ItemVenta.venta_id.in_(vids))
                    .all()
                )
                tc = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)
            else:
                tc = 0.0
            c.total_ventas        = tv
            c.total_efectivo      = ef
            c.total_tarjeta       = tj
            c.total_transferencia = tr
            c.total_costo         = tc
            c.num_ventas          = len(ventas)
            covered_intervals.append((c.abierto_en, c.cerrado_en))

        # ── Step 2: Find ventas NOT in any corte period ───────────────────────
        all_ventas = db.query(Venta).filter(
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
            Venta.creado_en != None,
        ).all()

        def _is_covered(v):
            for ini, fin in covered_intervals:
                if ini <= v.creado_en <= fin:
                    return True
            return False

        orphans = [v for v in all_ventas if not _is_covered(v)]

        # ── Step 3: Group orphan ventas by (usuario_id, day) ─────────────────
        day_groups: dict = defaultdict(list)
        for v in orphans:
            day = v.creado_en.date()
            if day >= _date.today():
                continue  # skip today — active corte will handle it
            day_groups[(v.usuario_id, day)].append(v)

        # ── Step 4: Create synthetic closed cortes per day ───────────────────
        from datetime import datetime as _dt
        for (uid, day), day_ventas in sorted(day_groups.items()):
            ef = sum(v.total for v in day_ventas if v.metodo_pago == MetodoPago.efectivo)
            tj = sum(v.total for v in day_ventas if v.metodo_pago == MetodoPago.tarjeta)
            tr = sum(v.total for v in day_ventas if v.metodo_pago == MetodoPago.transferencia)
            tv = ef + tj + tr
            vids = [v.id for v in day_ventas]
            if vids:
                cost_rows = (
                    db.query(ItemVenta.cantidad, _Prod.precio_compra)
                    .join(_Prod, ItemVenta.producto_id == _Prod.id)
                    .filter(ItemVenta.venta_id.in_(vids))
                    .all()
                )
                tc = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)
            else:
                tc = 0.0

            apertura = _dt.combine(day, _dt.min.time()).replace(hour=8,  minute=0, second=0)
            cierre   = _dt.combine(day, _dt.min.time()).replace(hour=21, minute=0, second=0)
            db.add(CortesCaja(
                usuario_id        = uid,
                monto_apertura    = 0.0,
                monto_cierre      = ef,
                total_ventas      = tv,
                total_efectivo    = ef,
                total_tarjeta     = tj,
                total_transferencia = tr,
                total_costo       = tc,
                num_ventas        = len(day_ventas),
                abierto_en        = apertura,
                cerrado_en        = cierre,
                notas             = "[Cierre histórico — generado automáticamente]",
            ))

        db.add(Configuracion(clave="recalculo_cortes_v1", valor="1"))
        print(f"[Migration] recalculo_cortes_v1: recalculados={len(closed_cortes)} cortes, "
              f"creados={len(day_groups)} cortes históricos")


def _recalcular_cortes_v2():
    """
    One-time: normalize monto_cierre = monto_apertura + total_efectivo for all
    closed cortes. Eliminates false 'Descuadre' caused by v1 recalculation
    changing total_efectivo without updating the manually-entered monto_cierre.
    """
    with get_db() as db:
        if db.query(Configuracion).filter(Configuracion.clave == "recalculo_cortes_v2").first():
            return
        from app.database.models import CortesCaja
        closed = db.query(CortesCaja).filter(CortesCaja.cerrado_en != None).all()
        for c in closed:
            c.monto_cierre = (c.monto_apertura or 0.0) + (c.total_efectivo or 0.0)
        db.add(Configuracion(clave="recalculo_cortes_v2", valor="1"))
        print(f"[Migration] recalculo_cortes_v2: normalizados {len(closed)} monto_cierre")
