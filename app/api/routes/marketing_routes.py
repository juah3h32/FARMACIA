"""
Marketing API — genera PDF catálogo e imágenes promo.
Solo acceso admin.
"""
import io
import os
import tempfile
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


# ── PDF catálogo ──────────────────────────────────────────────────────────────

@router.get("/pdf")
def generar_catalogo_pdf(
    filtro:      str  = Query("todos",  description="todos | activos | stock"),
    orden:       str  = Query("nombre", description="nombre | precio_asc | precio_desc | stock | categoria"),
    inc_stock:   bool = Query(True),
    inc_barcode: bool = Query(True),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Producto
    from sqlalchemy.orm import joinedload

    db = get_db_session()
    try:
        q = db.query(Producto).options(
            joinedload(Producto.categoria),
            joinedload(Producto.proveedor),
        )
        if filtro == "activos":
            q = q.filter(Producto.activo.is_(True))
        elif filtro == "stock":
            q = q.filter(Producto.activo.is_(True), Producto.stock > 0)
        elif filtro == "sin_stock":
            q = q.filter(Producto.activo.is_(True), Producto.stock <= 0)
        prods = q.order_by(Producto.nombre).all()

        if orden == "precio_asc":
            prods.sort(key=lambda p: p.precio_venta)
        elif orden == "precio_desc":
            prods.sort(key=lambda p: p.precio_venta, reverse=True)
        elif orden == "stock":
            prods.sort(key=lambda p: p.stock)
        elif orden == "categoria":
            prods.sort(key=lambda p: (p.categoria.nombre if p.categoria else "").lower())
        else:
            prods.sort(key=lambda p: p.nombre.lower())

        from app.ui.marketing_screen import _generar_pdf_reportlab

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.close()
        try:
            _generar_pdf_reportlab(prods, tmp.name, inc_stock, inc_barcode)
            with open(tmp.name, "rb") as f:
                data = f.read()
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

        ts = datetime.now().strftime("%Y%m%d_%H%M")
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="Catalogo_Farmacia_{ts}.pdf"'},
        )
    finally:
        db.close()


# ── Manual de Usuario PDF ────────────────────────────────────────────────────

@router.get("/manual-pdf")
def generar_manual(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from app.ui.marketing_screen import generar_manual_pdf

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    try:
        generar_manual_pdf(tmp.name)
        with open(tmp.name, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    ts = datetime.now().strftime("%Y%m%d")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Manual_FarmaciaPos_v{ts}.pdf"'},
    )


# ── Imagen promo ──────────────────────────────────────────────────────────────

class PromoImageIn(BaseModel):
    producto_id:       int
    precio_promo:      float
    precio_tachado:    Optional[float] = None
    texto_extra:       str = ""
    dia_oferta:        str = ""
    usar_imagen:       bool = False
    descripcion_promo: str = ""


@router.post("/promo-image")
def generar_promo_image(
    body: PromoImageIn,
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Producto
    from sqlalchemy.orm import joinedload
    from app.ui.marketing_screen import _generar_imagen_promo

    db = get_db_session()
    try:
        prod = db.query(Producto).options(
            joinedload(Producto.categoria)
        ).filter(Producto.id == body.producto_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        precio_tachado = body.precio_tachado if body.precio_tachado else body.precio_promo + 5
        usar_imagen    = body.usar_imagen and bool(prod.imagen_url)

        img = _generar_imagen_promo(
            producto=prod,
            precio_promo=body.precio_promo,
            precio_tachado=precio_tachado,
            texto_extra=body.texto_extra,
            dia_oferta=body.dia_oferta,
            usar_imagen=usar_imagen,
            descripcion_promo=body.descripcion_promo,
        )

        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="promo.png"'},
        )
    finally:
        db.close()


class PromoImageComboIn(BaseModel):
    producto_ids:      list[int]
    precio_paquete:    float
    texto_extra:       str = ""
    dia_oferta:        str = ""
    descripcion_promo: str = ""


@router.post("/promo-image-combo")
def generar_promo_image_combo(
    body: PromoImageComboIn,
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    from app.database.connection import get_db_session
    from app.database.models import Producto
    from app.ui.marketing_screen import _generar_imagen_promo_combo

    if len(body.producto_ids) < 2:
        raise HTTPException(status_code=400, detail="Elige al menos 2 productos para el paquete")

    db = get_db_session()
    try:
        productos = db.query(Producto).filter(Producto.id.in_(body.producto_ids)).all()
        if len(productos) != len(set(body.producto_ids)):
            raise HTTPException(status_code=404, detail="Alguno de los productos no existe")
        # conserva el orden en que el usuario los eligió
        by_id = {p.id: p for p in productos}
        productos_ordenados = [by_id[pid] for pid in dict.fromkeys(body.producto_ids)]

        img = _generar_imagen_promo_combo(
            productos=productos_ordenados,
            precio_paquete=body.precio_paquete,
            texto_extra=body.texto_extra,
            dia_oferta=body.dia_oferta,
            descripcion_promo=body.descripcion_promo,
        )

        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="promo_combo.png"'},
        )
    finally:
        db.close()
