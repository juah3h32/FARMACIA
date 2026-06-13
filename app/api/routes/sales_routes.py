from fastapi import APIRouter, HTTPException, Depends, Query, Body
from typing import Optional, List
from datetime import date, datetime
from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, EstadoVenta, Usuario, Cliente
from app.api.routes.auth_routes import get_current_api_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

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
        q = db.query(Venta).filter(Venta.eliminado.is_not(True))
        if payload.get("rol") != "admin":
            q = q.filter(Venta.usuario_id == int(payload["sub"]))
        if fecha_inicio:
            q = q.filter(Venta.creado_en >= datetime.combine(fecha_inicio, datetime.min.time()))
        if fecha_fin:
            q = q.filter(Venta.creado_en <= datetime.combine(fecha_fin, datetime.max.time()))
        ventas = (q.options(selectinload(Venta.items).selectinload(ItemVenta.producto),
                            selectinload(Venta.usuario),
                            selectinload(Venta.cliente))
                   .order_by(Venta.creado_en.desc()).limit(limite).all())
        return [
            {
                "id":            v.id,
                "folio":         v.folio,
                "total":         v.total,
                "subtotal":      v.subtotal,
                "descuento":     v.descuento,
                "iva":           v.iva,
                "metodo_pago":   v.metodo_pago.value,
                "estado":        v.estado.value,
                "creado_en":     v.creado_en.isoformat() if v.creado_en else None,
                "cajero":        v.usuario.nombre if v.usuario else "—",
                "cajero_user":   v.usuario.username if v.usuario else "—",
                "cliente_nombre": v.cliente.nombre if v.cliente else "Público general",
                "num_items":     len(v.items),
                "items": [
                    {
                        "producto_id":    i.producto_id,
                        "nombre":         i.producto.nombre if i.producto else "—",
                        "presentacion":   i.producto.presentacion if i.producto else None,
                        "concentracion":  i.producto.concentracion if i.producto else None,
                        "contenido":      i.producto.contenido if i.producto else None,
                        "marca":          i.producto.marca if i.producto else None,
                        "cantidad":       i.cantidad,
                        "precio_unitario": i.precio_unitario,
                        "descuento":      i.descuento,
                        "subtotal":       i.subtotal,
                    }
                    for i in v.items
                ],
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
        fecha_consulta = fecha or datetime.now().date()
        inicio = datetime.combine(fecha_consulta, datetime.min.time())
        fin = datetime.combine(fecha_consulta, datetime.max.time())

        ventas = db.query(Venta).filter(
            Venta.creado_en >= inicio,
            Venta.creado_en <= fin,
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
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
        venta = db.query(Venta).filter(Venta.id == venta_id, Venta.eliminado.is_not(True)).first()
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


@router.delete("/{venta_id}")
def eliminar_venta_endpoint(venta_id: int, payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden eliminar ventas")
    try:
        from app.database.sync_service import eliminar_venta
        result = eliminar_venta(venta_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/eliminar-lote")
def eliminar_ventas_lote(
    ids: List[int] = Body(..., embed=True),
    payload: dict = Depends(get_current_api_user),
):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if not ids:
        raise HTTPException(status_code=400, detail="Lista vacía")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="Máximo 200 por lote")
    try:
        from app.database.sync_service import eliminar_venta
        deleted, folios = 0, []
        for venta_id in ids:
            try:
                result = eliminar_venta(venta_id)
                folios.append(result["folio"])
                deleted += 1
            except ValueError:
                pass  # not found or already deleted
        return {"ok": True, "deleted": deleted, "folios": folios}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
