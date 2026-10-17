from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import os, tempfile
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.database.connection import get_db_session
from app.database.models import Usuario, RolUsuario, Venta
from app.api.routes.auth_routes import get_current_api_user
from app.auth.auth_service import hash_password

router = APIRouter()


class EmpleadoIn(BaseModel):
    username: str
    nombre: str
    rol: str = "cajero"
    telefono: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


@router.get("/")
def listar_empleados(incluir_inactivos: bool = False, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        q = db.query(Usuario)
        if not incluir_inactivos:
            q = q.filter(Usuario.activo == True)
        else:
            # Un inactivo solo debe aparecer aqui si tiene ventas registradas
            # (para poder localizarlas/borrarlas) — cuentas de prueba dadas de
            # baja sin ninguna venta eran puro ruido en el selector.
            tiene_ventas = db.query(Venta.id).filter(Venta.usuario_id == Usuario.id).exists()
            q = q.filter(or_(Usuario.activo == True, tiene_ventas))
        rows = q.order_by(Usuario.nombre).all()
        return [
            {"id": u.id, "username": u.username, "nombre": u.nombre,
             "rol": u.rol.value, "telefono": u.telefono, "email": u.email,
             "foto_url": u.foto_url, "activo": u.activo}
            for u in rows
        ]
    finally:
        db.close()


@router.post("/")
def crear_empleado(body: EmpleadoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not body.password or len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Contraseña requerida (mínimo 8 caracteres)")
    db = get_db_session()
    try:
        try:
            rol = RolUsuario(body.rol)
        except ValueError:
            rol = RolUsuario.cajero
        u = Usuario(
            username=body.username,
            nombre=body.nombre,
            rol=rol,
            telefono=body.telefono,
            email=body.email,
            password_hash=hash_password(body.password),
            debe_cambiar_password=True,    # la pone el admin: el empleado la cambia al entrar
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"id": u.id, "nombre": u.nombre}
    except Exception as e:
        db.rollback()
        if 'UNIQUE' in str(e).upper():
            raise HTTPException(status_code=400, detail="El nombre de usuario ya existe, elige otro")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{uid}/codigo-acceso")
def generar_codigo_acceso_empleado(uid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """El admin genera un código de un solo uso (vence en 2 horas) para el empleado que olvidó
    su contraseña. El empleado lo escribe en "¿Olvidaste tu contraseña?" y elige una nueva."""
    _require_admin(payload)
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    from app.auth.auth_service import generar_codigo_acceso, normalizar_codigo
    db = get_db_session()
    try:
        u = db.query(Usuario).filter(Usuario.id == uid, Usuario.activo == True).first()
        if not u:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        codigo = generar_codigo_acceso()
        vence = _dt.now() + _td(hours=2)
        u.codigo_acceso = _json.dumps({"h": hash_password(normalizar_codigo(codigo)),
                                       "vence": vence.isoformat(timespec="seconds"), "intentos": 0})
        u.actualizado_en = _dt.now()
        db.commit()
        from app.database.models import AuditoriaLog
        db.add(AuditoriaLog(usuario_id=int(payload["sub"]), accion="CODIGO_ACCESO", tabla="usuarios",
                            registro_id=u.id, detalles=f"Código de acceso para {u.username} (vence {vence:%H:%M})"))
        db.commit()
        respuesta = {"codigo": codigo, "username": u.username, "nombre": u.nombre,
                     "vence": vence.strftime("%H:%M")}
    finally:
        db.close()
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        from app.database.sync_service import sync_to_turso
        bg.add_task(sync_to_turso)
    return respuesta


@router.put("/{uid}")
def actualizar_empleado(uid: int, body: EmpleadoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        u = db.query(Usuario).filter(Usuario.id == uid).first()
        if not u:
            raise HTTPException(status_code=404, detail="No encontrado")
        u.nombre = body.nombre
        u.telefono = body.telefono
        u.email = body.email
        try:
            u.rol = RolUsuario(body.rol)
        except ValueError:
            pass
        cambio_password = False
        if body.password:
            if len(body.password) < 8:
                raise HTTPException(status_code=400, detail="Contraseña mínimo 8 caracteres")
            u.password_hash = hash_password(body.password)
            # contraseña temporal puesta por el admin: cierra las sesiones abiertas de ese
            # empleado y le pide cambiarla al entrar (salvo que sea la cuenta del propio admin)
            u.token_version = (u.token_version or 0) + 1
            u.debe_cambiar_password = u.id != int(payload["sub"])
            cambio_password = True
        from datetime import datetime as _now
        u.actualizado_en = _now.now()
        db.commit()
        if cambio_password:
            from app.database.models import AuditoriaLog
            db.add(AuditoriaLog(usuario_id=int(payload["sub"]), accion="PASSWORD_ADMIN_RESET", tabla="usuarios",
                                registro_id=u.id, detalles=f"El admin cambió la contraseña de {u.username}"))
            db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{uid}/foto")
async def subir_foto_empleado(
    uid: int,
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_api_user),
):
    if int(payload["sub"]) != uid and payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Sin permiso")
    db = get_db_session()
    try:
        u = db.query(Usuario).filter(Usuario.id == uid).first()
        if not u:
            raise HTTPException(status_code=404, detail="No encontrado")
        suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            from app.services.cloudinary_service import upload_profile_photo
            url = await __import__("asyncio").to_thread(upload_profile_photo, tmp_path, uid)   # sin congelar el POS
            u.foto_url = url
            db.commit()
            import app.config as _cfg
            if _cfg.TURSO_SYNC:
                from app.database.sync_service import sync_to_turso
                bg.add_task(sync_to_turso)
            return {"foto_url": url}
        finally:
            os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{uid}/foto")
def eliminar_foto_empleado(uid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    if int(payload["sub"]) != uid and payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Sin permiso")
    db = get_db_session()
    try:
        u = db.query(Usuario).filter(Usuario.id == uid).first()
        if not u:
            raise HTTPException(status_code=404, detail="No encontrado")
        u.foto_url = None
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{uid}")
def eliminar_empleado(uid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if int(payload["sub"]) == uid:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    db = get_db_session()
    try:
        u = db.query(Usuario).filter(Usuario.id == uid).first()
        if not u:
            raise HTTPException(status_code=404, detail="No encontrado")
        u.activo = False
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
