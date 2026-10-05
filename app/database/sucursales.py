"""
Administrar otras sucursales desde esta PC, al instante y en tiempo real.

Cada sucursal tiene su propia BD en Turso. La sucursal de ESTA PC trabaja como
siempre contra su SQLite local (sincronizada con su Turso). Cuando el admin
elige otra sucursal en el selector, el frontend manda `X-Sucursal: <clave>` en
cada request y get_db_session() devuelve una sesión conectada DIRECTO a la BD
de Turso de esa sucursal (igual que el modo Vercel): lo que se lee es lo que
esa sucursal tiene en este momento, y lo que se edita le llega a sus cajas en
su siguiente sync. Nunca se mezcla con la BD local.

El registro de sucursales (url + token de cada una) vive SOLO en esta PC:
DATA_DIR/sucursales.json — no se sincroniza, así los tokens de una sucursal
nunca quedan guardados en la BD de otra.
"""
import contextvars
import json
import re
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.config as cfg

_REG_FILE = cfg.DATA_DIR / "sucursales.json"
_lock = threading.Lock()
_sessions: dict[str, sessionmaker] = {}

# Clave de la sucursal elegida para ESTE request (None = la local).
sucursal_actual: contextvars.ContextVar = contextvars.ContextVar("sucursal_actual", default=None)


def normalizar_clave(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


def listar() -> list[dict]:
    try:
        data = json.loads(_REG_FILE.read_text(encoding="utf-8")) if _REG_FILE.exists() else []
        return [s for s in data if s.get("clave") and s.get("url") and s.get("token")]
    except Exception:
        return []


def _guardar(lista: list[dict]) -> None:
    _REG_FILE.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def obtener(clave: str) -> dict | None:
    return next((s for s in listar() if s["clave"] == clave), None)


def registrar(clave: str, nombre: str, url: str, token: str) -> None:
    with _lock:
        lista = [s for s in listar() if s["clave"] != clave]
        lista.append({"clave": clave, "nombre": nombre, "url": url, "token": token})
        _guardar(lista)
        _sessions.pop(clave, None)


def eliminar(clave: str) -> None:
    with _lock:
        _guardar([s for s in listar() if s["clave"] != clave])
        _sessions.pop(clave, None)


def engine_remoto(url: str, token: str):
    from app.database.turso_http import connect as turso_connect
    return create_engine("sqlite://", creator=lambda: turso_connect(url, token),
                         poolclass=NullPool, echo=False)


def session_remota_actual():
    """Sesión de la sucursal elegida en este request, o None si es la local."""
    clave = sucursal_actual.get()
    if not clave or clave == cfg.SUCURSAL_CLAVE:
        return None
    with _lock:
        maker = _sessions.get(clave)
        if maker is None:
            s = obtener(clave)
            if not s:
                return None
            maker = sessionmaker(autocommit=False, autoflush=False,
                                 bind=engine_remoto(s["url"], s["token"]))
            _sessions[clave] = maker
    return maker()


class SucursalMiddleware:
    """ASGI puro: fija sucursal_actual desde el header X-Sucursal, SOLO si el
    token es de un admin del POS (un cajero nunca puede ver otra sucursal)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        clave = (headers.get(b"x-sucursal") or b"").decode().strip().lower()
        tok = None
        if clave and clave != cfg.SUCURSAL_CLAVE:
            auth = (headers.get(b"authorization") or b"").decode()
            if auth.lower().startswith("bearer "):
                from app.auth.auth_service import verify_api_token
                p = verify_api_token(auth[7:]) or {}
                if p.get("rol") == "admin" and p.get("typ", "pos") == "pos" and obtener(clave):
                    tok = sucursal_actual.set(clave)
        try:
            await self.app(scope, receive, send)
        finally:
            if tok is not None:
                sucursal_actual.reset(tok)
