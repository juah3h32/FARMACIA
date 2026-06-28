from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Cliente
from app.api.routes.auth_routes import get_current_api_user

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
def listar_clientes(
    q: Optional[str] = Query(None),
    payload: dict = Depends(get_current_api_user),
):
    db = get_db_session()
    try:
        query = db.query(Cliente).filter(Cliente.activo == True)
        if q:
            term = f"%{q.strip()}%"
            query = query.filter(
                Cliente.nombre.ilike(term) | Cliente.telefono.ilike(term)
            )
        rows = query.order_by(Cliente.nombre).all()
        return [
            {
                "id": c.id,
                "nombre": c.nombre,
                "telefono": c.telefono,
                "email": c.email,
                "rfc": c.rfc,
                "direccion": c.direccion,
                "puntos_acumulados": c.puntos_acumulados or 0,
                "puntos_canjeados": c.puntos_canjeados or 0,
            }
            for c in rows
        ]
    finally:
        db.close()


@router.post("/")
def crear_cliente(body: ClienteIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = Cliente(**body.model_dump())
        db.add(c)
        db.commit()
        db.refresh(c)
        return {"id": c.id, "nombre": c.nombre}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/{cid}")
def actualizar_cliente(cid: int, body: ClienteIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="No encontrado")
        for k, v in body.model_dump().items():
            setattr(c, k, v)
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{cid}")
def eliminar_cliente(cid: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="No encontrado")
        c.activo = False
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{cid}/puntos")
def puntos_cliente(cid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(status_code=404, detail="No encontrado")
        from app.database.models import Configuracion
        cfg = {
            r.clave: r.valor
            for r in db.query(Configuracion).filter(
                Configuracion.clave.in_(["pesos_por_punto", "valor_punto_en_pesos"])
            ).all()
        }
        pesos_por_punto = float(cfg.get("pesos_por_punto", "10"))
        valor_punto = float(cfg.get("valor_punto_en_pesos", "0.1"))
        disponibles = (c.puntos_acumulados or 0) - (c.puntos_canjeados or 0)
        return {
            "puntos_acumulados": c.puntos_acumulados or 0,
            "puntos_canjeados": c.puntos_canjeados or 0,
            "puntos_disponibles": disponibles,
            "valor_descuento": round(disponibles * valor_punto, 2),
            "pesos_por_punto": pesos_por_punto,
            "valor_punto_en_pesos": valor_punto,
        }
    finally:
        db.close()
