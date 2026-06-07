import os
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
    # Siempre consulta GitHub — no devolver caché viejo
    st = updater_service.force_check()
    return {
        "available": bool(st["available"]),
        "latest_version": st["version"] or "",
        "current_version": cfg.VERSION,
        "has_download": st["url"] is not None,
        "releases": st.get("releases", []),
    }


class InstallUpdateIn(BaseModel):
    version_url: str | None = None
    is_installer: bool | None = None


@router.post("/update/install")
def install_update(body: InstallUpdateIn | None = None, payload: dict = Depends(get_current_api_user)):
    if _update_state["running"]:
        raise HTTPException(status_code=409, detail="Instalación en progreso")
    if not getattr(sys, "frozen", False):
        raise HTTPException(status_code=400, detail="Solo disponible en EXE instalado")

    _update_state.update({"running": True, "progress": 0.0, "error": None, "done": False})

    def _run():
        from app.services import updater_service
        import time
        def on_progress(pct):
            _update_state["progress"] = pct
        
        vurl = body.version_url if body else None
        isin = body.is_installer if body else None
        
        max_retries = 10
        retry_count = 0
        last_err = ""

        while retry_count < max_retries:
            ok, err = updater_service.download_and_install(on_progress, version_url=vurl, is_installer=isin)
            if ok:
                _update_state.update({"progress": 1.0, "done": True, "running": False})
                time.sleep(2.0)
                os._exit(0)
                return
            else:
                last_err = err
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(5) # Wait before retry
                else:
                    _update_state.update({"error": f"Error tras {max_retries} reintentos: {last_err}", "running": False})

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.get("/update/progress")
def update_progress(payload: dict = Depends(get_current_api_user)):
    return dict(_update_state)


@router.post("/update/cancel")
def cancel_update(payload: dict = Depends(get_current_api_user)):
    from app.services import updater_service
    updater_service.cancel_download()
    _update_state.update({"running": False, "error": "Actualización cancelada", "done": False})
    return {"cancelled": True}


class PurgarHistorialIn(BaseModel):
    clave: str


@router.post("/purgar-historial")
def purgar_historial(body: PurgarHistorialIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    from app.auth.auth_service import verify_password
    db = get_db_session()
    try:
        cfg_row = db.query(Configuracion).filter(
            Configuracion.clave == "purge_password_hash"
        ).first()
        if not cfg_row or not verify_password(body.clave, cfg_row.valor):
            raise HTTPException(status_code=403, detail="Clave incorrecta")
    finally:
        db.close()
    from app.database.sync_service import purgar_ventas_historial_cierres
    purgar_ventas_historial_cierres()
    return {"ok": True}


@router.post("/purgar-datos")
def purgar_datos(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.sync_service import purgar_todos_los_datos
    purgar_todos_los_datos()
    return {"ok": True}


@router.post("/factory-reset")
def factory_reset_endpoint(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.sync_service import factory_reset
    factory_reset()
    return {"ok": True}


@router.get("/db-stats")
def db_stats(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.sync_service import get_db_stats
    return get_db_stats()


@router.post("/db-sync")
def db_sync(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.sync_service import force_sync
    stats = force_sync()
    return {"ok": True, "stats": stats}


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
        {"method": "GET",  "path": "/api/admin/db-stats",      "desc": "Conteo de filas por tabla (admin)"},
        {"method": "POST", "path": "/api/admin/db-sync",       "desc": "Forzar sync local → Turso (admin)"},
        {"method": "GET",  "path": "/api/admin/backup",         "desc": "Descargar respaldo de la BD (admin)"},
        {"method": "POST", "path": "/api/admin/restore",        "desc": "Restaurar BD desde archivo (admin)"},
    ]


class BackupPathIn(BaseModel):
    path: str


@router.post("/backup-to-path")
def backup_to_path(body: BackupPathIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    import shutil
    from pathlib import Path as _Path
    if not body.path:
        raise HTTPException(status_code=400, detail="Ruta vacía")
    dest = _Path(body.path)
    if not dest.parent.exists():
        raise HTTPException(status_code=400, detail="Carpeta de destino no existe")
    if not cfg.DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")
    shutil.copy2(str(cfg.DB_PATH), str(dest))
    return {"ok": True, "filename": dest.name}


@router.get("/backup")
def descargar_backup(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from fastapi.responses import FileResponse
    if not cfg.DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"farmacia_backup_{ts}.db"
    return FileResponse(
        path=str(cfg.DB_PATH),
        media_type="application/octet-stream",
        filename=filename,
    )


@router.post("/restore")
async def restaurar_backup(
    payload: dict = Depends(get_current_api_user),
):
    """Restore DB from uploaded .db file. Requires multipart form upload."""
    _require_admin(payload)
    from fastapi import UploadFile, File
    raise HTTPException(status_code=400, detail="Usa el endpoint /restore-upload con multipart/form-data")


from fastapi import UploadFile, File
import shutil, tempfile

@router.post("/restore-upload")
async def restaurar_backup_upload(
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    if not (file.filename or "").endswith(".db"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .db")
    # Read upload into temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    # Validate: check SQLite magic bytes
    with open(tmp_path, "rb") as f:
        magic = f.read(16)
    if not magic.startswith(b"SQLite format 3"):
        import os; os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail="El archivo no es una base de datos SQLite válida")
    # Backup current DB before replacing
    backup_path = cfg.DB_PATH.parent / f"farmacia_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    if cfg.DB_PATH.exists():
        shutil.copy2(str(cfg.DB_PATH), str(backup_path))
    shutil.move(tmp_path, str(cfg.DB_PATH))
    return {"ok": True, "mensaje": "Base de datos restaurada. Reinicia la aplicación para aplicar los cambios.", "backup_previo": backup_path.name}
