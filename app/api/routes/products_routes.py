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
                Producto.nombre_generico.ilike(f"%{busqueda}%")
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



