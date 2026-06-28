from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database.connection import get_db_session
from app.database.models import Receta
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


class RecetaIn(BaseModel):
    venta_id: Optional[int] = None
    medico_nombre: Optional[str] = None
    cedula: Optional[str] = None
    num_receta: Optional[str] = None
    fecha_receta: Optional[date] = None
    notas: Optional[str] = None


def _receta_dict(r):
    return {
        "id": r.id,
        "venta_id": r.venta_id,
        "medico_nombre": r.medico_nombre,
        "cedula": r.cedula,
        "num_receta": r.num_receta,
        "fecha_receta": r.fecha_receta.isoformat() if r.fecha_receta else None,
        "notas": r.notas,
        "creado_en": r.creado_en.isoformat() if r.creado_en else None,
    }


@router.post("")
def crear_receta(body: RecetaIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        r = Receta(**body.model_dump())
        db.add(r)
        db.commit()
        db.refresh(r)
        return _receta_dict(r)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/venta/{vid}")
def recetas_por_venta(vid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        recetas = db.query(Receta).filter(Receta.venta_id == vid).all()
        return [_receta_dict(r) for r in recetas]
    finally:
        db.close()


@router.get("")
def listar_recetas(q: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        query = db.query(Receta)
        if q:
            query = query.filter(
                Receta.medico_nombre.ilike(f"%{q}%") | Receta.num_receta.ilike(f"%{q}%")
            )
        return [_receta_dict(r) for r in query.order_by(Receta.creado_en.desc()).limit(100).all()]
    finally:
        db.close()
