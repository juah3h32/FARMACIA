from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta, datetime
from app.database.connection import get_db_session
from sqlalchemy import func
from app.database.models import Producto, Lote, MovimientoStock, TipoMovimiento, ItemVenta, Venta, EstadoVenta
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

        # Aggregation queries (each uses a fresh query — no shared Query object)
        total_skus  = db.query(Producto).filter(Producto.activo == True).count()
        bajo_stock  = db.query(Producto).filter(Producto.activo == True, Producto.stock <= Producto.stock_minimo).count()
        sin_stock   = db.query(Producto).filter(Producto.activo == True, Producto.stock <= 0).count()
        valor_venta = db.query(func.sum(Producto.stock * Producto.precio_venta)).filter(Producto.activo == True).scalar() or 0.0
        valor_costo = db.query(func.sum(Producto.stock * func.coalesce(Producto.precio_compra, 0))).filter(Producto.activo == True).scalar() or 0.0
        ganancia_est = valor_venta - valor_costo

        # Single query with joinedload — no N+1
        from sqlalchemy.orm import joinedload as _jl
        lotes_act = (
            db.query(Lote)
            .join(Producto, Lote.producto_id == Producto.id)
            .options(_jl(Lote.producto))
            .filter(Lote.cantidad > 0, Lote.fecha_vencimiento != None, Producto.activo == True)
            .all()
        )
        valor_vencido = 0.0
        valor_critico = 0.0
        for l in lotes_act:
            if not l.producto:
                continue
            val = l.cantidad * l.producto.precio_venta
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


@router.get("/auditoria-stock")
def auditoria_stock(payload: dict = Depends(get_current_api_user)):
    """
    Por cada producto: compara unidades vendidas (ItemVenta) vs salidas en MovimientoStock.
    Devuelve lista de discrepancias donde la diferencia != 0.
    """
    _require_admin(payload)
    db = get_db_session()
    try:
        # Total vendido por producto (sum of ItemVenta.cantidad en ventas completadas)
        ventas_q = (
            db.query(ItemVenta.producto_id, func.sum(ItemVenta.cantidad).label("total_vendido"))
            .join(Venta, ItemVenta.venta_id == Venta.id)
            .filter(Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True))
            .group_by(ItemVenta.producto_id)
            .all()
        )
        vendido_map = {r.producto_id: r.total_vendido for r in ventas_q}

        # Total salidas por producto (tipo=salida: includes venta + auditoria_correccion)
        mov_q = (
            db.query(MovimientoStock.producto_id, func.sum(MovimientoStock.cantidad).label("total_salidas"))
            .filter(MovimientoStock.tipo == TipoMovimiento.salida)
            .group_by(MovimientoStock.producto_id)
            .all()
        )
        salidas_map = {r.producto_id: r.total_salidas for r in mov_q}

        # Todos los productos que aparecen en alguna venta
        todos_ids = set(vendido_map) | set(salidas_map)
        productos = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(todos_ids)).all()}

        resultado = []
        for pid in todos_ids:
            vendido = vendido_map.get(pid, 0)
            salidas = salidas_map.get(pid, 0)
            diferencia = vendido - salidas
            prod = productos.get(pid)
            resultado.append({
                "producto_id":   pid,
                "nombre":        prod.nombre if prod else f"ID {pid}",
                "stock_actual":  prod.stock if prod else None,
                "piezas_sueltas": prod.piezas_sueltas if prod else None,
                "vendido":       vendido,
                "mov_salidas":   salidas,
                "diferencia":    diferencia,
                "ok":            diferencia == 0,
            })

        # Sort: discrepancias primero
        resultado.sort(key=lambda x: (x["ok"], -abs(x["diferencia"])))
        return {
            "total": len(resultado),
            "con_discrepancia": sum(1 for r in resultado if not r["ok"]),
            "items": resultado,
        }
    finally:
        db.close()


@router.post("/pull-nube")
def pull_desde_nube(payload: dict = Depends(get_current_api_user)):
    """Trigger a Turso → local sync in background. Returns immediately."""
    import threading as _t
    import app.config as _cfg
    if _cfg.TURSO_SYNC:
        from app.database.sync_service import sync_from_turso
        _t.Thread(target=sync_from_turso, daemon=True, name="PullNube").start()
    return {"ok": True}


import math as _math

@router.post("/corregir-audit")
def corregir_audit(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """
    Reconcile actual stock against sales history.
    For each product where (items_venta sold) > (all tipo=salida movements):
      - Deducts the difference from prod.stock / piezas_sueltas
      - Creates a correction MovimientoStock entry for audit trail + Turso sync
    """
    _require_admin(payload)
    db = get_db_session()
    try:
        ventas_q = (
            db.query(ItemVenta.producto_id, func.sum(ItemVenta.cantidad).label("tv"))
            .join(Venta, ItemVenta.venta_id == Venta.id)
            .filter(Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True))
            .group_by(ItemVenta.producto_id)
            .all()
        )
        vendido_map = {r.producto_id: r.tv for r in ventas_q}

        # Count ALL tipo=salida (includes venta + auditoria_correccion)
        mov_q = (
            db.query(MovimientoStock.producto_id, func.sum(MovimientoStock.cantidad).label("ts"))
            .filter(MovimientoStock.tipo == TipoMovimiento.salida)
            .group_by(MovimientoStock.producto_id)
            .all()
        )
        salidas_map = {r.producto_id: r.ts for r in mov_q}

        corregidos = 0
        for pid, vendido in vendido_map.items():
            diferencia = float(vendido) - float(salidas_map.get(pid, 0) or 0)
            if diferencia <= 0:
                continue

            prod = db.query(Producto).filter(Producto.id == pid).first()
            if not prod:
                continue

            if prod.venta_fraccionada:
                # diferencia is in piezas — deduct from piezas_sueltas first, then boxes
                piezas_ant = prod.piezas_sueltas or 0
                upc = prod.unidades_por_caja or 1
                if piezas_ant >= diferencia:
                    stock_ant = piezas_ant
                    prod.piezas_sueltas = max(0, piezas_ant - diferencia)
                    stock_nuevo = prod.piezas_sueltas
                else:
                    deficit = diferencia - piezas_ant
                    cajas = _math.ceil(deficit / upc)
                    prod.stock = max(0, prod.stock - cajas)
                    prod.piezas_sueltas = max(0, piezas_ant + cajas * upc - diferencia)
                    stock_ant = piezas_ant
                    stock_nuevo = prod.piezas_sueltas
                notas = f"CORRECCIÓN STOCK — {int(diferencia)} {prod.unidad_pieza or 'pieza(s)'} vendidas sin descuento registrado"
            else:
                stock_ant = prod.stock or 0
                prod.stock = max(0, stock_ant - diferencia)
                stock_nuevo = prod.stock
                notas = f"CORRECCIÓN STOCK — {int(diferencia)} unidad(es) vendidas sin descuento registrado"

            db.add(MovimientoStock(
                producto_id=pid,
                tipo=TipoMovimiento.salida,
                cantidad=diferencia,
                stock_anterior=stock_ant,
                stock_nuevo=stock_nuevo,
                referencia_tipo="auditoria_correccion",
                referencia_id=None,
                usuario_id=int(payload["sub"]),
                notas=notas,
            ))
            corregidos += 1

        db.commit()

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)

        return {"ok": True, "corregidos": corregidos}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/recalcular-stock")
def recalcular_stock(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """
    Fija el stock de cada producto al stock_nuevo del último MovimientoStock registrado.
    Corrige corrupciones históricas causadas por sincronizaciones fuera de orden.
    """
    _require_admin(payload)
    db = get_db_session()
    try:
        from sqlalchemy import text as _sql_text

        productos = db.query(Producto).filter(Producto.activo.is_(True)).all()
        corregidos = []

        for prod in productos:
            ultimo_mov = (
                db.query(MovimientoStock)
                .filter(MovimientoStock.producto_id == prod.id)
                .order_by(MovimientoStock.id.desc())
                .first()
            )
            if not ultimo_mov:
                continue
            if prod.stock == ultimo_mov.stock_nuevo:
                continue

            old_stock = prod.stock
            prod.stock = ultimo_mov.stock_nuevo
            db.execute(
                _sql_text("UPDATE productos SET stock=:s WHERE id=:id"),
                {"s": ultimo_mov.stock_nuevo, "id": prod.id},
            )
            corregidos.append({
                "id": prod.id,
                "nombre": prod.nombre,
                "stock_anterior": old_stock,
                "stock_nuevo": ultimo_mov.stock_nuevo,
            })
            print(f"[RecalcStock] {prod.nombre}: {old_stock} → {ultimo_mov.stock_nuevo}")

        db.commit()

        import app.config as _cfg
        if corregidos and _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)

        return {"ok": True, "corregidos": len(corregidos), "detalle": corregidos}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
