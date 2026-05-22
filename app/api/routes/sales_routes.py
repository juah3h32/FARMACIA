from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from datetime import date, datetime
from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto
from app.api.routes.auth_routes import get_current_api_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

router = APIRouter()


@router.get("/")
def listar_ventas(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    limite: int = Query(50),
    payload: dict = Depends(get_current_api_user),
):
    limite = min(max(1, limite), 500)
    db = get_db_session()
    try:
        q = db.query(Venta)
        if fecha_inicio:
            q = q.filter(Venta.creado_en >= datetime.combine(fecha_inicio, datetime.min.time()))
        if fecha_fin:
            q = q.filter(Venta.creado_en <= datetime.combine(fecha_fin, datetime.max.time()))
        ventas = (q.options(joinedload(Venta.items))
                   .order_by(Venta.creado_en.desc()).limit(limite).all())
        return [
            {
                "id": v.id,
                "folio": v.folio,
                "total": v.total,
                "metodo_pago": v.metodo_pago.value,
                "estado": v.estado.value,
                "creado_en": v.creado_en.isoformat() if v.creado_en else None,
                "num_items": len(v.items),  # pre-loaded, no extra query
            }
            for v in ventas
        ]
    finally:
        db.close()


@router.get("/resumen")
def resumen_ventas(
    fecha: Optional[date] = Query(None),
    payload: dict = Depends(get_current_api_user),
):
    db = get_db_session()
    try:
        fecha_consulta = fecha or datetime.utcnow().date()
        inicio = datetime.combine(fecha_consulta, datetime.min.time())
        fin = datetime.combine(fecha_consulta, datetime.max.time())

        ventas = db.query(Venta).filter(
            Venta.creado_en >= inicio,
            Venta.creado_en <= fin,
            Venta.estado == "completada",
        ).all()

        total = sum(v.total for v in ventas)
        return {
            "fecha": fecha_consulta.isoformat(),
            "num_ventas": len(ventas),
            "total": total,
            "efectivo": sum(v.total for v in ventas if v.metodo_pago.value == "efectivo"),
            "tarjeta": sum(v.total for v in ventas if v.metodo_pago.value == "tarjeta"),
            "transferencia": sum(v.total for v in ventas if v.metodo_pago.value == "transferencia"),
        }
    finally:
        db.close()


@router.get("/{venta_id}")
def obtener_venta(venta_id: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        venta = db.query(Venta).filter(Venta.id == venta_id).first()
        if not venta:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        return {
            "id": venta.id,
            "folio": venta.folio,
            "subtotal": venta.subtotal,
            "descuento": venta.descuento,
            "iva": venta.iva,
            "total": venta.total,
            "metodo_pago": venta.metodo_pago.value,
            "estado": venta.estado.value,
            "creado_en": venta.creado_en.isoformat() if venta.creado_en else None,
            "items": [
                {
                    "producto_id": i.producto_id,
                    "nombre": i.producto.nombre if i.producto else "",
                    "cantidad": i.cantidad,
                    "precio_unitario": i.precio_unitario,
                    "subtotal": i.subtotal,
                }
                for i in venta.items
            ],
        }
    finally:
        db.close()
