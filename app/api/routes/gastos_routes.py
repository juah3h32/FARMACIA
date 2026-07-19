from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

from app.database.connection import get_db_session
from app.database.models import Gasto, CategoriaGasto
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class GastoIn(BaseModel):
    concepto: str
    monto: float
    categoria: str = "otros"
    fecha: date
    notas: Optional[str] = None


@router.get("")
def listar_gastos(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    categoria: Optional[str] = Query(None),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        q = db.query(Gasto)
        if fecha_inicio:
            q = q.filter(Gasto.fecha >= fecha_inicio)
        if fecha_fin:
            q = q.filter(Gasto.fecha <= fecha_fin)
        if categoria:
            q = q.filter(Gasto.categoria == categoria)
        gastos = q.order_by(Gasto.fecha.desc(), Gasto.creado_en.desc()).all()
        return [
            {
                "id": g.id,
                "concepto": g.concepto,
                "monto": g.monto,
                "categoria": g.categoria.value if g.categoria else "otros",
                "fecha": g.fecha.isoformat() if g.fecha else None,
                "notas": g.notas or "",
                "cajero": g.usuario.nombre if g.usuario else "",
                "creado_en": g.creado_en.isoformat() if g.creado_en else None,
            }
            for g in gastos
        ]
    finally:
        db.close()


@router.post("")
def crear_gasto(body: GastoIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if body.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")
    db = get_db_session()
    try:
        cat = CategoriaGasto(body.categoria) if body.categoria in CategoriaGasto.__members__ else CategoriaGasto.otros
        g = Gasto(
            concepto=body.concepto.strip(),
            monto=body.monto,
            categoria=cat,
            fecha=body.fecha,
            notas=body.notas,
            usuario_id=int(payload["sub"]) if payload.get("sub") else None,
        )
        db.add(g)
        db.commit()
        db.refresh(g)
        return {"ok": True, "id": g.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{gid}")
def eliminar_gasto(gid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        g = db.query(Gasto).filter(Gasto.id == gid).first()
        if not g:
            raise HTTPException(status_code=404, detail="No encontrado")
        db.delete(g)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            bg.add_task(delete_ids_from_turso, "gastos", [gid])
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/resumen")
def resumen_gastos(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        gastos = db.query(Gasto).filter(
            Gasto.fecha >= fecha_inicio,
            Gasto.fecha <= fecha_fin,
        ).all()
        total = sum(g.monto for g in gastos)
        por_categoria: dict = {}
        for g in gastos:
            cat = g.categoria.value if g.categoria else "otros"
            por_categoria[cat] = por_categoria.get(cat, 0.0) + g.monto
        return {
            "total": total,
            "num_gastos": len(gastos),
            "por_categoria": [{"categoria": k, "total": v} for k, v in sorted(por_categoria.items(), key=lambda x: -x[1])],
        }
    finally:
        db.close()
