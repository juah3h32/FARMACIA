from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
from app.api.routes.auth_routes import get_current_api_user
import app.config as cfg

router = APIRouter()


@router.get("/desktop-keys")
def desktop_keys(payload: dict = Depends(get_current_api_user)):
    """Devuelve las claves API al cliente de escritorio.
    Solo accesible por admin. En Vercel, cfg las lee de env vars."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return {
        "OPENAI_API_KEY":        cfg.OPENAI_API_KEY,
        "TURSO_AUTH_TOKEN":      cfg.TURSO_AUTH_TOKEN,
        "CLOUDINARY_CLOUD_NAME": cfg.CLOUDINARY_CLOUD_NAME,
        "CLOUDINARY_API_KEY":    cfg.CLOUDINARY_API_KEY,
        "CLOUDINARY_API_SECRET": cfg.CLOUDINARY_API_SECRET,
    }


# ── Integraciones propias (Turso / OpenAI / Cloudinary) ──────────────────────
# Cada instalación (comprador del programa) captura sus propias claves aquí.
# En EXE/dev: se guardan como archivos en DATA_DIR (misma prioridad que env vars
# en app/config.py: env var > archivo local > vacío). En Vercel: se configuran
# como variables de entorno en el dashboard, esta pantalla no aplica ahí.

_INTEGRACIONES_MAP = {
    "turso_database_url":   ("TURSO_DATABASE_URL",   "turso_url.key",        False),
    "turso_auth_token":     ("TURSO_AUTH_TOKEN",      "turso.key",            True),
    "openai_api_key":       ("OPENAI_API_KEY",        "openai.key",           True),
    "cloudinary_cloud_name": ("CLOUDINARY_CLOUD_NAME", "cloudinary_cloud.key", False),
    "cloudinary_api_key":   ("CLOUDINARY_API_KEY",    "cloudinary_api.key",   True),
    "cloudinary_api_secret": ("CLOUDINARY_API_SECRET", "cloudinary_secret.key", True),
    "removebg_api_key":     ("REMOVEBG_API_KEY",      "removebg.key",         True),
}


@router.get("/integraciones")
def get_integraciones(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    out = {"on_vercel": bool(cfg._ON_VERCEL)}
    for field, (attr, _filename, is_secret) in _INTEGRACIONES_MAP.items():
        val = getattr(cfg, attr, "") or ""
        out[field] = _mask(val) if is_secret else val
    out["removebg_auto"] = bool(cfg.REMOVEBG_AUTO)
    return out


class IntegracionesIn(BaseModel):
    turso_database_url: str = ""
    turso_auth_token: str = ""
    openai_api_key: str = ""
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    removebg_api_key: str = ""
    removebg_auto: bool = False


@router.post("/integraciones")
def set_integraciones(body: IntegracionesIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if cfg._ON_VERCEL:
        raise HTTPException(
            status_code=400,
            detail="En la versión web estas claves se configuran como variables de "
                   "entorno en el dashboard de Vercel, no desde aquí.",
        )
    data = body.dict()
    changed_turso = False
    for field, (attr, filename, is_secret) in _INTEGRACIONES_MAP.items():
        val = data.get(field, "").strip()
        if not val or (is_secret and val.startswith(_MASK_PREFIX)):
            continue  # usuario no tocó el campo — conservar valor actual
        (cfg.DATA_DIR / filename).write_text(val, encoding="utf-8")
        setattr(cfg, attr, val)
        if attr.startswith("TURSO_"):
            changed_turso = True

    # Booleano — a diferencia de las claves de arriba, siempre tiene un valor
    # definido (no hay "el usuario no tocó el campo" para un checkbox), así
    # que se persiste directo en cada guardado, no solo cuando cambia.
    (cfg.DATA_DIR / "removebg_auto.key").write_text("1" if body.removebg_auto else "0", encoding="utf-8")
    cfg.REMOVEBG_AUTO = body.removebg_auto

    # Si el equipo quedó en modo "local"/"offline" (elegido en el asistente de
    # primer arranque, p. ej. porque en ese momento no se tenían las claves de
    # Turso a la mano — el asistente promete "podrás activar la nube después
    # desde Configuración") y ahora ya hay URL + token de Turso guardados, hay
    # que pasar sync_mode a "turso" aquí mismo. Sin esto, TURSO_SYNC se quedaba
    # en False para siempre sin importar cuántas veces se guardaran credenciales
    # válidas — probar conexión nunca mostraba "Conectado", solo el mensaje de
    # "Sincronización con Turso desactivada (modo local)".
    switched_to_turso = False
    if cfg.TURSO_DATABASE_URL and cfg.TURSO_AUTH_TOKEN and cfg.SYNC_MODE != "turso":
        try:
            # Conservar el resto de setup.json (p. ej. la sucursal de esta PC)
            _setup = cfg._load_setup()
            _setup["sync_mode"] = "turso"
            cfg.SETUP_FILE.write_text(json.dumps(_setup), encoding="utf-8")
            cfg.reload_setup()
            switched_to_turso = True
        except Exception:
            pass

    return {
        "ok": True,
        # El engine/hilo de sync de Turso se arma al iniciar el programa —
        # aunque la prueba de conexión ya funciona en caliente (ver reload_setup
        # arriba), el push/pull en segundo plano necesita reiniciar para activarse.
        "restart_required": changed_turso or switched_to_turso,
    }


# ── Catálogo público (exponer /api/public/* a la red/internet) ───────────────
# Por default el POS solo escucha en 127.0.0.1 — nada fuera de este equipo
# puede pegarle. Al activarse: bind pasa a 0.0.0.0 y el puerto queda fijo
# (ver app/config.py y main.py), pero seguir siendo visible desde internet
# depende de que el comprador abra ese puerto en su router (o use un túnel).

def _lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


@router.get("/catalogo-publico")
def get_catalogo_publico(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return {
        "on_vercel": bool(cfg._ON_VERCEL),
        "enabled": bool(cfg.CATALOGO_PUBLICO),
        "lan_url": f"http://{_lan_ip()}:{cfg.API_PORT}/api/public/productos",
    }


class CatalogoPublicoIn(BaseModel):
    enabled: bool


@router.post("/catalogo-publico")
def set_catalogo_publico(body: CatalogoPublicoIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if cfg._ON_VERCEL:
        raise HTTPException(status_code=400, detail="En la versión web el catálogo ya es público por diseño.")
    (cfg.DATA_DIR / "catalogo_publico.key").write_text("1" if body.enabled else "0", encoding="utf-8")
    cfg.CATALOGO_PUBLICO = body.enabled
    return {"ok": True, "restart_required": True}


# ── Mercado Pago Point (Orders API) ───────────────────────────────────────────
# Ver app/services/mercadopago_service.py para el porqué de cada endpoint.

class MpSaveIn(BaseModel):
    token: Optional[str] = ""
    device_id: Optional[str] = ""


def _mp_device_valid(device_id: str) -> bool:
    # Mismo criterio que usa el POS (mp_point.enabled) — ver device_valido()
    from app.services.mercadopago_service import device_valido
    return device_valido(device_id)


def _mp_raise(e):
    # e.http_status: un 401 de Mercado Pago se responde como 400 para que el
    # frontend no lo confunda con "sesión vencida" y cierre la sesión del admin.
    raise HTTPException(status_code=e.http_status, detail=e.message)


@router.get("/mp-status")
def mp_status(payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    mp_point.recargar()  # toma el token si se cambió en otra PC
    device_id = mp_point.device_id
    valid_device = _mp_device_valid(device_id)
    return {
        "enabled":   mp_point.enabled,
        "token_set": bool(mp_point.access_token),
        "token_mask": _mask(mp_point.access_token),
        "device_id": device_id if valid_device else "",
    }


@router.post("/mp-save")
def mp_save(body: MpSaveIn, payload: dict = Depends(get_current_api_user)):
    """Guarda sin consultar a Mercado Pago (así se puede guardar aunque MP falle;
    la validación real la hacen Detectar / Diagnóstico)."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point
    from app.services.mp_config import guardar_config
    mp_point.ensure_loaded()
    # Misma limpieza que Detectar: antes se guardaba el texto tal cual (con
    # espacios/"Bearer"/máscara pegada) y Detectar usaba otro token distinto.
    token = _token_from(body.token)
    device = (body.device_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Access Token requerido")
    if device and not _mp_device_valid(device):
        raise HTTPException(status_code=400, detail="ID de terminal inválido — usa el botón Detectar")
    guardar_config(token, device)
    mp_point.configure(token, device or mp_point.device_id)
    return {"ok": True, "enabled": mp_point.enabled}


def _token_from(token: Optional[str]) -> str:
    """Token que manda la pantalla; si viene vacío o es la máscara "••••abcd"
    (campo sin tocar), se usa el guardado."""
    from app.services.mercadopago_service import mp_point, limpiar_token
    mp_point.ensure_loaded()
    t = limpiar_token(token)
    if not t or t.startswith(_MASK_PREFIX):
        t = mp_point.access_token
    return t


class MpTokenIn(BaseModel):
    token: Optional[str] = ""
    device_id: Optional[str] = ""


def _mp_detectar(token: Optional[str]) -> dict:
    from app.services.mercadopago_service import mp_point, MercadoPagoError
    use_token = _token_from(token)
    if not use_token:
        raise HTTPException(status_code=400, detail="Access Token no configurado")
    try:
        cuenta = mp_point.verificar_token(token=use_token)   # token válido y de México
        terms = mp_point.list_terminals(token=use_token)
    except MercadoPagoError as e:
        _mp_raise(e)
    # Se conserva la llave "devices" que ya usa el frontend
    return {"cuenta": cuenta, "devices": [
        {"id": t.get("id"), "operating_mode": t.get("operating_mode", ""),
         "store_id": t.get("store_id"), "pos_id": t.get("pos_id"),
         "external_pos_id": t.get("external_pos_id"), "api": t.get("api", "")}
        for t in terms
    ]}


@router.get("/mp-devices")
def mp_devices(token: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    # Compatibilidad: la pantalla nueva usa POST (el token en la URL queda en logs)
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return _mp_detectar(token)


@router.post("/mp-devices")
def mp_devices_post(body: MpTokenIn = MpTokenIn(), payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return _mp_detectar(body.token)


@router.post("/mp-diagnostico")
def mp_diagnostico(body: MpTokenIn = MpTokenIn(), payload: dict = Depends(get_current_api_user)):
    """Checklist paso a paso (token, cuenta, terminales en API nueva y anterior,
    sucursales, cajas, terminal elegida, modo PDV) con el texto crudo de MP.
    Solo lectura: no guarda ni cambia nada."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point
    return mp_point.diagnostico(token=_token_from(body.token), device_id=body.device_id)


class MpPdvIn(BaseModel):
    token: Optional[str] = ""
    device_id: Optional[str] = ""


@router.post("/mp-pdv")
def mp_set_pdv(body: MpPdvIn = MpPdvIn(), payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point, MercadoPagoError
    token = _token_from(body.token)
    device_id = (body.device_id or "").strip() or mp_point.device_id
    if not token or not device_id:
        raise HTTPException(status_code=400, detail="Guarda el Access Token y elige la terminal primero")
    try:
        data = mp_point.set_pdv_mode(device_id, token=token)
    except MercadoPagoError as e:
        _mp_raise(e)
    modo = ""
    for t in (data.get("terminals") or []):
        if t.get("id") == device_id:
            modo = t.get("operating_mode", "")
    return {"ok": True, "operating_mode": modo or "PDV",
            "message": "Modo PDV activado. REINICIA la terminal (apágala y enciéndela) para que aplique."}


# ── WhatsApp Alertas (CallMeBot) ─────────────────────────────────────────────

_WA_KEYS = ["whatsapp_numero", "whatsapp_token", "alertas_activas"]


@router.get("/alertas")
def get_alertas(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        rows = db.query(Configuracion).filter(Configuracion.clave.in_(_WA_KEYS)).all()
        d = {r.clave: r.valor for r in rows}
        return {
            "numero":   d.get("whatsapp_numero", ""),
            "token":    d.get("whatsapp_token", ""),
            "activas":  d.get("alertas_activas", "0") == "1",
        }
    finally:
        db.close()


class AlertasIn(BaseModel):
    numero: str
    token: str
    activas: bool = False


@router.post("/alertas")
def set_alertas(body: AlertasIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        updates = {
            "whatsapp_numero": body.numero.strip(),
            "whatsapp_token":  body.token.strip(),
            "alertas_activas": "1" if body.activas else "0",
        }
        for clave, valor in updates.items():
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = valor
            else:
                db.add(Configuracion(clave=clave, valor=valor))
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/alertas/test")
def test_alerta(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.alertas_service import _send_whatsapp, _get_config
    from app.database.connection import get_db_session
    db = get_db_session()
    try:
        cfg_data = _get_config(db)
        numero = cfg_data.get("whatsapp_numero", "")
        token  = cfg_data.get("whatsapp_token", "")
        if not numero or not token:
            raise HTTPException(status_code=400, detail="Configura número y token primero")
        _send_whatsapp(numero, token, "FarmaciaPOS: Prueba de alertas WhatsApp OK")
        return {"ok": True}
    finally:
        db.close()


# ── Facturación CFDI (Facturama) ─────────────────────────────────────────────

_FACT_KEYS = [
    "facturacom_api_key", "facturacom_secret_key", "facturacom_sandbox",
    "emisor_razon_social", "emisor_rfc", "emisor_regimen_fiscal", "emisor_cp",
    "email_smtp_host", "email_smtp_port", "email_smtp_user", "email_smtp_password",
]

# Prefijo que marca un valor como "enmascarado, sin cambios" — si el front lo regresa
# tal cual (usuario no tocó el campo), el POST sabe que debe conservar el valor real
# guardado en vez de sobreescribirlo con la máscara.
_MASK_PREFIX = "••••"


def _mask(v: str) -> str:
    if not v:
        return ""
    return _MASK_PREFIX + (v[-4:] if len(v) > 4 else "")


@router.get("/facturacion")
def get_facturacion(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        rows = db.query(Configuracion).filter(Configuracion.clave.in_(_FACT_KEYS)).all()
        d = {r.clave: r.valor for r in rows}
        return {
            # Nunca se regresan en texto plano al navegador — solo los últimos 4
            # caracteres, para que no queden expuestas en devtools/historial de red.
            "facturacom_api_key":    _mask(d.get("facturacom_api_key", "")),
            "facturacom_secret_key": _mask(d.get("facturacom_secret_key", "")),
            "facturacom_sandbox":    d.get("facturacom_sandbox", "1") == "1",
            "emisor_razon_social":  d.get("emisor_razon_social") or cfg.PHARMACY_RAZON_SOCIAL_FISCAL,
            "emisor_rfc":           d.get("emisor_rfc") or cfg.PHARMACY_RFC,
            "emisor_regimen_fiscal": d.get("emisor_regimen_fiscal") or cfg.PHARMACY_REGIMEN_FISCAL,
            "emisor_cp":            d.get("emisor_cp") or cfg.PHARMACY_CP_FISCAL,
            "email_smtp_host":      d.get("email_smtp_host", ""),
            "email_smtp_port":      d.get("email_smtp_port", "587"),
            "email_smtp_user":      d.get("email_smtp_user", ""),
            "email_smtp_password":  _mask(d.get("email_smtp_password", "")),
        }
    finally:
        db.close()


class FacturacionIn(BaseModel):
    facturacom_api_key: str = ""
    facturacom_secret_key: str = ""
    facturacom_sandbox: bool = True
    emisor_razon_social: str = ""
    emisor_rfc: str = ""
    emisor_regimen_fiscal: str = ""
    emisor_cp: str = ""
    email_smtp_host: str = ""
    email_smtp_port: str = "587"
    email_smtp_user: str = ""
    email_smtp_password: str = ""


@router.post("/facturacion")
def set_facturacion(body: FacturacionIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        updates = {
            "facturacom_api_key":    body.facturacom_api_key.strip(),
            "facturacom_secret_key": body.facturacom_secret_key.strip(),
            "facturacom_sandbox":    "1" if body.facturacom_sandbox else "0",
            "emisor_razon_social":   body.emisor_razon_social.strip(),
            "emisor_rfc":            body.emisor_rfc.strip().upper(),
            "emisor_regimen_fiscal": body.emisor_regimen_fiscal.strip(),
            "emisor_cp":             body.emisor_cp.strip(),
            "email_smtp_host":       body.email_smtp_host.strip(),
            "email_smtp_port":       body.email_smtp_port.strip() or "587",
            "email_smtp_user":       body.email_smtp_user.strip(),
            "email_smtp_password":   body.email_smtp_password.strip(),
        }
        # Si el campo llega vacío o con el prefijo de máscara, el usuario no lo tocó
        # (el front no reenvía el valor precargado si no cambió) — no sobreescribir
        # el secreto real guardado con un valor vacío o con la máscara.
        _secret_keys = ("facturacom_api_key", "facturacom_secret_key", "email_smtp_password")
        for clave in _secret_keys:
            if not updates[clave] or updates[clave].startswith(_MASK_PREFIX):
                del updates[clave]
        for clave, valor in updates.items():
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = valor
            else:
                db.add(Configuracion(clave=clave, valor=valor))
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ── Sucursal (nombre de sucursal y dirección para tickets y pantalla) ────────
# Todas las sucursales comparten nombre comercial y logo; lo que cambia es el
# nombre de la sucursal (ej. "13 de Abril", "López Mateos") y su dirección.
# Cada sucursal tiene su propia BD, así que estos datos viven en su tabla
# configuracion y se sincronizan entre las cajas de ESA sucursal. La clave la
# fija setup.json de cada PC (cfg.SUCURSAL_CLAVE) y no se edita desde aquí.
_SUCURSAL_CAMPOS = {
    "sucursal_nombre":    "nombre_sucursal",
    "farmacia_nombre":    "nombre_farmacia",
    "farmacia_direccion": "direccion",
    "farmacia_telefono":  "telefono",
}


def _leer_sucursal(db) -> dict:
    from app.database.models import Configuracion
    filas = {c.clave: c.valor for c in db.query(Configuracion).filter(
        Configuracion.clave.in_(list(_SUCURSAL_CAMPOS)))}
    out = {campo: (filas.get(clave) or "") for clave, campo in _SUCURSAL_CAMPOS.items()}
    out["nombre_farmacia"] = out["nombre_farmacia"] or cfg.PHARMACY_NAME
    out["clave"] = cfg.SUCURSAL_CLAVE
    return out


@router.get("/sucursal")
def get_sucursal():
    """Público (sin login): la pantalla de inicio de sesión muestra el nombre y
    logo de la sucursal. No contiene nada sensible."""
    from app.database.connection import get_db_session
    db = get_db_session()
    try:
        return _leer_sucursal(db)
    finally:
        db.close()


class SucursalIn(BaseModel):
    nombre_sucursal: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None


@router.post("/sucursal")
def set_sucursal(body: SucursalIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        datos = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        for clave, campo in _SUCURSAL_CAMPOS.items():
            val = datos.get(campo)
            if val is None or campo == "nombre_farmacia":  # nombre comercial: igual en todas
                continue
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = val.strip()
            else:
                db.add(Configuracion(clave=clave, valor=val.strip()))
        db.commit()
        return {"ok": True, **_leer_sucursal(db)}
    finally:
        db.close()
