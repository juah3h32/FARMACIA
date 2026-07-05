from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.database.connection import get_db_session
from app.database.models import OrdenCompra, ItemOrdenCompra, Producto, Lote, MovimientoStock, TipoMovimiento, EstadoOrdenCompra
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(p):
    if p.get("rol") != "admin":
        raise HTTPException(403, "Solo administradores")


class ItemOrdenIn(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float = 0.0


class OrdenCompraIn(BaseModel):
    proveedor_id: Optional[int] = None
    proveedor: Optional[str] = None
    notas: Optional[str] = None
    items: List[ItemOrdenIn] = []


def _orden_dict(o, include_items=True):
    d = {
        "id": o.id,
        "folio": o.folio,
        "proveedor_id": o.proveedor_id,
        "proveedor_nombre": o.proveedor.nombre if o.proveedor else (o.proveedor_texto or None),
        "estado": o.estado.value if hasattr(o.estado, "value") else o.estado,
        "notas": o.notas,
        "total_estimado": o.total_estimado,
        "creado_en": o.creado_en.isoformat() if o.creado_en else None,
        "enviada_en": o.enviada_en.isoformat() if o.enviada_en else None,
        "recibida_en": o.recibida_en.isoformat() if o.recibida_en else None,
    }
    if include_items:
        d["items"] = [
            {
                "id": i.id,
                "producto_id": i.producto_id,
                "producto_nombre": i.producto.nombre if i.producto else None,
                "cantidad": i.cantidad,
                "precio_unitario": i.precio_unitario,
                "subtotal": i.subtotal,
            }
            for i in o.items
        ]
    return d


@router.get("")
def listar_ordenes(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        ordenes = db.query(OrdenCompra).order_by(OrdenCompra.creado_en.desc()).limit(100).all()
        return [_orden_dict(o, include_items=False) for o in ordenes]
    finally:
        db.close()


@router.post("")
def crear_orden(body: OrdenCompraIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        import random, string
        folio = "OC-" + "".join(random.choices(string.digits, k=6))
        o = OrdenCompra(
            folio=folio,
            proveedor_id=body.proveedor_id,
            proveedor_texto=body.proveedor.strip() if body.proveedor else None,
            notas=body.notas,
            usuario_id=int(payload["sub"]),
        )
        db.add(o)
        db.flush()
        total = 0.0
        for item_data in body.items:
            prod = db.query(Producto).filter(Producto.id == item_data.producto_id).first()
            if not prod:
                continue
            subtotal = item_data.cantidad * item_data.precio_unitario
            total += subtotal
            item = ItemOrdenCompra(
                orden_id=o.id,
                producto_id=item_data.producto_id,
                cantidad=item_data.cantidad,
                precio_unitario=item_data.precio_unitario,
                subtotal=subtotal,
            )
            db.add(item)
        o.total_estimado = total
        db.commit()
        db.refresh(o)
        return _orden_dict(o)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/sugerida/stock-bajo")
def orden_sugerida(payload: dict = Depends(get_current_api_user)):
    """Productos con stock <= stock_minimo para sugerir orden."""
    db = get_db_session()
    try:
        productos = db.query(Producto).filter(
            Producto.activo == True, Producto.stock <= Producto.stock_minimo
        ).all()
        return [
            {
                "producto_id": p.id,
                "nombre": p.nombre,
                "stock_actual": p.stock,
                "stock_minimo": p.stock_minimo,
                "proveedor_id": p.proveedor_id,
                "proveedor_nombre": p.proveedor.nombre if p.proveedor else None,
                "precio_compra": p.precio_compra,
                "cantidad_sugerida": max(p.stock_minimo * 2 - p.stock, p.stock_minimo),
            }
            for p in productos
        ]
    finally:
        db.close()


@router.get("/{oid}")
def obtener_orden(oid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        o = db.query(OrdenCompra).filter(OrdenCompra.id == oid).first()
        if not o:
            raise HTTPException(404, "Orden no encontrada")
        return _orden_dict(o)
    finally:
        db.close()


@router.patch("/{oid}/estado")
def cambiar_estado(oid: int, estado: str, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if estado not in EstadoOrdenCompra._value2member_map_:
        raise HTTPException(400, f"Estado inválido: {estado}")
    db = get_db_session()
    try:
        o = db.query(OrdenCompra).filter(OrdenCompra.id == oid).first()
        if not o:
            raise HTTPException(404, "Orden no encontrada")

        ya_recibida = o.estado == EstadoOrdenCompra.recibida
        o.estado = estado
        if estado == "enviada" and not o.enviada_en:
            o.enviada_en = datetime.now()
        elif estado == "recibida" and not ya_recibida:
            # Marcar "recibida" ahora sí suma stock real — antes solo cambiaba el
            # texto de estado y había que ir aparte a capturar la entrada manual.
            o.recibida_en = datetime.now()
            usuario_id = int(payload["sub"])
            for item in o.items:
                prod = db.query(Producto).filter(Producto.id == item.producto_id).first()
                if not prod:
                    continue
                stock_ant = prod.stock or 0
                prod.stock = stock_ant + item.cantidad
                db.add(Lote(
                    producto_id=prod.id,
                    cantidad=item.cantidad,
                    precio_compra=item.precio_unitario,
                ))
                db.add(MovimientoStock(
                    producto_id=prod.id,
                    tipo=TipoMovimiento.entrada,
                    cantidad=item.cantidad,
                    stock_anterior=stock_ant,
                    stock_nuevo=prod.stock,
                    usuario_id=usuario_id,
                    referencia_id=o.id,
                    referencia_tipo="orden_compra",
                    notas=f"Recepción orden {o.folio or o.id}",
                ))
        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return _orden_dict(o)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
