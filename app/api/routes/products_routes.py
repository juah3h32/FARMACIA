from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
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


class ProductoResponse(BaseModel):
    id: int
    codigo_barras: Optional[str]
    nombre: str
    nombre_generico: Optional[str]
    marca: Optional[str]
    precio_venta: float
    stock: int
    stock_minimo: int
    aplica_iva: bool
    requiere_receta: bool
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    contenido: Optional[str] = None
    activo: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ProductoResponse])
def listar_productos(
    busqueda: Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    solo_activos: bool = Query(True),
    payload: dict = Depends(get_current_api_user),
):
    db = get_db_session()
    try:
        q = db.query(Producto)
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
        return q.order_by(Producto.nombre).all()
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


@router.put("/{producto_id}", response_model=ProductoResponse)
def actualizar_producto(producto_id: int, body: ProductoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Producto).filter(Producto.id == producto_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        # Check barcode uniqueness against other active products
        if body.codigo_barras:
            conflict = db.query(Producto).filter(
                Producto.codigo_barras == body.codigo_barras,
                Producto.id != producto_id,
                Producto.activo == True,
            ).first()
            if conflict:
                raise HTTPException(status_code=400, detail=f"Código de barras ya en uso por '{conflict.nombre}'")
        update_data = body.model_dump()
        update_data.pop("stock", None)  # stock is managed via lotes/entradas, never via product edit
        for k, v in update_data.items():
            setattr(p, k, v)
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


@router.get("/{producto_id}", response_model=ProductoResponse)
def obtener_producto(producto_id: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        producto = db.query(Producto).filter(Producto.id == producto_id).first()
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return producto
    finally:
        db.close()
