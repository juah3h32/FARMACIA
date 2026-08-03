import requests
import app.config as cfg
from app.services.cloudinary_service import _standardize_image_bytes, _STANDARD_SIZE


def removebg_configured() -> bool:
    return bool(cfg.REMOVEBG_API_KEY)


def quitar_fondo_bytes(raw: bytes) -> bytes:
    """Manda la imagen a remove.bg (fondo blanco, resource type 'photo') y
    regresa el resultado ya recortado/escalado al mismo cuadrado estándar que
    usa el resto del catálogo (ver _STANDARD_SIZE en cloudinary_service.py) —
    así una foto "arreglada" se ve igual de consistente que las demás."""
    if not cfg.REMOVEBG_API_KEY:
        raise RuntimeError("remove.bg no está configurado — agrega la API key en Configuración > Integraciones")
    try:
        resp = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": raw},
            data={"size": "auto", "bg_color": "FFFFFF", "format": "jpg"},
            headers={"X-Api-Key": cfg.REMOVEBG_API_KEY},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Sin conexión con remove.bg: {e}")
    if resp.status_code != 200:
        detail = resp.text[:200]
        try:
            errors = resp.json().get("errors", [])
            if errors:
                detail = errors[0].get("title", detail)
        except Exception:
            pass
        raise RuntimeError(detail)
    standardized = _standardize_image_bytes(resp.content, _STANDARD_SIZE["medicamentos"])
    return standardized if standardized is not None else resp.content


def check_account() -> dict:
    """Ping liviano a remove.bg — usado por /admin/integrations-status. Regresa
    créditos restantes, útil para avisar antes de que se acaben."""
    resp = requests.get(
        "https://api.remove.bg/v1.0/account",
        headers={"X-Api-Key": cfg.REMOVEBG_API_KEY},
        timeout=8,
    )
    if resp.status_code == 403:
        raise RuntimeError("API key de remove.bg inválida")
    resp.raise_for_status()
    attrs = resp.json().get("data", {}).get("attributes", {})
    credits = attrs.get("credits", {})
    return {"free_credits": credits.get("free"), "paid_credits": credits.get("subscription", credits.get("payg"))}
