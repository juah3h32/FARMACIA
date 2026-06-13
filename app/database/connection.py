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

    # Local SQLite with WAL mode for crash safety
    eng = create_engine(
        cfg.DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(eng, "connect")
    def _set_pragmas(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")   # survives crashes without corruption
        cur.execute("PRAGMA synchronous=NORMAL")  # safe + fast with WAL
        cur.execute("PRAGMA foreign_keys=ON")
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
                    {"type": "execute", "stmt": {"sql": f"ALTER TABLE {t} ADD COLUMN {c} {ct}", "args": []}}
                    for t, c, ct in new_cols
                ] + [{"type": "close"}]
            }
            _req.post(url, headers=hdrs, json=payload, timeout=15)
        except Exception:
            pass  # network error — safe to ignore, columns get created on next migration run


def init_db():
    # Fast path: skip create_all if schema already exists (saves ~400ms on every run)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT id FROM usuarios LIMIT 1"))
    except Exception:
        Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_initial_data()
    _normalizar_nombres_productos()
    _actualizar_info_farmacia_v2()


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
            "turno_auto_activo":        "true",
            "turno_auto_inicio":        "09:00",
            "turno_auto_fin":           "10:00",
        }
        existing_cfg = {c.clave for c in db.query(Configuracion.clave).all()}
        for clave, valor in configs_default.items():
            if clave not in existing_cfg:
                db.add(Configuracion(clave=clave, valor=valor))
