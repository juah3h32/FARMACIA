"""
Pedidos desde la app móvil/web de clientes.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from app.database.connection import get_db_session
from app.database.models import PedidoWeb, PedidoWebItem, ProductoWeb, EstadoPedidoWeb
from app.api.routes.app_auth_routes import get_current_cliente_app

router = APIRouter()


class ItemPedidoIn(BaseModel):
    producto_id: int
    cantidad: int


class PedidoIn(BaseModel):
    items: List[ItemPedidoIn]
    direccion_entrega: Optional[str] = None
    notas: Optional[str] = None


def _pedido_dict(pedido: PedidoWeb) -> dict:
    return {
        "id":                pedido.id,
        "estado":            pedido.estado.value,
        "total":             pedido.total,
        "direccion_entrega": pedido.direccion_entrega,
        "notas":             pedido.notas,
        "creado_en":         pedido.creado_en.isoformat() if pedido.creado_en else None,
        "items": [
            {
                "producto_id":     it.producto_id,
                "nombre":          it.producto.nombre if it.producto else str(it.producto_id),
                "imagen_url":      it.producto.imagen_url if it.producto else None,
                "cantidad":        it.cantidad,
                "precio_unitario": it.precio_unitario,
                "subtotal":        it.subtotal,
            }
            for it in pedido.items
        ],
    }


@router.post("/")
def crear_pedido(body: PedidoIn, payload: dict = Depends(get_current_cliente_app)):
    if not body.items:
        raise HTTPException(status_code=400, detail="El pedido no tiene items")
    db = get_db_session()
    try:
        total = 0.0
        items_data = []
        for it in body.items:
            if it.cantidad <= 0:
                raise HTTPException(status_code=400, detail=f"Cantidad inválida para producto {it.producto_id}")
            prod = db.query(ProductoWeb).filter(
                ProductoWeb.id == it.producto_id,
                ProductoWeb.disponible == True,
            ).first()
            if not prod:
                raise HTTPException(status_code=404, detail=f"Producto {it.producto_id} no encontrado")
            subtotal = round(prod.precio * it.cantidad, 2)
            total += subtotal
            items_data.append((prod, it.cantidad, prod.precio, subtotal))

        pedido = PedidoWeb(
            cliente_app_id=int(payload["sub"]),
            total=round(total, 2),
            direccion_entrega=body.direccion_entrega,
            notas=body.notas,
        )
        db.add(pedido)
        db.flush()
        for prod, qty, precio, subtotal in items_data:
            db.add(PedidoWebItem(
                pedido_id=pedido.id,
                producto_id=prod.id,
                cantidad=qty,
                precio_unitario=precio,
                subtotal=subtotal,
            ))
        db.commit()
        db.refresh(pedido)
        return {"success": True, "data": _pedido_dict(pedido)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/")
def listar_pedidos(payload: dict = Depends(get_current_cliente_app)):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        pedidos = (
            db.query(PedidoWeb)
            .options(joinedload(PedidoWeb.items).joinedload(PedidoWebItem.producto))
            .filter(PedidoWeb.cliente_app_id == int(payload["sub"]))
            .order_by(PedidoWeb.creado_en.desc())
            .all()
        )
        return {"success": True, "data": [_pedido_dict(p) for p in pedidos]}
    finally:
        db.close()


@router.get("/{pedido_id}")
def obtener_pedido(pedido_id: int, payload: dict = Depends(get_current_cliente_app)):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        pedido = (
            db.query(PedidoWeb)
            .options(joinedload(PedidoWeb.items).joinedload(PedidoWebItem.producto))
            .filter(
                PedidoWeb.id == pedido_id,
                PedidoWeb.cliente_app_id == int(payload["sub"]),
            ).first()
        )
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        return {"success": True, "data": _pedido_dict(pedido)}
    finally:
        db.close()
