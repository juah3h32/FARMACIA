from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database.connection import get_db_session
from app.database.models import Promocion
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(p):
    if p.get("rol") != "admin":
        raise HTTPException(403, "Solo administradores")


class PromocionIn(BaseModel):
    nombre: str
    tipo: str
    valor: float = 0.0
    aplica_a: str = "todos"
    aplica_id: Optional[int] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    activo: bool = True


def _promo_dict(p):
    return {
        "id": p.id,
        "nombre": p.nombre,
        "tipo": p.tipo.value if hasattr(p.tipo, "value") else p.tipo,
        "valor": p.valor,
        "aplica_a": p.aplica_a,
        "aplica_id": p.aplica_id,
        "fecha_inicio": p.fecha_inicio.isoformat() if p.fecha_inicio else None,
        "fecha_fin": p.fecha_fin.isoformat() if p.fecha_fin else None,
        "activo": p.activo,
        "activa": p.activo,
        "creado_en": p.creado_en.isoformat() if p.creado_en else None,
    }


@router.get("")
def listar_promociones(activas_only: bool = False, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        q = db.query(Promocion)
        if activas_only:
            today = date.today()
            q = q.filter(
                Promocion.activo == True,
                (Promocion.fecha_inicio == None) | (Promocion.fecha_inicio <= today),
                (Promocion.fecha_fin == None) | (Promocion.fecha_fin >= today),
            )
        return [_promo_dict(p) for p in q.order_by(Promocion.creado_en.desc()).all()]
    finally:
        db.close()


@router.post("")
def crear_promocion(body: PromocionIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = Promocion(**body.model_dump())
        db.add(p)
        db.commit()
        db.refresh(p)
        return _promo_dict(p)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.put("/{pid}")
def actualizar_promocion(pid: int, body: PromocionIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Promocion).filter(Promocion.id == pid).first()
        if not p:
            raise HTTPException(404, "No encontrada")
        for k, v in body.model_dump().items():
            setattr(p, k, v)
        db.commit()
        return _promo_dict(p)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.patch("/{pid}/toggle")
def toggle_promocion(pid: int, activa: bool, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Promocion).filter(Promocion.id == pid).first()
        if not p:
            raise HTTPException(404, "No encontrada")
        p.activo = activa
        db.commit()
        return _promo_dict(p)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.delete("/{pid}")
def eliminar_promocion(pid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Promocion).filter(Promocion.id == pid).first()
        if not p:
            raise HTTPException(404, "No encontrada")
        db.delete(p)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            bg.add_task(delete_ids_from_turso, "promociones", [pid])
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/calcular")
def calcular_promo(
    producto_id: int,
    categoria_id: Optional[int] = None,
    cantidad: int = 1,
    payload: dict = Depends(get_current_api_user),
):
    """Devuelve promociones aplicables a un producto dado."""
    db = get_db_session()
    try:
        today = date.today()
        promos = db.query(Promocion).filter(
            Promocion.activo == True,
            (Promocion.fecha_inicio == None) | (Promocion.fecha_inicio <= today),
            (Promocion.fecha_fin == None) | (Promocion.fecha_fin >= today),
        ).all()
        aplicables = []
        for p in promos:
            if p.aplica_a == "todos":
                aplicables.append(p)
            elif p.aplica_a == "producto" and p.aplica_id == producto_id:
                aplicables.append(p)
            elif p.aplica_a == "categoria" and p.aplica_id == categoria_id:
                aplicables.append(p)
        return [_promo_dict(p) for p in aplicables]
    finally:
        db.close()
