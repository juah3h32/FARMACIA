from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import datetime
from app.database.connection import get_db_session
from app.database.models import (
    SesionInventario, ConteoInventario, Producto,
    MovimientoStock, TipoMovimiento, EstadoSesionInventario,
)
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(p):
    if p.get("rol") != "admin":
        raise HTTPException(403, "Solo administradores")


class ConteoIn(BaseModel):
    producto_id: int
    cantidad_contada: int


class ConteosBatchIn(BaseModel):
    conteos: List[ConteoIn]


def _sesion_dict(s, include_conteos=False):
    d = {
        "id": s.id,
        "estado": s.estado.value if hasattr(s.estado, "value") else s.estado,
        "notas": s.notas,
        "usuario_nombre": s.usuario.nombre if s.usuario else None,
        "creado_en": s.creado_en.isoformat() if s.creado_en else None,
        "finalizada_en": s.finalizada_en.isoformat() if s.finalizada_en else None,
        "total_productos": len(s.conteos) if s.conteos else 0,
        "con_diferencia": sum(1 for c in s.conteos if c.diferencia != 0) if s.conteos else 0,
    }
    if include_conteos:
        d["conteos"] = [
            {
                "id": c.id,
                "producto_id": c.producto_id,
                "producto_nombre": c.producto.nombre if c.producto else None,
                "producto_codigo": c.producto.codigo_barras if c.producto else None,
                "cantidad_sistema": c.cantidad_sistema,
                "cantidad_contada": c.cantidad_contada,
                "diferencia": c.diferencia,
                "ajustado": c.ajustado,
            }
            for c in s.conteos
        ]
    return d


@router.get("")
def listar_sesiones(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        sesiones = db.query(SesionInventario).order_by(SesionInventario.creado_en.desc()).limit(20).all()
        return [_sesion_dict(s) for s in sesiones]
    finally:
        db.close()


@router.post("")
def crear_sesion(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        activa = db.query(SesionInventario).filter(
            SesionInventario.estado == EstadoSesionInventario.en_progreso
        ).first()
        if activa:
            raise HTTPException(409, f"Ya hay una sesión en progreso (ID {activa.id})")
        sesion = SesionInventario(usuario_id=int(payload["sub"]))
        db.add(sesion)
        db.flush()
        productos = db.query(Producto).filter(Producto.activo == True).all()
        for p in productos:
            conteo = ConteoInventario(
                sesion_id=sesion.id,
                producto_id=p.id,
                cantidad_sistema=p.stock,
                cantidad_contada=None,
                diferencia=0,
            )
            db.add(conteo)
        db.commit()
        db.refresh(sesion)
        return _sesion_dict(sesion)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/{sid}")
def obtener_sesion(sid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        s = db.query(SesionInventario).filter(SesionInventario.id == sid).first()
        if not s:
            raise HTTPException(404, "Sesión no encontrada")
        return _sesion_dict(s, include_conteos=True)
    finally:
        db.close()


@router.post("/{sid}/conteos")
def registrar_conteos(sid: int, body: ConteosBatchIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        s = db.query(SesionInventario).filter(
            SesionInventario.id == sid,
            SesionInventario.estado == EstadoSesionInventario.en_progreso,
        ).first()
        if not s:
            raise HTTPException(404, "Sesión no encontrada o no está en progreso")
        for item in body.conteos:
            conteo = db.query(ConteoInventario).filter(
                ConteoInventario.sesion_id == sid,
                ConteoInventario.producto_id == item.producto_id,
            ).first()
            if conteo:
                conteo.cantidad_contada = item.cantidad_contada
                conteo.diferencia = item.cantidad_contada - conteo.cantidad_sistema
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.post("/{sid}/aplicar")
def aplicar_ajustes(sid: int, payload: dict = Depends(get_current_api_user)):
    """Aplica ajustes de inventario y cierra la sesión."""
    _require_admin(payload)
    db = get_db_session()
    try:
        s = db.query(SesionInventario).filter(
            SesionInventario.id == sid,
            SesionInventario.estado == EstadoSesionInventario.en_progreso,
        ).first()
        if not s:
            raise HTTPException(404, "Sesión no encontrada o no está en progreso")
        ajustados = 0
        for conteo in s.conteos:
            if conteo.cantidad_contada is not None and conteo.diferencia != 0 and not conteo.ajustado:
                prod = db.query(Producto).filter(Producto.id == conteo.producto_id).first()
                if prod:
                    mov = MovimientoStock(
                        producto_id=prod.id,
                        tipo=TipoMovimiento.ajuste,
                        cantidad=abs(conteo.diferencia),
                        stock_anterior=prod.stock,
                        stock_nuevo=conteo.cantidad_contada,
                        usuario_id=int(payload["sub"]),
                        notas=f"Ajuste inventario cíclico sesión #{sid}",
                    )
                    prod.stock = conteo.cantidad_contada
                    conteo.ajustado = True
                    db.add(mov)
                    ajustados += 1
        s.estado = EstadoSesionInventario.finalizada
        s.finalizada_en = datetime.now()
        db.commit()
        return {"ok": True, "ajustados": ajustados}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
