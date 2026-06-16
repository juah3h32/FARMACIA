"""
Rutas públicas — sin autenticación.
Catálogo web/app de Farmacia Eben-Ezer (ProductoWeb, separado del POS).
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import ProductoWeb, CategoriaWeb

router = APIRouter()


def _pub_product(p: ProductoWeb) -> dict:
    return {
        "id":              p.id,
        "nombre":          p.nombre,
        "nombre_generico": p.nombre_generico,
        "marca":           p.marca,
        "descripcion":     p.descripcion,
        "categoria_id":    p.categoria_id,
        "categoria_nombre": p.categoria.nombre if p.categoria else None,
        "precio_venta":    p.precio,
        "precio_tachado":  p.precio_tachado,
        "aplica_iva":      False,
        "stock":           None,
        "requiere_receta": p.requiere_receta,
        "presentacion":    p.presentacion,
        "concentracion":   p.concentracion,
        "contenido":       p.contenido,
        "imagen_url":      p.imagen_url,
        "destacado":       p.destacado,
    }


@router.get("/productos")
def productos_publicos(
    busqueda:     Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    destacados:   bool          = Query(False),
):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        q = db.query(ProductoWeb).options(joinedload(ProductoWeb.categoria)).filter(
            ProductoWeb.disponible == True,
        )
        if busqueda:
            q = q.filter(
                ProductoWeb.nombre.ilike(f"%{busqueda}%") |
                ProductoWeb.nombre_generico.ilike(f"%{busqueda}%") |
                ProductoWeb.marca.ilike(f"%{busqueda}%")
            )
        if categoria_id:
            q = q.filter(ProductoWeb.categoria_id == categoria_id)
        if destacados:
            q = q.filter(ProductoWeb.destacado == True)
        return [_pub_product(p) for p in q.order_by(ProductoWeb.orden, ProductoWeb.nombre).all()]
    finally:
        db.close()


@router.get("/productos/{producto_id}")
def producto_publico(producto_id: int):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        p = db.query(ProductoWeb).options(joinedload(ProductoWeb.categoria)).filter(
            ProductoWeb.id == producto_id,
            ProductoWeb.disponible == True,
        ).first()
        if not p:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return _pub_product(p)
    finally:
        db.close()


@router.get("/categorias")
def categorias_publicas():
    db = get_db_session()
    try:
        cats = db.query(CategoriaWeb).filter(
            CategoriaWeb.activo == True,
        ).order_by(CategoriaWeb.orden, CategoriaWeb.nombre).all()
        return [
            {"id": c.id, "nombre": c.nombre, "imagen_url": c.imagen_url}
            for c in cats
        ]
    finally:
        db.close()
