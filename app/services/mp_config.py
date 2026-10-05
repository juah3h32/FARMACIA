"""Persistencia de la configuración de Mercado Pago Point.

- Access Token: es de la CUENTA → se guarda en archivo local (DATA_DIR) y en la
  tabla `configuracion` (se sincroniza con Turso), así las demás PCs lo reciben
  sin capturarlo otra vez.
- Terminal (device id): normalmente una por caja → el archivo local de cada PC
  manda; la tabla `configuracion` guarda la última elegida como valor por
  defecto para PCs que aún no eligieron la suya.
Prioridad token: variable de entorno > tabla configuracion > archivo local.
Prioridad terminal: variable de entorno > archivo local > tabla configuracion.
"""
import os
import app.config as cfg

_TOKEN_FILE = "mp_access_token.key"
_DEVICE_FILE = "mp_device_id.key"
_K_TOKEN = "mp_access_token"
_K_DEVICE = "mp_terminal_id"


def _read_file(name: str) -> str:
    f = cfg.DATA_DIR / name
    try:
        return f.read_text(encoding="utf-8").strip() if f.exists() else ""
    except Exception:
        return ""


def _read_db(clave: str) -> str:
    try:
        from app.database.connection import get_db_session
        from app.database.models import Configuracion
        db = get_db_session()
        try:
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            return (row.valor or "").strip() if row else ""
        finally:
            db.close()
    except Exception:
        return ""


def _write_db(clave: str, valor: str) -> None:
    try:
        from app.database.connection import get_db_session
        from app.database.models import Configuracion
        db = get_db_session()
        try:
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = valor
            else:
                db.add(Configuracion(clave=clave, valor=valor))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def cargar_config() -> tuple[str, str]:
    # Token: la tabla `configuracion` va ANTES que el archivo local. Si el dueño
    # cambia el token en otra PC, el archivo viejo de esta PC ya no lo tapa
    # (antes esta PC seguía usando el token anterior para siempre).
    token = os.getenv("MP_ACCESS_TOKEN", "") or _read_db(_K_TOKEN) or _read_file(_TOKEN_FILE)
    device = os.getenv("MP_DEVICE_ID", "") or _read_file(_DEVICE_FILE) or _read_db(_K_DEVICE)
    return token.strip(), device.strip()


def guardar_config(token: str, device: str) -> None:
    token = (token or "").strip()
    device = (device or "").strip()
    if token:
        (cfg.DATA_DIR / _TOKEN_FILE).write_text(token, encoding="utf-8")
        _write_db(_K_TOKEN, token)
        cfg.MP_ACCESS_TOKEN = token
    if device:
        (cfg.DATA_DIR / _DEVICE_FILE).write_text(device, encoding="utf-8")
        _write_db(_K_DEVICE, device)
        cfg.MP_DEVICE_ID = device
