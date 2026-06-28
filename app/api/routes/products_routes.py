from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks, UploadFile, File
from pydantic import BaseModel, field_validator
from typing import Optional
import os, tempfile
from app.database.connection import get_db_session
from app.database.models import Producto, Categoria
from app.api.routes.auth_routes import get_current_api_user
from sqlalchemy import func

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class ProductoIn(BaseModel):
    codigo_barras: Optional[str] = None
    nombre: str
    nombre_generico: Optional[str] = None
    marca: Optional[str] = None

    @field_validator('nombre', mode='before')
    @classmethod
    def _upper_nombre(cls, v):
        return v.strip().upper() if v else v

    @field_validator('nombre_generico', 'marca', mode='before')
    @classmethod
    def _upper_optional(cls, v):
        return v.strip().upper() if v else v
    categoria_id: Optional[int] = None
    precio_compra: float = 0.0
    precio_venta: float
    aplica_iva: bool = False
    stock: int = 0
    stock_minimo: int = 10
    requiere_receta: bool = False
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    contenido: Optional[str] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    proveedor_id: Optional[int] = None
    venta_fraccionada: bool = False
    unidades_por_caja: int = 1
    precio_pieza: float = 0.0
    unidad_pieza: Optional[str] = "pieza"
    unidad_caja: Optional[str] = "caja"
    piezas_sueltas: int = 0


class ProductoResponse(BaseModel):
    id: int
    codigo_barras: Optional[str]
    nombre: str
    nombre_generico: Optional[str]
    marca: Optional[str]
    categoria_id: Optional[int] = None
    proveedor_id: Optional[int] = None
    categoria_nombre: Optional[str] = None
    proveedor_nombre: Optional[str] = None
    precio_compra: float = 0.0
    precio_venta: float
    stock: int
    stock_minimo: int
    aplica_iva: bool
    requiere_receta: bool
    sustancia_controlada: bool = False
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    contenido: Optional[str] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    venta_fraccionada: bool = False
    unidades_por_caja: int = 1
    precio_pieza: float = 0.0
    unidad_pieza: Optional[str] = "pieza"
    unidad_caja: Optional[str] = "caja"
    piezas_sueltas: int = 0
    activo: bool

    class Config:
        from_attributes = True


def _prod_dict(p: Producto) -> dict:
    d = ProductoResponse.model_validate(p).model_dump()
    d["categoria_nombre"] = p.categoria.nombre if p.categoria else None
    d["proveedor_nombre"] = p.proveedor.nombre if p.proveedor else None
    return d


# ─── Barcode / QR helpers ─────────────────────────────────────────────────────

def _gen_barcode_img(texto: str, fmt: str):
    """Return PIL Image of barcode or QR."""
    import io
    from PIL import Image
    if fmt == "qr":
        import qrcode
        qr = qrcode.QRCode(box_size=7, border=2)
        qr.add_data(texto)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").get_image()
    else:
        import barcode as _bc
        from barcode.writer import ImageWriter
        writer = ImageWriter()
        writer.set_options({"module_height": 12, "quiet_zone": 3,
                            "font_size": 9, "text_distance": 3, "write_text": True})
        buf = io.BytesIO()
        bc_class = _bc.get_barcode_class(fmt)
        bc_obj = bc_class(texto, writer=writer)
        bc_obj.write(buf)
        buf.seek(0)
        img = Image.open(buf)
        img.load()
        return img.copy()


def _gen_label_img(nombre: str, precio: float, codigo: str, fmt: str):
    """Return PIL Image: barcode/QR + product name + price label."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    bc = _gen_barcode_img(codigo, fmt)
    lw = 420
    ratio = (lw - 20) / bc.width
    bh = max(int(bc.height * ratio), 10)
    bc = bc.resize((lw - 20, bh), Image.LANCZOS)
    label = Image.new("RGB", (lw, bh + 70), "white")
    label.paste(bc, (10, 5))
    draw = ImageDraw.Draw(label)
    try:
        f_big = ImageFont.truetype("arial.ttf", 13)
        f_sm  = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        f_big = f_sm = ImageFont.load_default()
    cx = lw // 2
    y0 = bh + 10
    nm = (nombre[:44] + "…") if len(nombre) > 44 else nombre
    draw.text((cx, y0), nm, fill="black", font=f_big, anchor="mt")
    draw.text((cx, y0 + 22), f"$ {precio:.2f}", fill="#555", font=f_sm, anchor="mt")
    return label


def _img_to_stream(img) -> "io.BytesIO":
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


@router.get("/barcode-preview")
def barcode_preview(
    texto: str = Query(...),
    tipo: str = Query("code128"),
    payload: dict = Depends(get_current_api_user),
):
    """Return PNG of barcode/QR for given text (for live preview)."""
    import io
    from fastapi.responses import StreamingResponse
    if not texto:
        raise HTTPException(status_code=400, detail="Texto vacío")
    try:
        img = _gen_barcode_img(texto.strip(), tipo)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return StreamingResponse(
        _img_to_stream(img), media_type="image/png",
        headers={"Cache-Control": "no-store"})


@router.post("/etiquetas-pdf")
def etiquetas_pdf(
    body: dict,
    bg: BackgroundTasks,
    payload: dict = Depends(get_current_api_user),
):
    """Generate PDF label sheet for given product IDs. Body: {ids:[..], tipo:'code128'}."""
    import io, os, tempfile
    from fastapi.responses import FileResponse
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader

    ids = body.get("ids", [])
    tipo = body.get("tipo", "code128")
    if not ids:
        raise HTTPException(status_code=400, detail="Sin IDs")

    db = get_db_session()
    try:
        productos = db.query(Producto).filter(
            Producto.id.in_(ids), Producto.codigo_barras != None,
            Producto.activo == True).all()
    finally:
        db.close()

    if not productos:
        raise HTTPException(status_code=400, detail="Sin productos con código")

    page_w, page_h = letter
    margin = 10 * mm
    cols, rows = 3, 8
    lw = (page_w - 2 * margin) / cols
    lh = (page_h - 2 * margin) / rows

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    c = rl_canvas.Canvas(tmp.name, pagesize=letter)
    ci, ri, first = 0, 0, True
    for p in productos:
        try:
            img = _gen_label_img(p.nombre, p.precio_venta, p.codigo_barras, tipo)
        except Exception:
            continue
        if not first and ci == 0 and ri == 0:
            c.showPage()
        first = False
        x = margin + ci * lw
        y = page_h - margin - (ri + 1) * lh
        buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
        ir = ImageReader(buf)
        iw, ih = ir.getSize()
        pad = 3 * mm
        scale = min((lw - 2*pad)/iw, (lh - 2*pad)/ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(ir, x+pad+(lw-2*pad-dw)/2, y+pad+(lh-2*pad-dh)/2, width=dw, height=dh)
        c.setStrokeColorRGB(0.85, 0.85, 0.85); c.setLineWidth(0.5)
        c.rect(x+1, y+1, lw-2, lh-2)
        ci += 1
        if ci >= cols:
            ci = 0; ri += 1
            if ri >= rows:
                ci, ri = 0, 0
    c.save()

    def _cleanup():
        try: os.unlink(tmp.name)
        except Exception: pass
    bg.add_task(_cleanup)

    return FileResponse(tmp.name, media_type="application/pdf", filename="etiquetas.pdf")


@router.get("/{producto_id}/label")
def get_product_label(
    producto_id: int,
    tipo: str = Query("code128"),
    payload: dict = Depends(get_current_api_user),
):
    """Return PNG label (barcode + name + price) for a product."""
    from fastapi.responses import StreamingResponse
    db = get_db_session()
    try:
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        if not p.codigo_barras:
            raise HTTPException(status_code=400, detail="Sin código de barras")
        nombre, precio, codigo = p.nombre, p.precio_venta, p.codigo_barras
    finally:
        db.close()
    try:
        img = _gen_label_img(nombre, precio, codigo, tipo)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return StreamingResponse(
        _img_to_stream(img), media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename=etiqueta_{producto_id}.png"})


# ─── Assign barcode ───────────────────────────────────────────────────────────

class AsignarCodigoIn(BaseModel):
    codigo_barras: str


@router.patch("/{producto_id}/barcode")
def asignar_barcode(
    producto_id: int,
    body: AsignarCodigoIn,
    bg: BackgroundTasks,
    payload: dict = Depends(get_current_api_user),
):
    """Assign barcode to a product (admin only)."""
    _require_admin(payload)
    codigo = body.codigo_barras.strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="Código vacío")
    db = get_db_session()
    try:
        dup = db.query(Producto).filter(
            Producto.codigo_barras == codigo,
            Producto.id != producto_id,
            Producto.activo == True,
        ).first()
        if dup:
            raise HTTPException(status_code=400,
                                detail=f"Código ya asignado a '{dup.nombre}'")
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        p.codigo_barras = codigo
        db.commit()
        db.refresh(p)
        _sync_bg(bg)
        return _prod_dict(p)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProductoResponse])
def listar_productos(
    busqueda: Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    solo_activos: bool = Query(True),
    payload: dict = Depends(get_current_api_user),
):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        q = db.query(Producto).options(joinedload(Producto.proveedor))
        if solo_activos:
            q = q.filter(Producto.activo == True)
        if busqueda:
            q = q.filter(
                Producto.nombre.ilike(f"%{busqueda}%") |
                Producto.codigo_barras.ilike(f"%{busqueda}%") |
                Producto.nombre_generico.ilike(f"%{busqueda}%") |
                Producto.marca.ilike(f"%{busqueda}%")
            )
        if categoria_id:
            q = q.filter(Producto.categoria_id == categoria_id)
        return [_prod_dict(p) for p in q.order_by(Producto.nombre).all()]
    finally:
        db.close()


@router.get("/categorias")
def listar_categorias(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        cats = db.query(Categoria).order_by(Categoria.nombre).all()
        return [{"id": c.id, "nombre": c.nombre} for c in cats]
    finally:
        db.close()


def _sync_bg(bg: BackgroundTasks):
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        from app.database.sync_service import sync_to_turso
        bg.add_task(sync_to_turso)


@router.post("/", response_model=ProductoResponse)
def crear_producto(body: ProductoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        if body.codigo_barras:
            # Rechazar si ya hay un producto ACTIVO con ese barcode
            activo = db.query(Producto).filter(
                Producto.codigo_barras == body.codigo_barras,
                Producto.activo == True,
            ).first()
            if activo:
                raise HTTPException(status_code=400, detail=f"Código de barras ya registrado en '{activo.nombre}'")
            # Limpiar barcode de productos INACTIVOS que lo tengan (libera el UNIQUE constraint)
            db.query(Producto).filter(
                Producto.codigo_barras == body.codigo_barras,
                Producto.activo == False,
            ).update({"codigo_barras": None})
        p = Producto(**body.model_dump())
        if p.venta_fraccionada and (p.stock or 0) > 0 and (p.piezas_sueltas or 0) == 0:
            p.piezas_sueltas = p.unidades_por_caja or 1
            p.stock = max(0, p.stock - 1)
        db.add(p)
        db.commit()
        db.refresh(p)
        _sync_bg(bg)
        return p
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{producto_id}", response_model=ProductoResponse)
def obtener_producto(producto_id: int, payload: dict = Depends(get_current_api_user)):
    from sqlalchemy.orm import joinedload
    db = get_db_session()
    try:
        p = db.query(Producto).options(joinedload(Producto.proveedor)).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        return _prod_dict(p)
    finally:
        db.close()


@router.put("/{producto_id}", response_model=ProductoResponse)
def actualizar_producto(producto_id: int, body: ProductoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        if body.codigo_barras and body.codigo_barras != p.codigo_barras:
            conflicto = db.query(Producto).filter(
                Producto.codigo_barras == body.codigo_barras,
                Producto.activo == True,
                Producto.id != producto_id,
            ).first()
            if conflicto:
                raise HTTPException(status_code=400, detail=f"Código de barras ya registrado en '{conflicto.nombre}'")
            db.query(Producto).filter(
                Producto.codigo_barras == body.codigo_barras,
                Producto.activo == False,
            ).update({"codigo_barras": None})
        from datetime import datetime as _dt_now
        was_fraccionada = p.venta_fraccionada
        for k, v in body.model_dump(exclude={'stock', 'imagen_url', 'piezas_sueltas'}).items():
            setattr(p, k, v)
        p.actualizado_en = _dt_now.now()  # guarantee bump so sync CASE WHEN keeps local
        if p.venta_fraccionada and not was_fraccionada and (p.stock or 0) > 0 and (p.piezas_sueltas or 0) == 0:
            p.piezas_sueltas = p.unidades_por_caja or 1
            p.stock = max(0, p.stock - 1)
        db.commit()
        db.refresh(p)
        _sync_bg(bg)
        return p
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{producto_id}")
def eliminar_producto(producto_id: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        p.activo = False
        p.codigo_barras = None   # libera el constraint UNIQUE para reutilizar el código
        db.commit()
        _sync_bg(bg)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class AjusteStockIn(BaseModel):
    nuevo_stock: int
    nuevo_piezas_sueltas: Optional[int] = None


@router.post("/{producto_id}/ajustar-stock")
def ajustar_stock(producto_id: int, body: AjusteStockIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if body.nuevo_stock < 0:
        raise HTTPException(status_code=400, detail="El stock no puede ser negativo")
    db = get_db_session()
    try:
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        stock_ant = p.stock
        p.stock = body.nuevo_stock
        if body.nuevo_piezas_sueltas is not None and p.venta_fraccionada:
            p.piezas_sueltas = max(0, body.nuevo_piezas_sueltas)
        from app.database.models import MovimientoStock, TipoMovimiento
        notas = f"Ajuste manual: {stock_ant} → {body.nuevo_stock}"
        if body.nuevo_piezas_sueltas is not None and p.venta_fraccionada:
            notas += f" | piezas sueltas: {p.piezas_sueltas}"
        db.add(MovimientoStock(
            producto_id=p.id,
            tipo=TipoMovimiento.ajuste,
            cantidad=abs(body.nuevo_stock - stock_ant),
            stock_anterior=stock_ant,
            stock_nuevo=body.nuevo_stock,
            usuario_id=int(payload["sub"]),
            notas=notas,
        ))
        db.commit()
        _sync_bg(bg)
        return {"ok": True, "stock_anterior": stock_ant, "stock_nuevo": p.stock, "piezas_sueltas": p.piezas_sueltas}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{producto_id}/imagen")
async def subir_imagen_producto(
    producto_id: int,
    file: UploadFile = File(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        prod = db.query(Producto).filter(Producto.id == producto_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            from app.services.cloudinary_service import upload_product_image
            url = upload_product_image(tmp_path, producto_id)
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


@router.get("/barcode/{codigo}")
def buscar_por_barcode(codigo: str, payload: dict = Depends(get_current_api_user)):
    from datetime import date
    from app.database.models import Lote
    db = get_db_session()
    try:
        producto = db.query(Producto).filter(
            Producto.codigo_barras == codigo,
            Producto.activo == True,
        ).first()
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        hoy = date.today()
        lotes_disp = db.query(Lote).filter(
            Lote.producto_id == producto.id,
            Lote.cantidad > 0,
        ).all()
        if lotes_disp:
            todos_vencidos = all(
                l.fecha_vencimiento is not None and l.fecha_vencimiento < hoy
                for l in lotes_disp
            )
            if todos_vencidos:
                fecha_ult = max(l.fecha_vencimiento for l in lotes_disp)
                raise HTTPException(
                    status_code=409,
                    detail=f"PRODUCTO VENCIDO — {producto.nombre} (venció: {fecha_ult.strftime('%d/%m/%Y')})",
                )

        return ProductoResponse.model_validate(producto)
    finally:
        db.close()



