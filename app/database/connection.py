from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from app.database.models import Base, Categoria, Configuracion, Usuario, RolUsuario
import app.config as cfg


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
    new_cols = [
        ("productos", "presentacion",         "VARCHAR(50)"),
        ("productos", "concentracion",        "VARCHAR(50)"),
        ("productos", "contenido",            "VARCHAR(50)"),
        ("productos", "sustancia_controlada", "BOOLEAN DEFAULT 0"),
        ("lotes",     "precio_compra",        "REAL DEFAULT 0.0"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # column already exists


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_initial_data()


def _seed_initial_data():
    with get_db() as db:
        # Admin por defecto
        admin = db.query(Usuario).filter(Usuario.username == "admin").first()
        if not admin:
            from app.auth.auth_service import hash_password
            admin = Usuario(
                username="admin",
                password_hash=hash_password("admin123"),
                nombre="Administrador",
                rol=RolUsuario.admin,
            )
            db.add(admin)

        # Categorias default
        categorias_default = [
            "Medicamentos Generales", "Antibióticos", "Vitaminas y Suplementos",
            "Cuidado Personal",       "Material de Curación", "Productos de Bebé",
            "Medicamentos Controlados", "Dermatología",       "Oftalmología",
        ]
        for nombre in categorias_default:
            if not db.query(Categoria).filter(Categoria.nombre == nombre).first():
                db.add(Categoria(nombre=nombre))

        # Configuraciones default
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
            "api_activa":               "true",
        }
        for clave, valor in configs_default.items():
            if not db.query(Configuracion).filter(Configuracion.clave == clave).first():
                db.add(Configuracion(clave=clave, valor=valor))
