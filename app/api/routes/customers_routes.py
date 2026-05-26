from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Cliente
from app.api.routes.auth_routes import get_current_api_user


def _sync_bg(bg: BackgroundTasks):
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        from app.database.sync_service import sync_to_turso
        bg.add_task(sync_to_turso)

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class ClienteIn(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    rfc: Optional[str] = None
    direccion: Optional[str] = None


@router.get("/")
def listar_clientes(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        rows = db.query(Cliente).filter(Cliente.activo == True).order_by(Cliente.nombre).all()
        return [
            {"id": c.id, "nombre": c.nombre, "telefono": c.telefono,
             "email": c.email, "rfc": c.rfc, "direccion": c.direccion}
            for c in rows
        ]
    finally:
        db.close()


@router.post("/")
def crear_cliente(body: ClienteIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = Cliente(**body.model_dump())
        db.add(c)
        db.commit()
        db.refresh(c)
        _sync_bg(bg)
        return {"id": c.id, "nombre": c.nombre}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/{cid}")
def actualizar_cliente(cid: int, body: ClienteIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="No encontrado")
        for k, v in body.model_dump().items():
            setattr(c, k, v)
        db.commit()
        _sync_bg(bg)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{cid}")
def eliminar_cliente(cid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="No encontrado")
        c.activo = False
        db.commit()
        _sync_bg(bg)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
