from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Proveedor, Producto
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _sync_bg(bg: BackgroundTasks):
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        from app.database.sync_service import sync_to_turso
        bg.add_task(sync_to_turso)


class ProveedorIn(BaseModel):
    nombre: str
    contacto: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    rfc: Optional[str] = None


def _fmt(p: Proveedor) -> dict:
    return {
        "id": p.id, "nombre": p.nombre, "contacto": p.contacto,
        "telefono": p.telefono, "email": p.email,
        "direccion": p.direccion, "rfc": p.rfc, "activo": p.activo,
    }


@router.get("/")
def listar_proveedores(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        rows = db.query(Proveedor).filter(Proveedor.activo == True).order_by(Proveedor.nombre).all()
        return [_fmt(p) for p in rows]
    finally:
        db.close()


@router.post("/")
def crear_proveedor(body: ProveedorIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not body.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre es requerido")
    db = get_db_session()
    try:
        p = Proveedor(
            nombre=body.nombre.strip().upper(),
            contacto=body.contacto, telefono=body.telefono,
            email=body.email, direccion=body.direccion, rfc=body.rfc,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        _sync_bg(bg)
        return _fmt(p)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/{pid}")
def actualizar_proveedor(pid: int, body: ProveedorIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Proveedor).filter(Proveedor.id == pid).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        p.nombre    = body.nombre.strip().upper()
        p.contacto  = body.contacto
        p.telefono  = body.telefono
        p.email     = body.email
        p.direccion = body.direccion
        p.rfc       = body.rfc
        db.commit()
        _sync_bg(bg)
        return _fmt(p)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{pid}")
def eliminar_proveedor(pid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Proveedor).filter(Proveedor.id == pid).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        p.activo = False
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


class AsignarProveedorIn(BaseModel):
    producto_ids: list[int]


@router.post("/{pid}/asignar-productos")
def asignar_productos(pid: int, body: AsignarProveedorIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        prov = db.query(Proveedor).filter(Proveedor.id == pid, Proveedor.activo == True).first()
        if not prov:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        updated = (
            db.query(Producto)
            .filter(Producto.id.in_(body.producto_ids), Producto.activo == True)
            .update({"proveedor_id": pid}, synchronize_session=False)
        )
        db.commit()
        _sync_bg(bg)
        return {"ok": True, "actualizados": updated}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{pid}/asignar-todos")
def asignar_todos(pid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        prov = db.query(Proveedor).filter(Proveedor.id == pid, Proveedor.activo == True).first()
        if not prov:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        updated = db.query(Producto).filter(Producto.activo == True).update(
            {"proveedor_id": pid}, synchronize_session=False
        )
        db.commit()
        _sync_bg(bg)
        return {"ok": True, "actualizados": updated}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
