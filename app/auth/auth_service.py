import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from app.database.connection import get_db_session
from app.database.models import Usuario, RolUsuario, AuditoriaLog
from app import config

# Usuario activo en sesion de escritorio
current_user: Usuario | None = None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# Hash de relleno: el login lo verifica aunque el usuario no exista, así tarda lo mismo
# y no se puede saber por el tiempo de respuesta qué usuarios existen.
# (Ya calculado, mismo costo 12: generarlo en cada arranque costaba ~0.2 s.)
DUMMY_HASH = "$2b$12$pCaBIuGaj9Jen.pLr7irL.2GBa8ZcUPoy1mpiZ6YD1AsHDamrfrP2"

# Contraseñas con las que se crean las cuentas de fábrica: son públicas, hay que cambiarlas.
_PASSWORDS_DE_FABRICA = {"admin123", "cajero123"}


def es_password_por_defecto(plain: str) -> bool:
    return (plain or "") in _PASSWORDS_DE_FABRICA


# ── Códigos de respaldo (recuperar la cuenta de admin sin internet) ──────────
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # sin 0/O ni 1/I para no confundirlos


def normalizar_codigo(codigo: str) -> str:
    return "".join(ch for ch in (codigo or "").upper() if ch.isalnum())


def generar_codigos_respaldo(n: int = 8) -> list[str]:
    import secrets
    out = []
    for _ in range(n):
        c = "".join(secrets.choice(_ALFABETO) for _ in range(10))
        out.append(f"{c[:4]}-{c[4:8]}-{c[8:]}")
    return out


def generar_codigo_acceso() -> str:
    """Código que el admin le da en persona a quien olvidó su contraseña, ej. K7QM-4TXP."""
    import secrets
    c = "".join(secrets.choice(_ALFABETO) for _ in range(8))
    return f"{c[:4]}-{c[4:]}"


def hash_codigo(codigo: str) -> str:
    """SHA-256 del código de respaldo ya normalizado (10 caracteres al azar ≈ 50 bits)."""
    import hashlib
    return hashlib.sha256(normalizar_codigo(codigo).encode("utf-8")).hexdigest()


def login(username: str, password: str) -> Usuario | None:
    global current_user
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(
            Usuario.username == username,
            Usuario.activo == True
        ).first()
        if not user or not verify_password(password, user.password_hash):
            return None
        # Refresh para mantener en memoria fuera de la sesion
        db.expunge(user)
        current_user = user
        _registrar_auditoria(user.id, "LOGIN", detalles=f"Inicio de sesion: {username}")
        return user
    finally:
        db.close()


def logout():
    global current_user
    if current_user:
        _registrar_auditoria(current_user.id, "LOGOUT", detalles=f"Cierre de sesion: {current_user.username}")
    current_user = None


def get_current_user() -> Usuario | None:
    return current_user


def is_admin() -> bool:
    return current_user is not None and current_user.rol == RolUsuario.admin


def create_api_token(user_id: int, username: str, nombre: str = "", rol: str = "cajero",
                     typ: str = "pos", token_version: int = 0) -> str:
    """typ separa tokens de empleados del POS ("pos") y de clientes de la app
    ("cliente"): ambos se firman con la misma SECRET_KEY y el `sub` es un id de
    tablas distintas — sin esto, el cliente id=1 de la app pasaba como el
    Usuario id=1 (admin) del POS."""
    expire = datetime.utcnow() + timedelta(hours=config.ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "nombre": nombre, "rol": rol,
               "exp": expire, "typ": typ, "tv": int(token_version or 0)}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def create_long_token(user_id: int, username: str, nombre: str = "", rol: str = "admin",
                      days: int = 365, token_name: str = "API Token", token_version: int = 0) -> str:
    expire = datetime.utcnow() + timedelta(days=days)
    payload = {
        "sub": str(user_id), "username": username, "nombre": nombre, "rol": rol,
        "exp": expire, "token_name": token_name, "long_lived": True, "typ": "pos",
        "tv": int(token_version or 0),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def verify_api_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        return None


def _registrar_auditoria(usuario_id: int, accion: str, tabla: str = None, registro_id: int = None, detalles: str = None):
    db = get_db_session()
    try:
        log = AuditoriaLog(
            usuario_id=usuario_id,
            accion=accion,
            tabla=tabla,
            registro_id=registro_id,
            detalles=detalles,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Audit] Failed to log: {e}")
    finally:
        db.close()


def registrar_accion(accion: str, tabla: str = None, registro_id: int = None, detalles: str = None):
    if current_user:
        _registrar_auditoria(current_user.id, accion, tabla, registro_id, detalles)
