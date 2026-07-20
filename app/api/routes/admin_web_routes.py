"""
Admin de la app web — edita directamente la tabla Producto del POS (misma
fuente que /api/public/productos), para que los cambios se vean sin sync.
Requiere token de ClienteApp con rol 'admin' o 'admin_web'.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Producto
from app.api.routes.app_auth_routes import get_current_cliente_app

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") not in ("admin", "admin_web"):
        raise HTTPException(status_code=403, detail="Solo administradores")


def _product_dict(p: Producto) -> dict:
    return {
        "id":             p.id,
        "name":           p.nombre,
        "category":       p.categoria.nombre if p.categoria else "Sin categoría",
        "price":          p.precio_venta,
        "unit":           p.unidad_pieza or "pieza",
        "stock":          p.stock,
        "active":         p.activo,
        "reserved":       0,
        "real_available": p.stock,
        "precio_tachado": p.precio_tachado,
        "destacado":      bool(p.destacado),
    }


@router.get("/products")
def listar_productos(payload: dict = Depends(get_current_cliente_app)):
    _require_admin(payload)
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        prods = (
            db.query(Producto)
            .options(joinedload(Producto.categoria))
            .order_by(Producto.nombre)
            .all()
        )
        return {"success": True, "data": [_product_dict(p) for p in prods]}
    finally:
        db.close()


class ProductUpdateIn(BaseModel):
    stock: Optional[int] = None
    active: Optional[bool] = None
    price: Optional[float] = None
    precio_tachado: Optional[float] = None
    destacado: Optional[bool] = None


@router.put("/products/{producto_id}")
def actualizar_producto(producto_id: int, body: ProductUpdateIn, payload: dict = Depends(get_current_cliente_app)):
    _require_admin(payload)
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        p = (
            db.query(Producto)
            .options(joinedload(Producto.categoria))
            .filter(Producto.id == producto_id)
            .first()
        )
        if not p:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        if body.stock is not None:
            p.stock = body.stock
        if body.active is not None:
            p.activo = body.active
        if body.price is not None:
            p.precio_venta = body.price
        if body.precio_tachado is not None:
            p.precio_tachado = body.precio_tachado if body.precio_tachado > 0 else None
        if body.destacado is not None:
            p.destacado = body.destacado
        db.commit()
        db.refresh(p)
        return {"success": True, "data": _product_dict(p)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
