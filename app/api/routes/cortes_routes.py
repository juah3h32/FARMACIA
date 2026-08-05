from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date as _date_type, time as _time_type
from sqlalchemy import func
from app.database.connection import get_db_session
from app.database.models import (
    CortesCaja, RetiroCaja, Venta, EstadoVenta, MetodoPago,
    ItemVenta, Producto, MovimientoStock, TipoMovimiento,
)
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _precio_lookup(db, venta_ids) -> dict:
    """Batch {(venta_id, producto_id): precio_unitario} for a set of ventas —
    one query, used to price MovimientoStock(tipo=devolucion) rows without
    doing a per-row ItemVenta query (was the N+1 that made corte/retiro
    screens slow as returns history grew)."""
    if not venta_ids:
        return {}
    rows = (
        db.query(ItemVenta.venta_id, ItemVenta.producto_id, ItemVenta.precio_unitario)
        .filter(ItemVenta.venta_id.in_(venta_ids))
        .all()
    )
    return {(vid, pid): precio for vid, pid, precio in rows}


def _calc_devoluciones(db, usuario_id: int, desde: datetime, hasta: datetime) -> float:
    """
    Monetary value of partial returns processed by usuario_id in [desde, hasta].
    Full returns already excluded via venta.estado=devolucion filter.
    Partial returns leave the original venta as completada but generate
    MovimientoStock(tipo=devolucion) entries — we price those here.
    """
    dev_movs = (
        db.query(MovimientoStock)
        .filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_tipo == "devolucion",
            MovimientoStock.usuario_id == usuario_id,
            MovimientoStock.creado_en >= desde,
            MovimientoStock.creado_en <= hasta,
        )
        .all()
    )
    if not dev_movs:
        return 0.0
    precios = _precio_lookup(db, {m.referencia_id for m in dev_movs})
    total = 0.0
    for mov in dev_movs:
        precio = precios.get((mov.referencia_id, mov.producto_id))
        if precio is not None:
            total += precio * mov.cantidad
    return total


def _calc_disponibles(db):
    """Returns (ganancia_disponible, capital_inversion_disponible) from all-time
    data. Debe usar la misma fórmula que /cortes/ganancia (ventas netas de
    devoluciones, IVA excluido de la ganancia) — si no, el límite que valida un
    retiro no coincide con lo que la pantalla de Control de Caja muestra."""
    tv, iva_total = db.query(
        func.sum(Venta.total), func.sum(Venta.iva)
    ).filter(
        Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True)
    ).first()
    tv = tv or 0.0
    iva_total = iva_total or 0.0

    total_costo = db.query(
        func.sum(ItemVenta.cantidad * func.coalesce(Producto.precio_compra, 0.0))
    ).join(Producto, ItemVenta.producto_id == Producto.id).join(
        Venta, ItemVenta.venta_id == Venta.id
    ).filter(
        Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True)
    ).scalar() or 0.0

    dev_movs = db.query(MovimientoStock).filter(
        MovimientoStock.tipo == TipoMovimiento.devolucion,
        MovimientoStock.referencia_tipo == "devolucion",
    ).all()
    total_devoluciones = 0.0
    if dev_movs:
        precios = _precio_lookup(db, {m.referencia_id for m in dev_movs})
        for mov in dev_movs:
            precio = precios.get((mov.referencia_id, mov.producto_id))
            if precio is not None:
                total_devoluciones += precio * mov.cantidad

    ventas_netas = tv - total_devoluciones
    # El IVA cobrado no es ganancia — es dinero del SAT que solo pasa por caja
    ganancia = (ventas_netas - iva_total) - total_costo

    ret_personal = db.query(func.sum(RetiroCaja.monto)).filter(
        RetiroCaja.tipo == "personal"
    ).scalar() or 0.0
    ret_inversion = db.query(func.sum(RetiroCaja.monto)).filter(
        RetiroCaja.tipo == "inversion"
    ).scalar() or 0.0
    return ganancia - ret_personal, max(0.0, total_costo - ret_inversion)


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


def _get_corte_cerrado_hoy(db, usuario_id: int) -> Optional[CortesCaja]:
    """Último turno de HOY ya cerrado para este cajero (si existe). Permite
    ofrecer reabrirlo cuando llega una venta tardía (ej. después del cierre de
    las 21:00) para que quede dentro del MISMO turno en vez de una venta huérfana
    o un corte sintético aparte."""
    inicio_hoy = datetime.combine(datetime.now().date(), _time_type.min)
    return (
        db.query(CortesCaja)
        .filter(
            CortesCaja.usuario_id == usuario_id,
            CortesCaja.cerrado_en != None,
            CortesCaja.abierto_en >= inicio_hoy,
        )
        .order_by(CortesCaja.cerrado_en.desc())
        .first()
    )


def _sumar_totales_ventas(ventas: list) -> tuple[float, float, float, float]:
    """Suma efectivo/tarjeta/transferencia/total de una lista de Venta ya cargada
    (sin query) — helper puro, reutilizado por _calcular_totales_corte y por
    reconstruir_historicos (que agrupa ventas en memoria para evitar N+1 queries).
    El total incluye también ventas con metodo_pago='mixto' (no tiene bucket propio
    de efectivo/tarjeta/transferencia, pero sí debe contar en el total del corte —
    antes se perdía del total_ventas guardado al cerrar turno, aunque sí aparecía
    en la vista en vivo, dando cifras distintas entre "corte abierto" y "ya cerrado")."""
    ef = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.efectivo)
    tj = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.tarjeta)
    tr = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.transferencia)
    mx = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.mixto)
    return ef, tj, tr, ef + tj + tr + mx


def _costo_ventas(db, venta_ids: list) -> float:
    """Costo de mercancía vendida (join ItemVenta → Producto.precio_compra)."""
    if not venta_ids:
        return 0.0
    cost_rows = (
        db.query(ItemVenta.cantidad, Producto.precio_compra)
        .join(Producto, ItemVenta.producto_id == Producto.id)
        .filter(ItemVenta.venta_id.in_(venta_ids))
        .all()
    )
    return sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)


def _calcular_totales_corte(db, c: CortesCaja, hasta: datetime):
    """Calculate and set totals on a CortesCaja object (does NOT commit)."""
    ventas = (
        db.query(Venta)
        .filter(
            Venta.usuario_id == c.usuario_id,
            Venta.creado_en >= c.abierto_en,
            Venta.creado_en <= hasta,
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
        )
        .all()
    )
    ef, tj, tr, tv = _sumar_totales_ventas(ventas)
    total_costo = _costo_ventas(db, [v.id for v in ventas])
    c.total_ventas        = tv
    c.total_efectivo      = ef
    c.total_tarjeta       = tj
    c.total_transferencia = tr
    c.total_costo         = total_costo
    c.num_ventas          = len(ventas)
    return ef, tj, tr, tv, total_costo


def _auto_cerrar_turno(db, c: CortesCaja, nota: str = "Cierre automático fin de día") -> None:
    """Close an open shift automatically. Does NOT commit."""
    ahora = datetime.now()
    # Close time = 21:00 of the shift's opening day (or now if opening day is today)
    apertura_date = c.abierto_en.date() if c.abierto_en else ahora.date()
    if apertura_date < ahora.date():
        cierre_dt = datetime.combine(apertura_date, _time_type(21, 0, 0))
    else:
        cierre_dt = ahora
    ef, _, _, _, _ = _calcular_totales_corte(db, c, cierre_dt)
    c.cerrado_en   = cierre_dt
    c.monto_cierre = (c.monto_apertura or 0.0) + ef
    if c.notas:
        c.notas = c.notas + " | " + nota
    else:
        c.notas = nota


@router.get("/activo")
def corte_activo(payload: dict = Depends(get_current_api_user)):
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        c = _get_corte_activo(db, usuario_id)
        if not c:
            cerrado_hoy = _get_corte_cerrado_hoy(db, usuario_id)
            return {
                "abierto": False,
                "cerrado_hoy": (
                    {"id": cerrado_hoy.id, "cerrado_en": cerrado_hoy.cerrado_en.isoformat()}
                    if cerrado_hoy else None
                ),
            }
        # Calculate running totals from ventas since opening
        ventas = (
            db.query(Venta)
            .filter(
                Venta.usuario_id == usuario_id,
                Venta.creado_en >= c.abierto_en,
                Venta.estado == EstadoVenta.completada,
                Venta.eliminado.is_not(True),
            )
            .all()
        )
        retiros = db.query(RetiroCaja).filter(RetiroCaja.corte_id == c.id).all()
        ef, tj, tr, tv = _sumar_totales_ventas(ventas)
        total_retiros = sum(r.monto for r in retiros)
        total_costo = _costo_ventas(db, [v.id for v in ventas])
        iva_total = sum(v.iva or 0.0 for v in ventas)

        total_devoluciones = _calc_devoluciones(db, usuario_id, c.abierto_en, datetime.now())
        ventas_netas = tv - total_devoluciones

        # El IVA cobrado no es ganancia y las devoluciones ya no son venta real
        ganancia   = (ventas_netas - iva_total) - total_costo
        disponible = ganancia - total_retiros

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
            "total_costo":      total_costo,
            "ganancia":         ganancia,
            "total_retiros":    total_retiros,
            "disponible":       disponible,
            # Los retiros siempre los hace el admin (los cajeros no pueden
            # registrar retiros), nunca se descuentan del cuadre de UN turno —
            # son un movimiento del cajón en general, no responsabilidad de
            # ese cajero. Antes restarlos aquí producía "esperado" negativo
            # cada vez que un pago a proveedor superaba las ventas del propio
            # turno, aunque el dinero viniera acumulado de turnos anteriores.
            "esperado_caja":    c.monto_apertura + ef,
            "notas":            c.notas or "",
            "total_devoluciones": total_devoluciones,
            "ventas_netas":       ventas_netas,
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
            # If the open shift is from a previous day, auto-close it before opening today's
            if existente.abierto_en and existente.abierto_en.date() < datetime.now().date():
                _auto_cerrar_turno(db, existente, "Cierre automático — nuevo día")
                db.commit()
            else:
                raise HTTPException(status_code=400, detail="Ya tienes un turno abierto hoy")
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


@router.post("/reabrir")
def reabrir_corte(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Reabre el turno de HOY de este cajero ya cerrado (ej. cierre automático
    de las 21:00) para que una venta tardía quede dentro del MISMO turno en vez
    de crear uno nuevo o quedar huérfana. Limpia cerrado_en/monto_cierre — se
    recalculan solos con _calcular_totales_corte al volver a cerrarlo."""
    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        if _get_corte_activo(db, usuario_id):
            raise HTTPException(status_code=400, detail="Ya tienes un turno abierto")
        c = _get_corte_cerrado_hoy(db, usuario_id)
        if not c:
            raise HTTPException(status_code=404, detail="No hay un turno de hoy para reabrir")
        c.cerrado_en = None
        c.monto_cierre = None
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "id": c.id}
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

        ahora = datetime.now()
        ef, tj, tr, tv, total_costo = _calcular_totales_corte(db, c, ahora)
        total_retiros = sum(
            r.monto for r in db.query(RetiroCaja).filter(RetiroCaja.corte_id == c.id).all()
        )

        c.monto_cierre = body.monto_cierre
        c.cerrado_en   = ahora
        if body.notas:
            c.notas = body.notas

        apertura = c.monto_apertura  # cache before commit (object expires after commit)
        num_ventas = c.num_ventas
        total_devoluciones = _calc_devoluciones(db, usuario_id, c.abierto_en, ahora)
        ventas_netas = tv - total_devoluciones
        iva_total = db.query(func.sum(Venta.iva)).filter(
            Venta.usuario_id == usuario_id,
            Venta.creado_en >= c.abierto_en,
            Venta.creado_en <= ahora,
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
        ).scalar() or 0.0
        # El IVA cobrado no es ganancia y las devoluciones ya no son venta real
        ganancia = (ventas_netas - iva_total) - total_costo
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        # Ventas de emergencia hechas DESPUÉS de este cierre (turno ya cerrado, sin
        # abrir uno nuevo) quedarían huérfanas para siempre — se dispara la
        # reconstrucción en background para que, apenas ocurran, ya tengan un corte
        # que las cubra ese mismo día sin que nadie tenga que acordarse de darle al
        # botón manual del panel admin.
        bg.add_task(_reconstruir_historicos_run)
        # Los retiros los hace el admin, nunca el cajero — no se descuentan del
        # cuadre de un turno individual (ver mismo criterio en /activo).
        esperado   = apertura + ef
        diferencia = body.monto_cierre - esperado
        return {
            "ok":                 True,
            "num_ventas":         num_ventas,
            "total_ventas":       tv,
            "efectivo":           ef,
            "tarjeta":            tj,
            "transferencia":      tr,
            "total_costo":        total_costo,
            "ganancia":           ganancia,
            "monto_apertura":     apertura,
            "monto_cierre":       body.monto_cierre,
            "total_retiros":      total_retiros,
            "esperado":           esperado,
            "diferencia":         diferencia,
            "total_devoluciones": total_devoluciones,
            "ventas_netas":       ventas_netas,
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
            ef  = c.total_efectivo       or 0.0
            tj  = c.total_tarjeta        or 0.0
            tr  = c.total_transferencia  or 0.0
            tv  = c.total_ventas         or 0.0
            tc  = c.total_costo          or 0.0
            ape = c.monto_apertura       or 0.0
            total_retiros_c = sum(
                r.monto for r in db.query(RetiroCaja).filter(RetiroCaja.corte_id == c.id).all()
            )
            # Los retiros los hace el admin, nunca el cajero — no se descuentan
            # del cuadre de un turno individual (ver mismo criterio en /activo).
            esperado_caja = ape + ef
            dif = (c.monto_cierre - esperado_caja) if c.monto_cierre is not None else None
            hasta = c.cerrado_en or datetime.now()
            total_dev = _calc_devoluciones(db, usuario_id, c.abierto_en, hasta) if c.abierto_en else 0.0
            iva_c = 0.0
            if c.abierto_en:
                iva_c = db.query(func.sum(Venta.iva)).filter(
                    Venta.usuario_id == usuario_id,
                    Venta.creado_en >= c.abierto_en,
                    Venta.creado_en <= hasta,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True),
                ).scalar() or 0.0
            ventas_netas_c = tv - total_dev
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
                "total_costo":      tc,
                "ganancia":         (ventas_netas_c - iva_c) - tc,
                "monto_apertura":   ape,
                "monto_cierre":     c.monto_cierre,
                "total_retiros":    total_retiros_c,
                "esperado_caja":    esperado_caja,
                "diferencia":       dif,
                "abierto":          c.cerrado_en is None,
                "total_devoluciones": total_dev,
                "ventas_netas":       ventas_netas_c,
            })
        return result
    finally:
        db.close()


class RetiroIn(BaseModel):
    monto: float
    concepto: Optional[str] = None
    tipo: str = "personal"   # 'personal' | 'inversion'
    fecha: Optional[str] = None  # ISO date "YYYY-MM-DD", None = hoy


@router.post("/retiro")
def registrar_retiro(body: RetiroIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden retirar efectivo")
    if body.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")

    usuario_id = int(payload["sub"])
    db = get_db_session()
    try:
        tipo = body.tipo if body.tipo in ("personal", "inversion") else "personal"

        # Parse optional backdated date
        if body.fecha:
            try:
                from datetime import date as _date
                parsed = datetime.strptime(body.fecha, "%Y-%m-%d")
                # Keep time as 23:59 so it sorts after regular events of that day
                creado_en = parsed.replace(hour=23, minute=59, second=0)
            except ValueError:
                raise HTTPException(status_code=400, detail="Fecha inválida, usa YYYY-MM-DD")
        else:
            creado_en = datetime.now()

        # Validate against available balance
        gan_disp, cap_inv = _calc_disponibles(db)
        if tipo == "personal" and body.monto > gan_disp + 0.005:
            raise HTTPException(
                status_code=400,
                detail=f"Saldo insuficiente. Ganancia disponible: ${gan_disp:.2f}",
            )
        if tipo == "inversion" and body.monto > cap_inv + 0.005:
            raise HTTPException(
                status_code=400,
                detail=f"Saldo insuficiente. Capital de inversión disponible: ${cap_inv:.2f}",
            )

        # Un retiro es un movimiento del admin (solo el admin puede registrarlo),
        # nunca del turno de un cajero — no se asocia a ningún corte_id. Antes se
        # ligaba al corte abierto de turno (o al corte cuya ventana cubriera la
        # fecha, si era retroactivo), lo que hacía que un pago a proveedor apareciera
        # como si fuera responsabilidad del cajero que tenía el turno abierto en
        # ese momento — un cajero jamás retira dinero, así que nunca le pertenece.
        r = RetiroCaja(
            corte_id=None,
            usuario_id=usuario_id,
            monto=body.monto,
            concepto=body.concepto,
            tipo=tipo,
            creado_en=creado_en,
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

        from app.auth.auth_service import _registrar_auditoria
        _registrar_auditoria(
            usuario_id,
            "RETIRO_CAJA",
            "retiros_caja",
            r.id,
            f"Monto:${r.monto:.2f} Tipo:{tipo} Concepto:{r.concepto or ''}"
        )

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
                "tipo":      r.tipo or "personal",
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                "usuario":   r.usuario.nombre if r.usuario else "",
            }
            for r in retiros
        ]
    finally:
        db.close()


class EditarRetiroIn(BaseModel):
    tipo: str   # 'personal' | 'inversion'


@router.delete("/retiro/{retiro_id}")
def eliminar_retiro(retiro_id: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        r = db.query(RetiroCaja).filter(RetiroCaja.id == retiro_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="Retiro no encontrado")
        monto_borrado, tipo_borrado, concepto_borrado = r.monto, r.tipo, r.concepto
        db.delete(r)
        db.commit()

        from app.auth.auth_service import _registrar_auditoria
        _registrar_auditoria(
            int(payload["sub"]), "RETIRO_CAJA_BORRADO", "retiros_caja", retiro_id,
            f"Monto:${monto_borrado:.2f} Tipo:{tipo_borrado} Concepto:{concepto_borrado or ''}"
        )

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            # retiros_caja está en _NO_TURSO_DELETE (sync normal nunca borra por
            # ausencia, para no perder retiros de otra PC no sincronizada aún) —
            # sin este delete explícito, el retiro borrado localmente reaparecía
            # solo con el siguiente pull periódico de Turso.
            # Síncrono (no bg.add_task): si la app cierra justo después de borrar
            # (p.ej. para instalar una actualización), una tarea en background se
            # pierde antes de llegar a Turso y el retiro "resucita" en el próximo pull.
            delete_ids_from_turso("retiros_caja", [retiro_id])
            bg.add_task(sync_to_turso)
        return {"ok": True, "id": retiro_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.patch("/retiro/{retiro_id}")
def editar_retiro(retiro_id: int, body: EditarRetiroIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if body.tipo not in ("personal", "inversion"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'personal' o 'inversion'")
    db = get_db_session()
    try:
        r = db.query(RetiroCaja).filter(RetiroCaja.id == retiro_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="Retiro no encontrado")
        tipo_anterior = r.tipo
        r.tipo = body.tipo
        db.commit()

        from app.auth.auth_service import _registrar_auditoria
        _registrar_auditoria(
            int(payload["sub"]), "RETIRO_CAJA_TIPO_CAMBIADO", "retiros_caja", retiro_id,
            f"Monto:${r.monto:.2f} Tipo:{tipo_anterior}->{body.tipo} Concepto:{r.concepto or ''}"
        )

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "id": r.id, "tipo": r.tipo}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/ganancia")
def resumen_ganancia(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    payload: dict = Depends(get_current_api_user),
):
    """All-time profit snapshot — turno-independent. Admin only.

    Los totales devueltos (ganancia, capital_inversion, etc.) SIEMPRE son
    acumulados desde el inicio — son los que realmente determinan cuánto se
    puede retirar hoy, y no deben depender del filtro de fechas de la pantalla.
    Si se mandan `desde`/`hasta`, se agrega además un bloque "periodo" con el
    mismo desglose pero acotado a ese rango — solo para comparar/reconciliar
    contra un cálculo manual del usuario, nunca como límite de retiro."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        ventas = (
            db.query(Venta)
            .filter(Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True))
            .all()
        )
        tv = sum(v.total for v in ventas)
        iva_total = sum(v.iva or 0.0 for v in ventas)

        venta_ids = [v.id for v in ventas]
        if venta_ids:
            cost_rows = (
                db.query(ItemVenta.cantidad, Producto.precio_compra)
                .join(Producto, ItemVenta.producto_id == Producto.id)
                .filter(ItemVenta.venta_id.in_(venta_ids))
                .all()
            )
            total_costo = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)
        else:
            total_costo = 0.0

        all_retiros = db.query(RetiroCaja).all()
        retiros_personales = sum(r.monto for r in all_retiros if (r.tipo or "personal") == "personal")
        retiros_inversion  = sum(r.monto for r in all_retiros if (r.tipo or "personal") == "inversion")
        total_retiros      = retiros_personales + retiros_inversion

        # Subtract all-time partial returns
        dev_movs = db.query(MovimientoStock).filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_tipo == "devolucion",
        ).all()
        total_devoluciones = 0.0
        if dev_movs:
            precios = _precio_lookup(db, {m.referencia_id for m in dev_movs})
            for mov in dev_movs:
                precio = precios.get((mov.referencia_id, mov.producto_id))
                if precio is not None:
                    total_devoluciones += precio * mov.cantidad

        ventas_netas        = tv - total_devoluciones
        # El IVA cobrado no es ganancia — es dinero del SAT que solo pasa por caja
        ganancia            = (ventas_netas - iva_total) - total_costo
        ganancia_disponible = ganancia - retiros_personales
        # Puede ser negativo si se retiró más de lo que las ventas han recuperado
        # (sobregiro de inversión) — se reporta tal cual para no ocultarlo.
        capital_inversion             = total_costo - retiros_inversion
        capital_inversion_disponible  = max(0.0, capital_inversion)

        result = {
            "num_ventas":          len(ventas),
            "total_ventas":        tv,
            "total_devoluciones":  round(total_devoluciones, 2),
            "ventas_netas":        round(ventas_netas, 2),
            "total_costo":         total_costo,
            "ganancia":            round(ganancia, 2),
            "total_retiros":       total_retiros,
            "retiros_personales":  retiros_personales,
            "retiros_inversion":   retiros_inversion,
            "disponible":          round(ganancia_disponible, 2),
            "ganancia_disponible": round(ganancia_disponible, 2),
            "capital_inversion":             round(capital_inversion, 2),
            "capital_inversion_disponible":  round(capital_inversion_disponible, 2),
        }

        if desde or hasta:
            try:
                d_ini = datetime.strptime(desde, "%Y-%m-%d") if desde else datetime.min
                d_fin = (datetime.strptime(hasta, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                         if hasta else datetime.now())
            except ValueError:
                raise HTTPException(status_code=400, detail="Fecha inválida, usa YYYY-MM-DD")

            ventas_p = [v for v in ventas if v.creado_en and d_ini <= v.creado_en <= d_fin]
            tv_p  = sum(v.total for v in ventas_p)
            iva_p = sum(v.iva or 0.0 for v in ventas_p)
            vids_p = [v.id for v in ventas_p]
            if vids_p:
                cost_rows_p = (
                    db.query(ItemVenta.cantidad, Producto.precio_compra)
                    .join(Producto, ItemVenta.producto_id == Producto.id)
                    .filter(ItemVenta.venta_id.in_(vids_p))
                    .all()
                )
                total_costo_p = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows_p)
            else:
                total_costo_p = 0.0

            dev_movs_p = [m for m in dev_movs if m.creado_en and d_ini <= m.creado_en <= d_fin]
            total_dev_p = 0.0
            if dev_movs_p:
                precios_p = _precio_lookup(db, {m.referencia_id for m in dev_movs_p})
                for mov in dev_movs_p:
                    precio = precios_p.get((mov.referencia_id, mov.producto_id))
                    if precio is not None:
                        total_dev_p += precio * mov.cantidad

            retiros_p = [r for r in all_retiros if r.creado_en and d_ini <= r.creado_en <= d_fin]
            ret_personal_p  = sum(r.monto for r in retiros_p if (r.tipo or "personal") == "personal")
            ret_inversion_p = sum(r.monto for r in retiros_p if (r.tipo or "personal") == "inversion")

            ventas_netas_p = tv_p - total_dev_p
            ganancia_p = (ventas_netas_p - iva_p) - total_costo_p

            result["periodo"] = {
                "desde":               desde,
                "hasta":               hasta,
                "num_ventas":          len(ventas_p),
                "total_ventas":        round(tv_p, 2),
                "total_devoluciones":  round(total_dev_p, 2),
                "ventas_netas":        round(ventas_netas_p, 2),
                "total_costo":         round(total_costo_p, 2),
                "ganancia":            round(ganancia_p, 2),
                "retiros_personales":  round(ret_personal_p, 2),
                "retiros_inversion":   round(ret_inversion_p, 2),
                # Costo recuperado en el período menos lo pagado a proveedores en
                # el período — NO es un saldo acumulado, solo sirve para comparar
                # contra un cálculo manual de ese mismo rango de fechas.
                "capital_inversion":   round(total_costo_p - ret_inversion_p, 2),
            }

        return result
    finally:
        db.close()


@router.post("/recalcular-historicos")
def recalcular_historicos(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Admin: recalcula totales de todos los cortes cerrados usando el rango abierto_en..cerrado_en."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        cortes = (
            db.query(CortesCaja)
            .filter(CortesCaja.cerrado_en != None)
            .all()
        )
        actualizados = 0
        for c in cortes:
            if not c.abierto_en or not c.cerrado_en:
                continue
            _calcular_totales_corte(db, c, c.cerrado_en)
            actualizados += 1
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "cortes_recalculados": actualizados}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/cerrar-viejos")
def cerrar_turnos_viejos(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Admin: auto-close all shifts that are still open from previous days."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        hoy = datetime.now().date()
        cortes = (
            db.query(CortesCaja)
            .filter(CortesCaja.cerrado_en == None)
            .all()
        )
        cerrados = 0
        for c in cortes:
            if c.abierto_en and c.abierto_en.date() < hoy:
                _auto_cerrar_turno(db, c, "Cierre automático — turno de día anterior")
                cerrados += 1
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "turnos_cerrados": cerrados}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/auto-cerrar-diario")
def auto_cerrar_diario(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Internal: close all open shifts at end of day (21:00). Called by scheduler or admin."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        cortes = db.query(CortesCaja).filter(CortesCaja.cerrado_en == None).all()
        cerrados = 0
        for c in cortes:
            _auto_cerrar_turno(db, c, "Cierre automático 21:00")
            cerrados += 1
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"ok": True, "turnos_cerrados": cerrados}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


def _reconstruir_historicos_core(db) -> dict:
    """Cierra cortes fantasma y crea cortes sintéticos para ventas huérfanas —
    ventas completadas que no caen dentro de la ventana horaria [abierto_en,
    cerrado_en] de ningún corte (típicamente ventas de emergencia hechas después
    de cerrar caja). Comparar por timestamp exacto (no solo por día calendario)
    importa: una venta de emergencia cae en el mismo 'día' que el corte ya
    cerrado, pero fuera de su ventana horaria — con un chequeo por día completo
    esa venta se consideraba 'cubierta' y jamás se le creaba un corte, quedando
    huérfana para siempre. Hace commit; no abre/cierra la sesión."""
    from collections import defaultdict

    # 1. Close open phantom cortes (0 completed ventas tied to them)
    open_cortes = db.query(CortesCaja).filter(CortesCaja.cerrado_en == None).all()
    phantoms_closed = 0
    for c in open_cortes:
        if not c.abierto_en:
            _auto_cerrar_turno(db, c, "Cerrado — corte sin fecha de apertura")
            phantoms_closed += 1
            continue
        count = db.query(Venta).filter(
            Venta.usuario_id == c.usuario_id,
            Venta.creado_en >= c.abierto_en,
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
        ).count()
        if count == 0:
            _auto_cerrar_turno(db, c, "Cerrado — corte fantasma sin ventas")
            phantoms_closed += 1
    db.flush()

    # 2. Gather all completed ventas
    all_ventas = (
        db.query(Venta)
        .filter(Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True))
        .all()
    )

    # 3. Gather existing cortes (including newly created/closed ones via flush)
    all_cortes = db.query(CortesCaja).all()

    def _venta_covered(v) -> bool:
        for c in all_cortes:
            if c.usuario_id != v.usuario_id or not c.abierto_en:
                continue
            cierre = c.cerrado_en or datetime.now()
            if c.abierto_en <= v.creado_en <= cierre:
                return True
        return False

    # 4. Group uncovered ventas by (usuario, día)
    huerfanas_by_user_day: dict = defaultdict(list)
    for v in all_ventas:
        if v.creado_en and not _venta_covered(v):
            huerfanas_by_user_day[(v.usuario_id, v.creado_en.date())].append(v)

    # 5. Create a synthetic corte per (user, day) group spanning exactly those
    # ventas' timestamps — así aparece ese mismo día sin solaparse con el corte
    # normal ya cerrado.
    created = 0
    for (usuario_id, day), ventas in sorted(huerfanas_by_user_day.items()):
        open_dt  = min(v.creado_en for v in ventas)
        close_dt = max(v.creado_en for v in ventas)

        ef, tj, tr, tv = _sumar_totales_ventas(ventas)
        total_costo = _costo_ventas(db, [v.id for v in ventas])

        new_c = CortesCaja(
            usuario_id=usuario_id,
            monto_apertura=0.0,
            monto_cierre=ef,
            abierto_en=open_dt,
            cerrado_en=close_dt,
            total_ventas=tv,
            total_efectivo=ef,
            total_tarjeta=tj,
            total_transferencia=tr,
            total_costo=total_costo,
            num_ventas=len(ventas),
            notas="Reconstruido automáticamente — venta(s) de emergencia fuera de turno",
        )
        db.add(new_c)
        all_cortes.append(new_c)
        created += 1

    db.commit()
    return {"cortes_creados": created, "cortes_phantom_cerrados": phantoms_closed}


def _reconstruir_historicos_run() -> dict:
    """Pull-run-push standalone: sin dependencias de request, para poder llamarse
    desde un BackgroundTasks (auto-trigger al cerrar corte) o desde el endpoint
    manual del panel admin."""
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        try:
            from app.database.sync_service import sync_from_turso
            sync_from_turso()
        except Exception as _e:
            print(f"[reconstruir] sync_from_turso warning: {_e}")

    db = get_db_session()
    try:
        result = _reconstruir_historicos_core(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if _cfg.TURSO_SYNC:
        try:
            from app.database.sync_service import sync_to_turso
            sync_to_turso()
        except Exception as _e:
            print(f"[reconstruir] sync_to_turso warning: {_e}")

    return {"ok": True, **result}


@router.post("/reconstruir-historicos")
def reconstruir_historicos(payload: dict = Depends(get_current_api_user)):
    """Admin: dispara manualmente la reconstrucción (ver _reconstruir_historicos_core)."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    try:
        return _reconstruir_historicos_run()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
