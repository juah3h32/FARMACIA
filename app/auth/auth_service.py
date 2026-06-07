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


def create_api_token(user_id: int, username: str, nombre: str = "", rol: str = "cajero") -> str:
    expire = datetime.utcnow() + timedelta(hours=config.ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "nombre": nombre, "rol": rol, "exp": expire}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def create_long_token(user_id: int, username: str, nombre: str = "", rol: str = "admin",
                      days: int = 365, token_name: str = "API Token") -> str:
    expire = datetime.utcnow() + timedelta(days=days)
    payload = {
        "sub": str(user_id), "username": username, "nombre": nombre, "rol": rol,
        "exp": expire, "token_name": token_name, "long_lived": True,
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
