"""
Admin del catálogo web — gestiona ProductoWeb y CategoriaWeb.
Separado del inventario POS. Requiere token de ClienteApp con rol 'admin_web'.
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import ProductoWeb, CategoriaWeb
from app.api.routes.app_auth_routes import get_current_cliente_app

router = APIRouter()


def _require_admin_web(payload: dict):
    if payload.get("rol") not in ("admin_web", "admin"):
        raise HTTPException(status_code=403, detail="Solo administradores web")


# ─── CATEGORÍAS WEB ──────────────────────────────────────────────────────────

class CategoriaWebIn(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    orden: int = 0


@router.get("/categorias")
def listar_categorias(payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        cats = db.query(CategoriaWeb).order_by(CategoriaWeb.orden, CategoriaWeb.nombre).all()
        return [
            {"id": c.id, "nombre": c.nombre, "descripcion": c.descripcion,
             "imagen_url": c.imagen_url, "orden": c.orden, "activo": c.activo}
            for c in cats
        ]
    finally:
        db.close()


@router.post("/categorias")
def crear_categoria(body: CategoriaWebIn, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        cat = CategoriaWeb(**body.model_dump())
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return {"id": cat.id, "nombre": cat.nombre}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/categorias/{cat_id}")
def actualizar_categoria(cat_id: int, body: CategoriaWebIn, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        cat = db.query(CategoriaWeb).filter(CategoriaWeb.id == cat_id).first()
        if not cat:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        for k, v in body.model_dump().items():
            setattr(cat, k, v)
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/categorias/{cat_id}")
def eliminar_categoria(cat_id: int, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        cat = db.query(CategoriaWeb).filter(CategoriaWeb.id == cat_id).first()
        if not cat:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        cat.activo = False
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ─── PRODUCTOS WEB ────────────────────────────────────────────────────────────

class ProductoWebIn(BaseModel):
    nombre: str
    nombre_generico: Optional[str] = None
    marca: Optional[str] = None
    descripcion: Optional[str] = None
    categoria_id: Optional[int] = None
    precio: float
    precio_tachado: Optional[float] = None
    imagen_url: Optional[str] = None
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    contenido: Optional[str] = None
    requiere_receta: bool = False
    disponible: bool = True
    destacado: bool = False
    orden: int = 0


def _prod_dict(p: ProductoWeb) -> dict:
    return {
        "id":              p.id,
        "nombre":          p.nombre,
        "nombre_generico": p.nombre_generico,
        "marca":           p.marca,
        "descripcion":     p.descripcion,
        "categoria_id":    p.categoria_id,
        "categoria_nombre": p.categoria.nombre if p.categoria else None,
        "precio":          p.precio,
        "precio_tachado":  p.precio_tachado,
        "imagen_url":      p.imagen_url,
        "presentacion":    p.presentacion,
        "concentracion":   p.concentracion,
        "contenido":       p.contenido,
        "requiere_receta": p.requiere_receta,
        "disponible":      p.disponible,
        "destacado":       p.destacado,
        "orden":           p.orden,
    }


@router.get("/productos")
def listar_productos(payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        prods = (
            db.query(ProductoWeb)
            .options(joinedload(ProductoWeb.categoria))
            .order_by(ProductoWeb.orden, ProductoWeb.nombre)
            .all()
        )
        return [_prod_dict(p) for p in prods]
    finally:
        db.close()


@router.post("/productos")
def crear_producto(body: ProductoWebIn, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        prod = ProductoWeb(**body.model_dump())
        db.add(prod)
        db.commit()
        db.refresh(prod)
        return _prod_dict(prod)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.put("/productos/{prod_id}")
def actualizar_producto(prod_id: int, body: ProductoWebIn, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        prod = db.query(ProductoWeb).options(joinedload(ProductoWeb.categoria)).filter(
            ProductoWeb.id == prod_id
        ).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        for k, v in body.model_dump().items():
            setattr(prod, k, v)
        db.commit()
        db.refresh(prod)
        return _prod_dict(prod)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/productos/{prod_id}")
def eliminar_producto(prod_id: int, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    db = get_db_session()
    try:
        prod = db.query(ProductoWeb).filter(ProductoWeb.id == prod_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        prod.disponible = False
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/productos/{prod_id}/imagen")
async def subir_imagen(prod_id: int, file: UploadFile = File(...), payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    import os, tempfile
    db = get_db_session()
    try:
        prod = db.query(ProductoWeb).filter(ProductoWeb.id == prod_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            from app.services.cloudinary_service import upload_product_image
            url = upload_product_image(tmp_path, f"web_{prod_id}")
            prod.imagen_url = url
            db.commit()
            return {"imagen_url": url}
        finally:
            os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ─── PEDIDOS WEB (vista admin) ────────────────────────────────────────────────

@router.get("/pedidos")
def listar_pedidos_admin(payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    from sqlalchemy.orm import joinedload
    from app.database.models import PedidoWeb, PedidoWebItem, ClienteApp
    db = get_db_session()
    try:
        pedidos = (
            db.query(PedidoWeb)
            .options(
                joinedload(PedidoWeb.items).joinedload(PedidoWebItem.producto),
                joinedload(PedidoWeb.cliente_app),
            )
            .order_by(PedidoWeb.creado_en.desc())
            .limit(200)
            .all()
        )
        result = []
        for p in pedidos:
            result.append({
                "id":     p.id,
                "estado": p.estado.value,
                "total":  p.total,
                "cliente": {
                    "id":     p.cliente_app.id,
                    "nombre": p.cliente_app.nombre,
                    "email":  p.cliente_app.email,
                    "telefono": p.cliente_app.telefono,
                } if p.cliente_app else None,
                "direccion_entrega": p.direccion_entrega,
                "notas":    p.notas,
                "creado_en": p.creado_en.isoformat() if p.creado_en else None,
                "items": [
                    {
                        "nombre":          it.producto.nombre if it.producto else str(it.producto_id),
                        "cantidad":        it.cantidad,
                        "precio_unitario": it.precio_unitario,
                        "subtotal":        it.subtotal,
                    }
                    for it in p.items
                ],
            })
        return {"success": True, "data": result}
    finally:
        db.close()


@router.put("/pedidos/{pedido_id}/estado")
def actualizar_estado_pedido(pedido_id: int, body: dict, payload: dict = Depends(get_current_cliente_app)):
    _require_admin_web(payload)
    from app.database.models import PedidoWeb, EstadoPedidoWeb
    db = get_db_session()
    try:
        pedido = db.query(PedidoWeb).filter(PedidoWeb.id == pedido_id).first()
        if not pedido:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        nuevo_estado = body.get("estado")
        if nuevo_estado not in [e.value for e in EstadoPedidoWeb]:
            raise HTTPException(status_code=400, detail=f"Estado inválido: {nuevo_estado}")
        pedido.estado = nuevo_estado
        db.commit()
        return {"ok": True, "estado": pedido.estado.value}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
