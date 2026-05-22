from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.exc import IntegrityError
from app.database.connection import get_db_session
from app.database.models import Usuario, RolUsuario
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
def listar_empleados(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        rows = db.query(Usuario).filter(Usuario.activo == True).order_by(Usuario.nombre).all()
        return [
            {"id": u.id, "username": u.username, "nombre": u.nombre,
             "rol": u.rol.value, "telefono": u.telefono, "email": u.email}
            for u in rows
        ]
    finally:
        db.close()


@router.post("/")
def crear_empleado(body: EmpleadoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not body.password or len(body.password) < 4:
        raise HTTPException(status_code=400, detail="Contraseña requerida (mínimo 4 caracteres)")
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
        if body.password:
            if len(body.password) < 4:
                raise HTTPException(status_code=400, detail="Contraseña mínimo 4 caracteres")
            u.password_hash = hash_password(body.password)
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
