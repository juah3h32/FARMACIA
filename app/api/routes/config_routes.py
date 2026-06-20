from fastapi import APIRouter, Depends, HTTPException
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
