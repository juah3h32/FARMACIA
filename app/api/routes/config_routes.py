from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
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
}


@router.get("/integraciones")
def get_integraciones(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    out = {"on_vercel": bool(cfg._ON_VERCEL)}
    for field, (attr, _filename, is_secret) in _INTEGRACIONES_MAP.items():
        val = getattr(cfg, attr, "") or ""
        out[field] = _mask(val) if is_secret else val
    return out


class IntegracionesIn(BaseModel):
    turso_database_url: str = ""
    turso_auth_token: str = ""
    openai_api_key: str = ""
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""


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
    return {
        "ok": True,
        "restart_required": changed_turso,  # el engine de Turso se arma al iniciar
    }


# ── Mercado Pago Point ────────────────────────────────────────────────────────

class MpSaveIn(BaseModel):
    token: str
    device_id: Optional[str] = ""


@router.get("/mp-status")
def mp_status(payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    device_id = mp_point.device_id
    # Device IDs reales de MP son alfanuméricos (NEWLAND_ME30SU__...). Solo dígitos = inválido.
    valid_device = bool(device_id and len(device_id) > 8 and not device_id.isdigit())
    return {
        "enabled":   mp_point.enabled and valid_device,
        "token_set": bool(mp_point.access_token),
        "device_id": device_id if valid_device else "",
    }


@router.post("/mp-save")
def mp_save(body: MpSaveIn, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    token  = body.token.strip()
    device = body.device_id.strip() if body.device_id else ""
    if not token:
        raise HTTPException(status_code=400, detail="Access Token requerido")
    (cfg.DATA_DIR / "mp_access_token.key").write_text(token, encoding="utf-8")
    # Solo guarda device_id si tiene formato válido (alfanumérico, no solo dígitos)
    valid_device = bool(device and len(device) > 8 and not device.isdigit())
    if valid_device:
        (cfg.DATA_DIR / "mp_device_id.key").write_text(device, encoding="utf-8")
    elif not device:
        # Limpiar archivo si se guardó sin device_id
        kf = cfg.DATA_DIR / "mp_device_id.key"
        if kf.exists():
            kf.unlink()
    cfg.MP_ACCESS_TOKEN = token
    cfg.MP_DEVICE_ID    = device if valid_device else ""
    from app.services.mercadopago_service import mp_point
    mp_point.configure(token, cfg.MP_DEVICE_ID)
    return {"ok": True, "enabled": mp_point.enabled and valid_device}


@router.get("/mp-devices")
def mp_devices(token: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point, MercadoPagoPointService
    import requests as _req
    # Usa token del query param (temporal, sin guardar) o el configurado
    use_token = (token or "").strip() or mp_point.access_token
    if not use_token:
        raise HTTPException(status_code=400, detail="Access Token no configurado")
    try:
        headers = {"Authorization": f"Bearer {use_token}", "Content-Type": "application/json"}
        r = _req.get("https://api.mercadopago.com/point/integration-api/devices", headers=headers, timeout=10)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Token inválido o sin permisos de Point")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail="La cuenta no tiene acceso a la API de Point. Activa la integración en developers.mercadopago.com")
        r.raise_for_status()
        data = r.json()
        devices = data.get("devices", [])
        return {"devices": devices}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error MP API: {e}")


class MpPdvIn(BaseModel):
    token: Optional[str] = ""
    device_id: Optional[str] = ""


_MP_ERRORS = {
    "111": "Acción no soportada por la terminal",
    "112": "Terminal no configurada para integración. Enciende la terminal, conéctala a WiFi y vuelve a intentarlo.",
    "113": "Terminal no permite esta acción ahora. Asegúrate de que esté ENCENDIDA y conectada a WiFi/datos.",
}


@router.post("/mp-pdv")
def mp_set_pdv(body: MpPdvIn = MpPdvIn(), payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    import requests as _req
    from app.services.mercadopago_service import mp_point
    token     = (body.token or "").strip() or mp_point.access_token
    device_id = (body.device_id or "").strip() or mp_point.device_id
    if not token or not device_id:
        raise HTTPException(status_code=400, detail="Guarda el Access Token y Device ID primero, luego activa PDV")
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = _req.patch(
            f"https://api.mercadopago.com/point/integration-api/devices/{device_id}",
            headers=headers, json={"operating_mode": "PDV"}, timeout=15,
        )
        if r.status_code == 200:
            mp_point.configure(token, device_id)
            return {"ok": True}
        data = r.json()
        mp_error = str(data.get("error", ""))
        friendly = _MP_ERRORS.get(mp_error, data.get("message", "Error desconocido"))
        raise HTTPException(status_code=502, detail=friendly)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error de red: {e}")


# ── MP Payment Intent (usado por processSale en webview) ─────────────────────

@router.post("/mp-intent")
def mp_create_intent(body: dict, payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    if not mp_point.enabled:
        raise HTTPException(status_code=400, detail="Terminal MP no configurada")
    amount    = float(body.get("amount", 0))
    reference = str(body.get("reference", ""))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Monto inválido")
    mp_point.cancel_current_intent()
    try:
        intent = mp_point.create_payment_intent(amount, reference)
        return {"intent_id": intent.get("id"), "state": intent.get("state")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error creando intent: {e}")


@router.get("/mp-intent/{intent_id}")
def mp_get_intent(intent_id: str, payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    if not mp_point.access_token:
        raise HTTPException(status_code=400, detail="Token MP no configurado")
    try:
        data = mp_point.get_payment_intent(intent_id)
        return {
            "state":       data.get("state"),
            "payment":     data.get("payment", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error consultando intent: {e}")


@router.delete("/mp-intent")
def mp_cancel_intent(payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    mp_point.cancel_current_intent()
    return {"ok": True}


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
