import sys
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.config as cfg
from app.api.routes.auth_routes import get_current_api_user
from app.auth.auth_service import create_long_token

router = APIRouter()

# ── Update state (shared across requests) ─────────────────────────────────────
_update_state: dict = {"running": False, "progress": 0.0, "error": None, "done": False}


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class TokenRequest(BaseModel):
    nombre: str = "Mi Token API"
    dias: int = 365


@router.post("/generate-token")
def generate_api_token(body: TokenRequest, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not 1 <= body.dias <= 3650:
        raise HTTPException(status_code=400, detail="Días debe estar entre 1 y 3650")
    token = create_long_token(
        user_id=int(payload["sub"]),
        username=payload["username"],
        nombre=payload.get("nombre", ""),
        rol=payload.get("rol", "admin"),
        days=body.dias,
        token_name=body.nombre,
    )
    expires_at = (datetime.utcnow() + timedelta(days=body.dias)).strftime("%Y-%m-%d")
    return {
        "token": token,
        "nombre": body.nombre,
        "expires_at": expires_at,
        "dias": body.dias,
    }


@router.get("/update/check")
def check_update(payload: dict = Depends(get_current_api_user)):
    from app.services import updater_service
    st = updater_service.get_status()
    if not st["checked"]:
        st = updater_service.force_check()
    return {
        "available": bool(st["available"]),
        "latest_version": st["version"] or "",
        "current_version": cfg.VERSION,
        "has_download": st["url"] is not None,
    }


@router.post("/update/install")
def install_update(payload: dict = Depends(get_current_api_user)):
    if _update_state["running"]:
        raise HTTPException(status_code=409, detail="Instalación en progreso")
    if not getattr(sys, "frozen", False):
        raise HTTPException(status_code=400, detail="Solo disponible en EXE instalado")

    _update_state.update({"running": True, "progress": 0.0, "error": None, "done": False})

    def _run():
        from app.services import updater_service
        def on_progress(pct):
            _update_state["progress"] = pct
        ok, err = updater_service.download_and_install(on_progress)
        if ok:
            _update_state.update({"progress": 1.0, "done": True, "running": False})
            import time
            time.sleep(1.5)
            sys.exit(0)
        else:
            _update_state.update({"error": err, "running": False})

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.get("/update/progress")
def update_progress(payload: dict = Depends(get_current_api_user)):
    return dict(_update_state)


@router.get("/endpoints")
def list_endpoints(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    return [
        {"method": "POST", "path": "/api/auth/login",        "desc": "Obtener token de sesión"},
        {"method": "GET",  "path": "/api/auth/me",           "desc": "Información del usuario actual"},
        {"method": "GET",  "path": "/api/productos/",        "desc": "Listar productos activos"},
        {"method": "POST", "path": "/api/productos/",        "desc": "Crear producto"},
        {"method": "PUT",  "path": "/api/productos/{id}",    "desc": "Actualizar producto"},
        {"method": "DELETE","path":"/api/productos/{id}",    "desc": "Eliminar producto (soft)"},
        {"method": "GET",  "path": "/api/productos/categorias","desc": "Listar categorías"},
        {"method": "GET",  "path": "/api/ventas/",           "desc": "Listar ventas con filtros"},
        {"method": "GET",  "path": "/api/ventas/resumen",    "desc": "Resumen cobros del día"},
        {"method": "POST", "path": "/api/pos/",              "desc": "Registrar nueva venta"},
        {"method": "GET",  "path": "/api/clientes/",         "desc": "Listar clientes"},
        {"method": "POST", "path": "/api/clientes/",         "desc": "Crear cliente"},
        {"method": "PUT",  "path": "/api/clientes/{id}",     "desc": "Actualizar cliente"},
        {"method": "DELETE","path":"/api/clientes/{id}",     "desc": "Eliminar cliente"},
        {"method": "GET",  "path": "/api/empleados/",        "desc": "Listar empleados (admin)"},
        {"method": "POST", "path": "/api/empleados/",        "desc": "Crear empleado (admin)"},
        {"method": "GET",  "path": "/api/dashboard/stats",   "desc": "Estadísticas del dashboard"},
        {"method": "POST", "path": "/api/admin/generate-token","desc": "Generar token API (admin)"},
    ]
