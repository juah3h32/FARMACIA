from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Cliente, PagoCredito
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(p):
    if p.get("rol") != "admin":
        raise HTTPException(403, "Solo administradores")


class PagoIn(BaseModel):
    monto: float
    notas: Optional[str] = None


class CreditoIn(BaseModel):
    limite_credito: float


@router.get("/{cid}/credito")
def estado_credito(cid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid, Cliente.activo == True).first()
        if not c:
            raise HTTPException(404, "Cliente no encontrado")
        pagos = db.query(PagoCredito).filter(PagoCredito.cliente_id == cid).order_by(PagoCredito.creado_en.desc()).all()
        return {
            "limite_credito": c.limite_credito,
            "saldo_deuda": c.saldo_deuda,
            "disponible": max(0, c.limite_credito - c.saldo_deuda),
            "pagos": [{"id": p.id, "monto": p.monto, "notas": p.notas, "creado_en": p.creado_en.isoformat()} for p in pagos],
        }
    finally:
        db.close()


@router.post("/{cid}/credito/pago")
def registrar_pago(cid: int, body: PagoIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid, Cliente.activo == True).first()
        if not c:
            raise HTTPException(404, "Cliente no encontrado")
        if body.monto <= 0:
            raise HTTPException(400, "Monto debe ser mayor a 0")
        pago = PagoCredito(cliente_id=cid, monto=body.monto, notas=body.notas, usuario_id=int(payload["sub"]))
        c.saldo_deuda = max(0, c.saldo_deuda - body.monto)
        db.add(pago)
        db.commit()
        return {"ok": True, "saldo_deuda": c.saldo_deuda}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.put("/{cid}/credito/limite")
def actualizar_limite(cid: int, body: CreditoIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        c = db.query(Cliente).filter(Cliente.id == cid).first()
        if not c:
            raise HTTPException(404, "Cliente no encontrado")
        c.limite_credito = body.limite_credito
        db.commit()
        return {"ok": True, "limite_credito": c.limite_credito}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
