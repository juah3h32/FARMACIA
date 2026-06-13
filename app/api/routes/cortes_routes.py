from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy import func
from app.database.connection import get_db_session
from app.database.models import CortesCaja, RetiroCaja, Venta, EstadoVenta, MetodoPago
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


class AbrirCorteIn(BaseModel):
    monto_apertura: float = 0.0
    notas: Optional[str] = None


class CerrarCorteIn(BaseModel):
    monto_cierre: float
    notas: Optional[str] = None


def _get_corte_activo(db, usuario_id: int) -> Optional[CortesCaja]:
    return (
        db.query(CortesCaja)
        .filter(CortesCaja.usuario_id == usuario_id, CortesCaja.cerrado_en == None)
        .order_by(CortesCaja.abierto_en.desc())
        .first()
    )


@router.get("/activo")
def corte_activo(payload: dict = Depends(get_current_api_user)):
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        c = _get_corte_activo(db, usuario_id)
        if not c:
            return {"abierto": False}
        # Calculate running totals from ventas since opening
        ventas = (
            db.query(Venta)
            .filter(
                Venta.usuario_id == usuario_id,
                Venta.creado_en >= c.abierto_en,
                Venta.estado == EstadoVenta.completada,
            )
            .all()
        )
        retiros = db.query(RetiroCaja).filter(RetiroCaja.corte_id == c.id).all()
        ef = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.efectivo)
        tj = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.tarjeta)
        tr = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.transferencia)
        tv = sum(v.total for v in ventas)
        total_retiros = sum(r.monto for r in retiros)
        return {
            "abierto":          True,
            "id":               c.id,
            "abierto_en":       c.abierto_en.isoformat(),
            "monto_apertura":   c.monto_apertura,
            "num_ventas":       len(ventas),
            "total_ventas":     tv,
            "total_efectivo":   ef,
            "total_tarjeta":    tj,
            "total_transferencia": tr,
            "total_retiros":    total_retiros,
            "esperado_caja":    c.monto_apertura + ef - total_retiros,
            "notas":            c.notas or "",
            "retiros": [
                {"id": r.id, "monto": r.monto, "concepto": r.concepto or "",
                 "creado_en": r.creado_en.isoformat() if r.creado_en else None}
                for r in retiros
            ],
        }
    finally:
        db.close()


@router.post("/abrir")
def abrir_corte(body: AbrirCorteIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        existente = _get_corte_activo(db, usuario_id)
        if existente:
            raise HTTPException(status_code=400, detail="Ya tienes un turno abierto")
        c = CortesCaja(
            usuario_id=usuario_id,
            monto_apertura=body.monto_apertura,
            notas=body.notas,
            abierto_en=datetime.now(),
        )
        db.add(c)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "id": c.id, "abierto_en": c.abierto_en.isoformat() if c.abierto_en else None}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/cerrar")
def cerrar_corte(body: CerrarCorteIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        c = _get_corte_activo(db, usuario_id)
        if not c:
            raise HTTPException(status_code=404, detail="No hay turno abierto")

        ventas = (
            db.query(Venta)
            .filter(
                Venta.usuario_id == usuario_id,
                Venta.creado_en >= c.abierto_en,
                Venta.estado == EstadoVenta.completada,
            )
            .all()
        )
        ef = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.efectivo)
        tj = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.tarjeta)
        tr = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.transferencia)
        tv = ef + tj + tr

        c.monto_cierre       = body.monto_cierre
        c.cerrado_en         = datetime.now()
        c.total_ventas       = tv
        c.total_efectivo     = ef
        c.total_tarjeta      = tj
        c.total_transferencia = tr
        c.num_ventas         = len(ventas)
        if body.notas:
            c.notas = body.notas

        apertura = c.monto_apertura  # cache before commit (object expires after commit)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        diferencia = body.monto_cierre - (apertura + ef)
        return {
            "ok":           True,
            "num_ventas":   len(ventas),
            "total_ventas": tv,
            "efectivo":     ef,
            "tarjeta":      tj,
            "transferencia": tr,
            "monto_apertura": apertura,
            "monto_cierre": body.monto_cierre,
            "esperado":     apertura + ef,
            "diferencia":   diferencia,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/historial")
def historial_cajero(
    limite: int = 20,
    payload: dict = Depends(get_current_api_user),
):
    limite = min(max(1, limite), 100)
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        cortes = (
            db.query(CortesCaja)
            .filter(CortesCaja.usuario_id == usuario_id)
            .order_by(CortesCaja.abierto_en.desc())
            .limit(limite)
            .all()
        )
        result = []
        for c in cortes:
            dur = None
            if c.cerrado_en and c.abierto_en:
                dur = int((c.cerrado_en - c.abierto_en).total_seconds() / 60)
            ef  = c.total_efectivo  or 0.0
            tj  = c.total_tarjeta   or 0.0
            tr  = c.total_transferencia or 0.0
            tv  = c.total_ventas    or 0.0
            ape = c.monto_apertura  or 0.0
            dif = (c.monto_cierre - (ape + ef)) if c.monto_cierre is not None else None
            result.append({
                "id":               c.id,
                "abierto_en":       c.abierto_en.isoformat() if c.abierto_en else None,
                "cerrado_en":       c.cerrado_en.isoformat() if c.cerrado_en else None,
                "duracion_min":     dur,
                "num_ventas":       c.num_ventas or 0,
                "total_ventas":     tv,
                "total_efectivo":   ef,
                "total_tarjeta":    tj,
                "total_transferencia": tr,
                "monto_apertura":   ape,
                "monto_cierre":     c.monto_cierre,
                "esperado_caja":    ape + ef,
                "diferencia":       dif,
                "abierto":          c.cerrado_en is None,
            })
        return result
    finally:
        db.close()


class RetiroIn(BaseModel):
    monto: float
    concepto: Optional[str] = None


@router.post("/retiro")
def registrar_retiro(body: RetiroIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden retirar efectivo")
    if body.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")

    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        # Intentar asociar al corte activo de cualquier cajero (si admin también tiene uno, o el primer abierto)
        corte = (
            db.query(CortesCaja)
            .filter(CortesCaja.cerrado_en == None)
            .order_by(CortesCaja.abierto_en.desc())
            .first()
        )
        r = RetiroCaja(
            corte_id=corte.id if corte else None,
            usuario_id=usuario_id,
            monto=body.monto,
            concepto=body.concepto,
            creado_en=datetime.now(),
        )
        db.add(r)
        db.commit()

        # Imprimir ticket de retiro y abrir cajón
        from app.database.models import Usuario as _Usr
        admin_obj = db.query(_Usr).filter(_Usr.id == usuario_id).first()
        retiro_ticket_data = {
            "monto":    r.monto,
            "concepto": r.concepto or "Sin concepto",
            "fecha":    r.creado_en.strftime("%d/%m/%Y %H:%M") if r.creado_en else "",
            "admin":    admin_obj.nombre if admin_obj else "Administrador",
        }
        from app.services.printer_service import printer_service as _ps
        bg.add_task(_ps.print_retiro, retiro_ticket_data)

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {
            "ok": True,
            "id": r.id,
            "monto": r.monto,
            "concepto": r.concepto,
            "creado_en": r.creado_en.isoformat(),
            "corte_id": r.corte_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/retiros")
def listar_retiros(
    limite: int = 200,
    corte_id: Optional[int] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    payload: dict = Depends(get_current_api_user),
):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    limite = min(max(1, limite), 500)
    db = get_db_session()
    try:
        q = db.query(RetiroCaja)
        if corte_id is not None:
            q = q.filter(RetiroCaja.corte_id == corte_id)
        if fecha_inicio:
            q = q.filter(RetiroCaja.creado_en >= datetime.fromisoformat(fecha_inicio))
        if fecha_fin:
            q = q.filter(RetiroCaja.creado_en <= datetime.fromisoformat(fecha_fin + "T23:59:59"))
        retiros = q.order_by(RetiroCaja.creado_en.desc()).limit(limite).all()
        return [
            {
                "id":        r.id,
                "corte_id":  r.corte_id,
                "monto":     r.monto,
                "concepto":  r.concepto or "",
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                "usuario":   r.usuario.nombre if r.usuario else "",
            }
            for r in retiros
        ]
    finally:
        db.close()
