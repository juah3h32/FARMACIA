from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload
import io, csv

from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, EstadoVenta, CortesCaja, Lote
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _rango(fecha_inicio: date, fecha_fin: date):
    return (
        datetime.combine(fecha_inicio, datetime.min.time()),
        datetime.combine(fecha_fin,    datetime.max.time()),
    )


@router.get("/resumen")
def resumen(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        ventas = (
            db.query(Venta)
            .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .all()
        )
        total = sum(v.total for v in ventas)
        num   = len(ventas)

        por_dia: dict[str, float] = {}
        for v in ventas:
            d = v.creado_en.date().isoformat() if v.creado_en else "?"
            por_dia[d] = por_dia.get(d, 0.0) + v.total

        mejor_dia   = max(por_dia, key=por_dia.get) if por_dia else None
        mejor_monto = por_dia[mejor_dia] if mejor_dia else 0.0

        # Cost of goods sold for period
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
        ganancia = total - total_costo

        return {
            "total":            total,
            "num_ventas":       num,
            "ticket_promedio":  total / num if num else 0.0,
            "mejor_dia_fecha":  mejor_dia,
            "mejor_dia_monto":  mejor_monto,
            "efectivo":         sum(v.total for v in ventas if v.metodo_pago.value == "efectivo"),
            "tarjeta":          sum(v.total for v in ventas if v.metodo_pago.value == "tarjeta"),
            "transferencia":    sum(v.total for v in ventas if v.metodo_pago.value == "transferencia"),
            "total_costo":      total_costo,
            "ganancia":         ganancia,
            "por_dia": [{"fecha": k, "total": v} for k, v in sorted(por_dia.items())],
        }
    finally:
        db.close()


@router.get("/top-productos")
def top_productos(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    limite: int = Query(10, ge=1, le=50),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        rows = (
            db.query(
                Producto.nombre,
                func.sum(ItemVenta.cantidad).label("total_vendido"),
                func.sum(ItemVenta.subtotal).label("total_ingreso"),
            )
            .join(ItemVenta, ItemVenta.producto_id == Producto.id)
            .join(Venta,     Venta.id == ItemVenta.venta_id)
            .filter(
                Venta.creado_en >= fi,
                Venta.creado_en <= ff,
                Venta.estado == EstadoVenta.completada,
                Venta.eliminado.is_not(True),
            )
            .group_by(Producto.id, Producto.nombre)
            .order_by(func.sum(ItemVenta.cantidad).desc())
            .limit(limite)
            .all()
        )
        return [
            {"nombre": r.nombre, "cantidad": r.total_vendido or 0, "ingreso": r.total_ingreso or 0.0}
            for r in rows
        ]
    finally:
        db.close()


@router.get("/inventario")
def reporte_inventario(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        productos = (
            db.query(Producto)
            .filter(Producto.activo == True)
            .order_by(Producto.stock.asc(), Producto.nombre.asc())
            .all()
        )
        return [
            {
                "id":           p.id,
                "nombre":       p.nombre,
                "stock":        p.stock,
                "stock_minimo": p.stock_minimo,
                "precio_venta": p.precio_venta,
                "bajo_stock":   p.stock <= p.stock_minimo,
            }
            for p in productos
        ]
    finally:
        db.close()


@router.get("/cortes")
def cortes_caja(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        cortes = (
            db.query(CortesCaja)
            .filter(CortesCaja.abierto_en >= fi, CortesCaja.abierto_en <= ff)
            .order_by(CortesCaja.abierto_en.desc())
            .all()
        )
        result = []
        for c in cortes:
            dur_min = None
            if c.cerrado_en and c.abierto_en:
                dur_min = int((c.cerrado_en - c.abierto_en).total_seconds() / 60)
            ef  = c.total_efectivo or 0.0
            ape = c.monto_apertura or 0.0
            esperado = ape + ef
            dif = (c.monto_cierre - esperado) if c.monto_cierre is not None else None
            result.append({
                "id":               c.id,
                "cajero":           c.usuario.nombre if c.usuario else "",
                "abierto_en":       c.abierto_en.isoformat() if c.abierto_en else None,
                "cerrado_en":       c.cerrado_en.isoformat() if c.cerrado_en else None,
                "duracion_min":     dur_min,
                "num_ventas":       c.num_ventas or 0,
                "total_ventas":     c.total_ventas or 0.0,
                "total_efectivo":   ef,
                "total_tarjeta":    c.total_tarjeta or 0.0,
                "total_transferencia": c.total_transferencia or 0.0,
                "monto_apertura":   ape,
                "monto_cierre":     c.monto_cierre,
                "esperado_caja":    esperado,
                "diferencia":       dif,
                "notas":            c.notas or "",
                "abierto":          c.cerrado_en is None,
            })
        return result
    finally:
        db.close()


@router.get("/vencimientos")
def vencimientos(
    filtro: str = Query("todos"),   # todos | vencidos | por_vencer | vigentes
    dias:   int = Query(30),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        hoy = date.today()
        alerta = hoy + timedelta(days=dias)
        lotes = (
            db.query(Lote)
            .join(Producto, Lote.producto_id == Producto.id)
            .filter(Producto.activo == True, Lote.cantidad > 0)
            .order_by(Lote.fecha_vencimiento)
            .all()
        )
        result = []
        for l in lotes:
            fv = l.fecha_vencimiento
            if fv:
                dias_rest = (fv - hoy).days
                if fv < hoy:
                    estado = "vencido"
                elif fv <= alerta:
                    estado = "por_vencer"
                else:
                    estado = "vigente"
            else:
                dias_rest = None
                estado = "sin_fecha"

            if filtro == "vencidos"    and estado != "vencido":    continue
            if filtro == "por_vencer"  and estado != "por_vencer": continue
            if filtro == "vigentes"    and estado not in ("vigente","sin_fecha"): continue

            result.append({
                "lote_id":           l.id,
                "producto_id":       l.producto_id,
                "producto":          l.producto.nombre if l.producto else "",
                "numero_lote":       l.numero_lote or "",
                "fecha_vencimiento": fv.isoformat() if fv else None,
                "cantidad":          l.cantidad,
                "dias_restantes":    dias_rest,
                "estado":            estado,
            })
        return result
    finally:
        db.close()


@router.get("/export-csv")
def export_csv(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        from app.database.models import EstadoVenta as _EV
        ventas = (
            db.query(Venta)
            .options(joinedload(Venta.items))
            .filter(
                Venta.creado_en >= fi,
                Venta.creado_en <= ff,
                Venta.estado == _EV.completada,
                Venta.eliminado.is_not(True),
            )
            .order_by(Venta.creado_en)
            .all()
        )

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Folio", "Fecha", "Subtotal", "Descuento", "IVA", "Total",
                    "Metodo Pago", "Monto Pagado", "Cambio", "Estado", "N Articulos"])
        for v in ventas:
            w.writerow([
                v.folio or v.id,
                v.creado_en.strftime("%Y-%m-%d %H:%M") if v.creado_en else "",
                round(v.subtotal, 2),
                round(v.descuento, 2),
                round(v.iva, 2),
                round(v.total, 2),
                v.metodo_pago.value,
                round(v.monto_pagado, 2),
                round(v.cambio, 2),
                v.estado.value,
                len(v.items),
            ])

        buf.seek(0)
        filename = f"ventas_{fecha_inicio}_{fecha_fin}.csv"
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),  # utf-8-sig = Excel-compatible BOM
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        db.close()
