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


# ── Mercado Pago Point ────────────────────────────────────────────────────────

class MpSaveIn(BaseModel):
    token: str
    device_id: Optional[str] = ""


@router.get("/mp-status")
def mp_status(payload: dict = Depends(get_current_api_user)):
    from app.services.mercadopago_service import mp_point
    return {
        "enabled":   mp_point.enabled,
        "token_set": bool(mp_point.access_token),
        "device_id": mp_point.device_id,
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
    if device:
        (cfg.DATA_DIR / "mp_device_id.key").write_text(device, encoding="utf-8")
    cfg.MP_ACCESS_TOKEN = token
    cfg.MP_DEVICE_ID    = device
    from app.services.mercadopago_service import mp_point
    mp_point.configure(token, device)
    return {"ok": True, "enabled": mp_point.enabled}


@router.get("/mp-devices")
def mp_devices(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point
    if not mp_point.access_token:
        raise HTTPException(status_code=400, detail="Access Token no configurado")
    try:
        devices = mp_point.get_devices()
        return {"devices": devices}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error MP API: {e}")


@router.post("/mp-pdv")
def mp_set_pdv(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.mercadopago_service import mp_point
    if not mp_point.enabled:
        raise HTTPException(status_code=400, detail="Configura token y device_id primero")
    try:
        ok = mp_point.set_pdv_mode()
        if not ok:
            raise HTTPException(status_code=502, detail="Terminal no respondió correctamente")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error MP API: {e}")


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
