"""
Rutas públicas — sin autenticación.
Sirve directamente desde la tabla Producto del POS (sincronizada con Turso).
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import Producto, Categoria

router = APIRouter()


def _pub_product(p: Producto) -> dict:
    return {
        "id":              p.id,
        "nombre":          p.nombre,
        "nombre_generico": p.nombre_generico,
        "marca":           p.marca,
        "descripcion":     p.descripcion,
        "categoria_id":    p.categoria_id,
        "categoria_nombre": p.categoria.nombre if p.categoria else None,
        "precio_venta":    p.precio_venta,
        "precio_tachado":  None,
        "aplica_iva":      p.aplica_iva,
        "stock":           p.stock,
        "requiere_receta": p.requiere_receta,
        "presentacion":    p.presentacion,
        "concentracion":   p.concentracion,
        "contenido":       p.contenido,
        "imagen_url":      p.imagen_url,
        "destacado":       False,
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
        q = (
            db.query(Producto)
            .options(joinedload(Producto.categoria))
            .filter(Producto.activo == True, Producto.stock > 0)
        )
        if busqueda:
            q = q.filter(
                Producto.nombre.ilike(f"%{busqueda}%") |
                Producto.nombre_generico.ilike(f"%{busqueda}%") |
                Producto.marca.ilike(f"%{busqueda}%")
            )
        if categoria_id:
            q = q.filter(Producto.categoria_id == categoria_id)
        return [_pub_product(p) for p in q.order_by(Producto.nombre).all()]
    finally:
        db.close()


@router.get("/productos/{producto_id}")
def producto_publico(producto_id: int):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        p = (
            db.query(Producto)
            .options(joinedload(Producto.categoria))
            .filter(Producto.id == producto_id, Producto.activo == True)
            .first()
        )
        if not p:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return _pub_product(p)
    finally:
        db.close()


@router.get("/categorias")
def categorias_publicas():
    db = get_db_session()
    try:
        cats = (
            db.query(Categoria)
            .order_by(Categoria.nombre)
            .all()
        )
        return [
            {"id": c.id, "nombre": c.nombre, "imagen_url": None}
            for c in cats
        ]
    finally:
        db.close()
