import os
import sys
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
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
    expires_at = (datetime.now() + timedelta(days=body.dias)).strftime("%Y-%m-%d")
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
    _require_admin(payload)
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
                # Give the frontend 4 seconds to see "✓ Instalando..." before we exit.
                # The installer is already launched at this point; os._exit kills Python
                # cleanly so the installer can overwrite EXE files without conflict.
                time.sleep(4.0)
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
def update_progress():
    # No auth required — only exposes download progress, no sensitive data.
    # Avoids forced logout when the API restarts mid-update and the old token
    # would otherwise trigger a 401 → doLogout() in the frontend.
    return dict(_update_state)


@router.post("/update/cancel")
def cancel_update(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
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
def purgar_datos(body: PurgarHistorialIn, payload: dict = Depends(get_current_api_user)):
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
    from app.database.sync_service import purgar_todos_los_datos
    purgar_todos_los_datos()
    return {"ok": True}


@router.post("/factory-reset")
def factory_reset_endpoint(body: PurgarHistorialIn, payload: dict = Depends(get_current_api_user)):
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
    from app.database.sync_service import factory_reset
    factory_reset()
    return {"ok": True}


@router.post("/normalizar-nombres")
def normalizar_nombres(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Uppercase nombre, nombre_generico and marca for all active products."""
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    try:
        prods = db.query(Producto).filter(Producto.activo == True).all()
        updated = 0
        for p in prods:
            changed = False
            if p.nombre and p.nombre != p.nombre.upper():
                p.nombre = p.nombre.strip().upper()
                changed = True
            if p.nombre_generico and p.nombre_generico != p.nombre_generico.upper():
                p.nombre_generico = p.nombre_generico.strip().upper()
                changed = True
            if p.marca and p.marca != p.marca.upper():
                p.marca = p.marca.strip().upper()
                changed = True
            if changed:
                updated += 1
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC and updated > 0:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "actualizados": updated, "total": len(prods)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


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
    err = stats.pop("_error", None)
    if err:
        return {"ok": False, "error": err, "stats": stats}
    return {"ok": True, "stats": stats}


@router.get("/turso-diagnostico")
def turso_diagnostico(payload: dict = Depends(get_current_api_user)):
    """Compare local SQLite row counts vs Turso for key tables."""
    _require_admin(payload)
    from app.database.sync_service import get_db_stats, _turso_read_table
    local_stats = get_db_stats()
    turso_stats = {}
    for tabla in ("ventas", "cortes_caja", "items_venta", "retiros_caja"):
        try:
            cols, rows = _turso_read_table(tabla)
            turso_stats[tabla] = len(rows)
        except Exception as e:
            turso_stats[tabla] = f"error: {e}"
    diff = {}
    for t in turso_stats:
        l = local_stats.get(t, 0)
        r = turso_stats[t]
        if isinstance(l, int) and isinstance(r, int):
            diff[t] = {"local": l, "turso": r, "diferencia": r - l}
        else:
            diff[t] = {"local": l, "turso": r, "diferencia": "?"}
    return {"ok": True, "tablas": diff, "turso_sync_activo": cfg.TURSO_SYNC}


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


class TurnoConfigIn(BaseModel):
    turno_auto_activo: str = "true"   # "true" | "false"
    turno_auto_inicio: str = "09:00"  # "HH:MM"
    turno_auto_fin:    str = "10:00"  # "HH:MM"


_TURNO_CFG_KEYS = {"turno_auto_activo", "turno_auto_inicio", "turno_auto_fin"}


@router.get("/config")
def get_config(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        rows = db.query(Configuracion).filter(
            Configuracion.clave.in_(_TURNO_CFG_KEYS)
        ).all()
        return {r.clave: r.valor for r in rows}
    finally:
        db.close()


@router.post("/config")
def set_config(body: TurnoConfigIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        updates = {
            "turno_auto_activo": body.turno_auto_activo,
            "turno_auto_inicio": body.turno_auto_inicio,
            "turno_auto_fin":    body.turno_auto_fin,
        }
        for clave, valor in updates.items():
            row = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if row:
                row.valor = valor
            else:
                db.add(Configuracion(clave=clave, valor=valor))
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


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
    content = await file.read()
    if len(content) > 100_000_000:  # 100 MB max
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx 100 MB)")
    # Write to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
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


# ── Estado de integraciones (campana de notificaciones) ─────────────────────

def _check_turso() -> dict:
    if not (cfg.USE_TURSO or cfg.TURSO_SYNC):
        return {"ok": True, "enabled": False, "message": "Sincronización con Turso desactivada (modo local)."}
    try:
        from app.database.sync_service import _turso_pipeline_url, _turso_headers
        import requests as _req
        url, hdrs = _turso_pipeline_url(), _turso_headers()
        payload = {"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1", "args": []}}, {"type": "close"}]}
        r = _req.post(url, headers=hdrs, json=payload, timeout=6)
        if not r.ok:
            return {"ok": False, "enabled": True, "message": f"Turso respondió HTTP {r.status_code}."}
        data = r.json()
        first = (data.get("results") or [{}])[0]
        if first.get("type") == "error":
            msg = first.get("error", {}).get("message", "error desconocido")
            return {"ok": False, "enabled": True, "message": f"Turso: {msg}"}
        return {"ok": True, "enabled": True, "message": "Conectado."}
    except Exception as e:
        return {"ok": False, "enabled": True, "message": f"Sin conexión con Turso: {e}"}


def _check_facturacom() -> dict:
    from app.database.connection import get_db_session
    from app.database.models import Configuracion
    db = get_db_session()
    try:
        rows = db.query(Configuracion).filter(
            Configuracion.clave.in_(["facturacom_api_key", "facturacom_secret_key", "facturacom_sandbox"])
        ).all()
        d = {r.clave: r.valor for r in rows}
        api_key = d.get("facturacom_api_key", "")
        secret_key = d.get("facturacom_secret_key", "")
        sandbox = d.get("facturacom_sandbox", "1") == "1"
        if not api_key or not secret_key:
            return {"ok": True, "enabled": False, "message": "Factura.com no está configurado."}
        from app.services.facturacom_service import _serie_id_factura, FacturaComError
        try:
            _serie_id_factura(api_key, secret_key, sandbox)
            return {"ok": True, "enabled": True, "message": "Conectado y credenciales válidas."}
        except FacturaComError as e:
            return {"ok": False, "enabled": True, "message": str(e)}
    except Exception as e:
        return {"ok": False, "enabled": True, "message": f"Error al verificar Factura.com: {e}"}
    finally:
        db.close()


def _check_openai() -> dict:
    if not cfg.OPENAI_API_KEY:
        return {"ok": True, "enabled": False, "message": "OpenAI no está configurado."}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=cfg.OPENAI_API_KEY, timeout=6.0)
        client.models.retrieve("gpt-4o-mini")
        return {"ok": True, "enabled": True, "message": "Conectado."}
    except Exception as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower() or "billing" in msg.lower():
            return {"ok": False, "enabled": True, "message": "Sin créditos en OpenAI (revisa billing)."}
        if "401" in msg or "invalid_api_key" in msg.lower() or "incorrect api key" in msg.lower():
            return {"ok": False, "enabled": True, "message": "API key de OpenAI inválida."}
        return {"ok": False, "enabled": True, "message": f"Sin conexión con OpenAI: {msg[:150]}"}


@router.get("/integrations-status")
def integrations_status(payload: dict = Depends(get_current_api_user)):
    """Prueba en vivo la conexión a Turso, Factura.com y OpenAI — usado por la
    campana de notificaciones del header para avisar si alguna integración cayó."""
    _require_admin(payload)
    from concurrent.futures import ThreadPoolExecutor

    checks = {"turso": _check_turso, "facturacom": _check_facturacom, "openai": _check_openai}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = dict(zip(checks.keys(), pool.map(lambda f: f(), checks.values())))

    labels = {
        "turso": "Turso (Base de datos)",
        "facturacom": "Factura.com (CFDI)",
        "openai": "OpenAI (Farmacito / IA)",
    }
    integrations = [
        {"key": k, "label": labels[k], **v} for k, v in results.items()
    ]
    any_down = any((not it["ok"]) and it["enabled"] for it in integrations)

    # Guarda en el historial solo cuando el estado CAMBIA respecto al último
    # registro — si no, cada chequeo (uno cada 2 min) llenaría la tabla de filas
    # repetidas de "todo bien" sin aportar nada al historial.
    try:
        from app.database.connection import get_db_session
        from app.database.models import IntegracionLog
        db = get_db_session()
        try:
            for it in integrations:
                if not it["enabled"]:
                    continue
                ultimo = (
                    db.query(IntegracionLog)
                    .filter(IntegracionLog.origen == it["key"])
                    .order_by(IntegracionLog.id.desc())
                    .first()
                )
                if ultimo is None or ultimo.ok != it["ok"]:
                    db.add(IntegracionLog(origen=it["key"], ok=it["ok"], mensaje=it["message"]))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # el historial nunca debe romper el chequeo de estado en vivo

    return {
        "checked_at": datetime.now().isoformat(),
        "integrations": integrations,
        "any_down": any_down,
    }


@router.get("/integrations-log")
def integrations_log(limit: int = 100, payload: dict = Depends(get_current_api_user)):
    """Historial de cambios de estado de integraciones — para ver qué falló y cuándo."""
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import IntegracionLog
    db = get_db_session()
    try:
        rows = (
            db.query(IntegracionLog)
            .order_by(IntegracionLog.id.desc())
            .limit(min(limit, 500))
            .all()
        )
        labels = {
            "turso": "Turso (Base de datos)",
            "facturacom": "Factura.com (CFDI)",
            "openai": "OpenAI (Farmacito / IA)",
        }
        return {
            "logs": [
                {
                    "id": r.id,
                    "origen": r.origen,
                    "label": labels.get(r.origen, r.origen),
                    "ok": r.ok,
                    "mensaje": r.mensaje,
                    "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                }
                for r in rows
            ]
        }
    finally:
        db.close()
