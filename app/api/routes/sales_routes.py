from fastapi import APIRouter, HTTPException, Depends, Query, Body
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database.connection import get_db_session
from app.database.models import (
    Venta, ItemVenta, Producto, EstadoVenta, Usuario, Cliente,
    MovimientoStock, TipoMovimiento,
)
from app.api.routes.auth_routes import get_current_api_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

router = APIRouter()


@router.get("/")
def listar_ventas(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    limite: int = Query(50),
    folio: Optional[str] = Query(None),
    payload: dict = Depends(get_current_api_user),
):
    limite = min(max(1, limite), 500)
    db = get_db_session()
    try:
        q = db.query(Venta).filter(Venta.eliminado.is_not(True))
        if payload.get("rol") != "admin":
            q = q.filter(Venta.usuario_id == int(payload["sub"]))
        if folio:
            q = q.filter(Venta.folio == folio.upper().strip())
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
        venta = (
            db.query(Venta)
            .options(selectinload(Venta.items).selectinload(ItemVenta.producto))
            .filter(Venta.id == venta_id, Venta.eliminado.is_not(True))
            .first()
        )
        if not venta:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        # ya_devuelto: sum of all prior devoluciones for each item in this venta
        dev_movs = db.query(MovimientoStock).filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_id == venta_id,
            MovimientoStock.referencia_tipo == "devolucion",
        ).all()
        ya_devuelto: dict[int, int] = {}
        for m in dev_movs:
            ya_devuelto[m.producto_id] = ya_devuelto.get(m.producto_id, 0) + m.cantidad
        return {
            "id": venta.id,
            "folio": venta.folio,
            "subtotal": venta.subtotal,
            "descuento": venta.descuento,
            "iva": venta.iva,
            "total": venta.total,
            "metodo_pago": venta.metodo_pago.value,
            "estado": venta.estado.value,
            "cajero": venta.usuario.nombre if venta.usuario else "—",
            "creado_en": venta.creado_en.isoformat() if venta.creado_en else None,
            "items": [
                {
                    "producto_id":    i.producto_id,
                    "nombre":         i.producto.nombre if i.producto else "",
                    "cantidad":       i.cantidad,
                    "ya_devuelto":    ya_devuelto.get(i.producto_id, 0),
                    "precio_unitario": i.precio_unitario,
                    "subtotal":       i.subtotal,
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


class DevolucionItemIn(BaseModel):
    producto_id: int
    cantidad: int


class DevolucionIn(BaseModel):
    items: list[DevolucionItemIn]
    motivo: str = ""


@router.post("/{venta_id}/devolucion")
def registrar_devolucion(
    venta_id: int,
    body: DevolucionIn,
    payload: dict = Depends(get_current_api_user),
):
    """
    Partial or full return: restore stock for each returned item,
    log a devolucion movement, and mark the sale as devolucion if all items returned.
    """
    db = get_db_session()
    try:
        venta = (
            db.query(Venta)
            .options(selectinload(Venta.items).selectinload(ItemVenta.producto))
            .filter(Venta.id == venta_id, Venta.eliminado.is_not(True))
            .first()
        )
        if not venta:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        if venta.estado == EstadoVenta.devolucion:
            raise HTTPException(status_code=400, detail="Venta ya marcada como devolución completa")

        orig_items = {i.producto_id: i for i in venta.items}
        cantidad_original = {i.producto_id: i.cantidad for i in venta.items}
        usuario_id = int(payload["sub"])
        total_devuelto = 0.0
        nota_parts = []

        for dev in body.items:
            if dev.cantidad <= 0:
                continue
            orig = orig_items.get(dev.producto_id)
            if not orig:
                raise HTTPException(
                    status_code=400,
                    detail=f"Producto {dev.producto_id} no estaba en la venta original",
                )
            if dev.cantidad > orig.cantidad:
                raise HTTPException(
                    status_code=400,
                    detail=f"No puedes devolver {dev.cantidad} — vendido {orig.cantidad} (prod {dev.producto_id})",
                )
            prod = db.query(Producto).filter(Producto.id == dev.producto_id).first()
            if prod:
                stock_ant = prod.stock
                prod.stock += dev.cantidad
                db.add(MovimientoStock(
                    producto_id=dev.producto_id,
                    tipo=TipoMovimiento.devolucion,
                    cantidad=dev.cantidad,
                    stock_anterior=stock_ant,
                    stock_nuevo=prod.stock,
                    referencia_id=venta_id,
                    referencia_tipo="devolucion",
                    usuario_id=usuario_id,
                    notas=f"Dev. {venta.folio}" + (f" | {body.motivo}" if body.motivo else ""),
                ))
            total_devuelto += orig.precio_unitario * dev.cantidad
            nombre = orig.producto.nombre if orig.producto else str(dev.producto_id)
            nota_parts.append(f"{nombre[:20]} x{dev.cantidad}")

            # Ajustar el item: reducir cantidad/subtotal/descuento proporcionalmente —
            # sin esto, la venta seguía "completada" por el monto ORIGINAL completo,
            # inflando ingresos/impuestos declarados y sobre-facturando si se timbra
            # como factura individual (bug real: devolución parcial no bajaba nada).
            cant_previa = orig.cantidad
            cant_nueva = cant_previa - dev.cantidad
            ratio_kept = (cant_nueva / cant_previa) if cant_previa else 0.0
            orig.cantidad = cant_nueva
            orig.subtotal = round((orig.subtotal or 0.0) * ratio_kept, 2)
            orig.descuento = round((orig.descuento or 0.0) * ratio_kept, 2)

        # Recalcular totales de la venta sobre lo que realmente quedó (no lo original)
        venta.subtotal = round(sum(i.subtotal or 0.0 for i in venta.items), 2)
        venta.iva = round(sum(
            (i.subtotal or 0.0) * 0.16 for i in venta.items if i.producto and i.producto.aplica_iva
        ), 2)
        venta.total = round((venta.subtotal - (venta.descuento or 0.0)) + venta.iva, 2)

        # Full return → mark sale as devolucion
        dev_map = {d.producto_id: d.cantidad for d in body.items if d.cantidad > 0}
        all_returned = all(
            dev_map.get(pid, 0) >= cant_orig
            for pid, cant_orig in cantidad_original.items()
        )
        if all_returned:
            venta.estado = EstadoVenta.devolucion

        nota_dev = f"[DEV {datetime.now().strftime('%d/%m %H:%M')}: {', '.join(nota_parts)}]"
        if body.motivo:
            nota_dev += f" Motivo:{body.motivo}"
        venta.notas = ((venta.notas or "").strip() + " " + nota_dev).strip()

        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            import threading
            threading.Thread(target=sync_to_turso, daemon=True).start()

        return {
            "ok": True,
            "folio": venta.folio,
            "total_devuelto": round(total_devuelto, 2),
            "estado_venta": venta.estado.value,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


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
