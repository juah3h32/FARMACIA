from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta, datetime
from app.database.connection import get_db_session
from app.database.models import Producto, Lote, MovimientoStock, TipoMovimiento
from app.api.routes.auth_routes import get_current_api_user
import app.config as cfg


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class EntradaStockIn(BaseModel):
    producto_id: int
    cantidad: int
    numero_lote: Optional[str] = None
    fecha_vencimiento: Optional[str] = None   # "DD/MM/YYYY" or "YYYY-MM-DD"
    precio_compra: float = 0.0


class BajaLoteIn(BaseModel):
    lote_id: int
    cantidad: int                 # partial or full write-off
    motivo: str = "vencimiento"   # vencimiento | dano | robo | ajuste


class AjusteFisicoIn(BaseModel):
    producto_id: int
    stock_fisico: int             # actual physical count
    notas: str = ""


router = APIRouter()


@router.get("/")
def inventario_general(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        productos = db.query(Producto).filter(Producto.activo == True).all()
        return [
            {
                "id": p.id,
                "codigo_barras": p.codigo_barras,
                "nombre": p.nombre,
                "stock": p.stock,
                "stock_minimo": p.stock_minimo,
                "precio_venta": p.precio_venta,
                "alerta_stock_bajo": p.stock <= p.stock_minimo,
            }
            for p in productos
        ]
    finally:
        db.close()


@router.get("/stock-bajo")
def stock_bajo(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        productos = db.query(Producto).filter(
            Producto.activo == True,
            Producto.stock <= Producto.stock_minimo,
        ).all()
        return [
            {"id": p.id, "nombre": p.nombre, "stock": p.stock, "stock_minimo": p.stock_minimo}
            for p in productos
        ]
    finally:
        db.close()


@router.get("/por-vencer")
def por_vencer(
    dias: int = Query(30),
    payload: dict = Depends(get_current_api_user),
):
    db = get_db_session()
    try:
        limite = date.today() + timedelta(days=dias)
        lotes = db.query(Lote).filter(
            Lote.fecha_vencimiento <= limite,
            Lote.fecha_vencimiento >= date.today(),
            Lote.cantidad > 0,
        ).all()
        return [
            {
                "lote_id": l.id,
                "producto_id": l.producto_id,
                "producto": l.producto.nombre if l.producto else "",
                "numero_lote": l.numero_lote,
                "fecha_vencimiento": l.fecha_vencimiento.isoformat() if l.fecha_vencimiento else None,
                "cantidad": l.cantidad,
            }
            for l in lotes
        ]
    finally:
        db.close()


@router.post("/entrada")
def registrar_entrada(body: EntradaStockIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        prod = db.query(Producto).filter(Producto.id == body.producto_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        stock_ant = prod.stock
        prod.stock += body.cantidad

        fecha_venc = None
        if body.fecha_vencimiento:
            import calendar as _cal
            for fmt in ("%m/%Y", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(body.fecha_vencimiento, fmt)
                    if fmt == "%m/%Y":
                        last = _cal.monthrange(parsed.year, parsed.month)[1]
                        fecha_venc = date(parsed.year, parsed.month, last)
                    else:
                        fecha_venc = parsed.date()
                    break
                except ValueError:
                    continue

        lote = Lote(
            producto_id=prod.id,
            numero_lote=body.numero_lote or None,
            fecha_vencimiento=fecha_venc,
            cantidad=body.cantidad,
            precio_compra=body.precio_compra,
        )
        db.add(lote)

        mov = MovimientoStock(
            producto_id=prod.id,
            tipo=TipoMovimiento.entrada,
            cantidad=body.cantidad,
            stock_anterior=stock_ant,
            stock_nuevo=prod.stock,
            usuario_id=int(payload["sub"]),
            notas=f"Lote: {body.numero_lote or 'S/N'}",
        )
        db.add(mov)
        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)

        return {"ok": True, "stock_nuevo": prod.stock, "producto": prod.nombre}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/lotes/{producto_id}")
def lotes_producto(producto_id: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        hoy = date.today()
        alerta = hoy + timedelta(days=cfg.EXPIRY_ALERT_DAYS)
        lotes = (
            db.query(Lote)
            .filter(Lote.producto_id == producto_id)
            .order_by(Lote.fecha_vencimiento)
            .all()
        )
        result = []
        for l in lotes:
            fv = l.fecha_vencimiento
            if fv:
                dias = (fv - hoy).days
                if fv < hoy:
                    estado = "vencido"
                elif fv <= alerta:
                    estado = "por_vencer"
                else:
                    estado = "vigente"
            else:
                dias = None
                estado = "sin_fecha"
            result.append({
                "id":                l.id,
                "numero_lote":       l.numero_lote or "",
                "fecha_vencimiento": fv.isoformat() if fv else None,
                "cantidad":          l.cantidad,
                "precio_compra":     l.precio_compra,
                "dias_restantes":    dias,
                "estado":            estado,
            })
        return result
    finally:
        db.close()


@router.get("/alertas-caducidad")
def alertas_caducidad(payload: dict = Depends(get_current_api_user)):
    """
    Returns expired + expiring lotes for all authenticated users.
    - vencidos: fecha_vencimiento < today
    - criticos: expires within 30 days
    - proximos: expires within 31-90 days
    """
    db = get_db_session()
    try:
        hoy = date.today()
        lim_critico = hoy + timedelta(days=30)
        lim_proximo = hoy + timedelta(days=90)

        lotes = (
            db.query(Lote)
            .join(Producto, Lote.producto_id == Producto.id)
            .filter(
                Producto.activo == True,
                Lote.cantidad > 0,
                Lote.fecha_vencimiento != None,
                Lote.fecha_vencimiento <= lim_proximo,
            )
            .order_by(Lote.fecha_vencimiento)
            .all()
        )

        items = []
        vencidos = criticos = proximos = 0
        for l in lotes:
            fv = l.fecha_vencimiento
            dias_rest = (fv - hoy).days
            if fv < hoy:
                estado = "vencido"
                vencidos += 1
            elif fv <= lim_critico:
                estado = "critico"
                criticos += 1
            else:
                estado = "proximo"
                proximos += 1
            items.append({
                "lote_id":           l.id,
                "producto_id":       l.producto_id,
                "producto":          l.producto.nombre if l.producto else "",
                "numero_lote":       l.numero_lote or "",
                "fecha_vencimiento": fv.isoformat(),
                "cantidad":          l.cantidad,
                "dias_restantes":    dias_rest,
                "estado":            estado,
            })

        return {
            "total":    len(items),
            "vencidos": vencidos,
            "criticos": criticos,
            "proximos": proximos,
            "items":    items,
        }
    finally:
        db.close()


@router.get("/movimientos")
def movimientos_stock(
    producto_id: int = Query(None),
    limite: int = Query(100),
    payload: dict = Depends(get_current_api_user),
):
    if payload.get("rol") != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Solo administradores")
    db = get_db_session()
    try:
        q = db.query(MovimientoStock)
        if producto_id:
            q = q.filter(MovimientoStock.producto_id == producto_id)
        movimientos = q.order_by(MovimientoStock.creado_en.desc()).limit(limite).all()
        return [
            {
                "id": m.id,
                "producto_id": m.producto_id,
                "producto": m.producto.nombre if m.producto else "",
                "tipo": m.tipo.value,
                "cantidad": m.cantidad,
                "stock_anterior": m.stock_anterior,
                "stock_nuevo": m.stock_nuevo,
                "creado_en": m.creado_en.isoformat() if m.creado_en else None,
            }
            for m in movimientos
        ]
    finally:
        db.close()


@router.post("/baja-lote")
def dar_baja_lote(body: BajaLoteIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Write off (merma) a lote — partial or full. Admin only."""
    _require_admin(payload)
    if body.cantidad <= 0:
        raise HTTPException(status_code=400, detail="Cantidad debe ser mayor a 0")
    db = get_db_session()
    try:
        lote = db.query(Lote).filter(Lote.id == body.lote_id).first()
        if not lote:
            raise HTTPException(status_code=404, detail="Lote no encontrado")
        if body.cantidad > lote.cantidad:
            raise HTTPException(status_code=400, detail=f"Solo hay {lote.cantidad} unidades en este lote")

        prod = db.query(Producto).filter(Producto.id == lote.producto_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        stock_ant = prod.stock
        prod.stock = max(0, prod.stock - body.cantidad)
        lote.cantidad -= body.cantidad

        db.add(MovimientoStock(
            producto_id=prod.id,
            tipo=TipoMovimiento.ajuste,
            cantidad=body.cantidad,
            stock_anterior=stock_ant,
            stock_nuevo=prod.stock,
            usuario_id=int(payload["sub"]),
            notas=f"MERMA — Lote {lote.numero_lote or lote.id} · Motivo: {body.motivo}",
        ))
        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)

        return {
            "ok": True,
            "lote_id": lote.id,
            "cantidad_dada_baja": body.cantidad,
            "cantidad_restante": lote.cantidad,
            "stock_nuevo": prod.stock,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/ajuste-fisico")
def ajuste_fisico(body: AjusteFisicoIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Physical count adjustment. Records discrepancy and corrects system stock. Admin only."""
    _require_admin(payload)
    if body.stock_fisico < 0:
        raise HTTPException(status_code=400, detail="Stock físico no puede ser negativo")
    db = get_db_session()
    try:
        prod = db.query(Producto).filter(Producto.id == body.producto_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        diferencia = body.stock_fisico - prod.stock
        if diferencia == 0:
            return {"ok": True, "diferencia": 0, "mensaje": "Sin diferencia — stock correcto"}

        stock_ant = prod.stock
        prod.stock = body.stock_fisico

        db.add(MovimientoStock(
            producto_id=prod.id,
            tipo=TipoMovimiento.ajuste,
            cantidad=abs(diferencia),
            stock_anterior=stock_ant,
            stock_nuevo=prod.stock,
            usuario_id=int(payload["sub"]),
            notas=f"AJUSTE FÍSICO · {'Sobrante' if diferencia > 0 else 'Faltante'} {abs(diferencia)} uds. {body.notas}".strip(),
        ))
        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)

        return {
            "ok": True,
            "producto": prod.nombre,
            "stock_anterior": stock_ant,
            "stock_nuevo": prod.stock,
            "diferencia": diferencia,
            "tipo": "sobrante" if diferencia > 0 else "faltante",
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/resumen-inventario")
def resumen_inventario(payload: dict = Depends(get_current_api_user)):
    """
    KPI snapshot for inventory dashboard:
    total SKUs, stock value, low-stock count, expiry risk value.
    """
    db = get_db_session()
    try:
        from datetime import date, timedelta
        hoy = date.today()
        critico = hoy + timedelta(days=30)
        proximo = hoy + timedelta(days=90)

        productos = db.query(Producto).filter(Producto.activo == True).all()
        total_skus    = len(productos)
        valor_venta   = sum(p.stock * p.precio_venta for p in productos)
        valor_costo   = sum(p.stock * (p.precio_compra or 0) for p in productos)
        ganancia_est  = valor_venta - valor_costo
        bajo_stock    = sum(1 for p in productos if p.stock <= p.stock_minimo)
        sin_stock     = sum(1 for p in productos if p.stock <= 0)

        lotes_act = db.query(Lote).filter(
            Lote.cantidad > 0, Lote.fecha_vencimiento != None
        ).all()
        valor_vencido = 0.0
        valor_critico = 0.0
        for l in lotes_act:
            prod = next((p for p in productos if p.id == l.producto_id), None)
            if not prod:
                continue
            val = l.cantidad * prod.precio_venta
            if l.fecha_vencimiento < hoy:
                valor_vencido += val
            elif l.fecha_vencimiento <= critico:
                valor_critico += val

        es_admin = payload.get("rol") == "admin"
        result = {
            "total_skus": total_skus,
            "bajo_stock":  bajo_stock,
            "sin_stock":   sin_stock,
        }
        if es_admin:
            result["valor_venta"]   = round(valor_venta, 2)
            result["valor_costo"]   = round(valor_costo, 2)
            result["ganancia_est"]  = round(ganancia_est, 2)
            result["valor_vencido"] = round(valor_vencido, 2)
            result["valor_critico"] = round(valor_critico, 2)
        return result
    finally:
        db.close()
