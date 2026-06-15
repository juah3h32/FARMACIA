from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text as _sql_text
from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, Lote, MovimientoStock, TipoMovimiento, EstadoVenta, MetodoPago
from app.api.routes.auth_routes import get_current_api_user
import random
import string

router = APIRouter()


class ItemVentaIn(BaseModel):
    producto_id: int
    cantidad: int
    precio_unitario: float
    descuento: float = 0.0
    es_pieza: bool = False


class CreateVentaIn(BaseModel):
    cliente_id: Optional[int] = None
    items: list[ItemVentaIn]
    metodo_pago: str = "efectivo"
    monto_pagado: float
    descuento_global: float = 0.0
    notas: Optional[str] = None


def _gen_folio() -> str:
    return "F" + "".join(random.choices(string.digits, k=8))


def _fefo_consume(db, producto_id: int, cantidad: int) -> None:
    """
    Decrement lote quantities in FEFO order (earliest expiry first).
    Lotes without fecha_vencimiento are consumed last.
    Silently handles products without lotes (legacy/pre-lote-tracking).
    """
    lotes = (
        db.query(Lote)
        .filter(Lote.producto_id == producto_id, Lote.cantidad > 0)
        .order_by(
            Lote.fecha_vencimiento.is_(None),   # nulls last
            Lote.fecha_vencimiento.asc(),
        )
        .all()
    )
    remaining = cantidad
    for lote in lotes:
        if remaining <= 0:
            break
        consume = min(lote.cantidad, remaining)
        lote.cantidad -= consume
        remaining -= consume


@router.post("/")
def crear_venta(body: CreateVentaIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        # Single query for all products at once (1 HTTP call instead of 2N)
        product_ids = [i.producto_id for i in body.items]
        products = {
            p.id: p
            for p in db.query(Producto).filter(Producto.id.in_(product_ids)).all()
        }

        # Guard: reject if all available lotes are expired (no usable stock)
        from datetime import date as _date
        hoy = _date.today()
        for item in body.items:
            prod = products.get(item.producto_id)
            if not prod:
                continue
            lotes_all = db.query(Lote).filter(
                Lote.producto_id == item.producto_id, Lote.cantidad > 0
            ).all()
            if lotes_all:
                lotes_ok = [
                    l for l in lotes_all
                    if l.fecha_vencimiento is None or l.fecha_vencimiento >= hoy
                ]
                if not lotes_ok:
                    raise HTTPException(
                        status_code=409,
                        detail=f"'{prod.nombre}' tiene todos los lotes vencidos — no se puede vender",
                    )

        # Guard: reject if insufficient stock before any decrement
        for item in body.items:
            prod = products.get(item.producto_id)
            if not prod:
                continue
            if prod.venta_fraccionada and item.es_pieza:
                total_piezas = (prod.piezas_sueltas or 0) + (prod.stock or 0) * (prod.unidades_por_caja or 1)
                if total_piezas < item.cantidad:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Stock insuficiente: '{prod.nombre}' — disponible {total_piezas} {prod.unidad_pieza or 'pieza(s)'}, solicitado {item.cantidad}",
                    )
            elif prod.venta_fraccionada and not item.es_pieza:
                if (prod.stock or 0) < item.cantidad:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Stock insuficiente: '{prod.nombre}' — disponible {prod.stock or 0} {prod.unidad_caja or 'caja(s)'}, solicitado {item.cantidad}",
                    )
            else:
                if (prod.stock or 0) < item.cantidad:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Stock insuficiente: '{prod.nombre}' — disponible {prod.stock or 0}, solicitado {item.cantidad}",
                    )

        # Calculate totals in one pass
        subtotal  = 0.0
        iva_total = 0.0
        for item in body.items:
            prod = products.get(item.producto_id)
            if not prod:
                raise HTTPException(status_code=404, detail=f"Producto {item.producto_id} no encontrado")
            item_base = (item.precio_unitario * item.cantidad) - item.descuento
            subtotal  += item_base
            if prod.aplica_iva:
                iva_total += item_base * 0.16

        base   = subtotal - body.descuento_global
        total  = base + iva_total
        cambio = max(0.0, body.monto_pagado - total)
        folio  = _gen_folio()

        try:
            metodo = MetodoPago(body.metodo_pago)
        except ValueError:
            metodo = MetodoPago.efectivo

        from datetime import datetime as _dt
        venta = Venta(
            folio=folio,
            usuario_id=int(payload["sub"]),
            cliente_id=body.cliente_id,
            subtotal=subtotal,
            descuento=body.descuento_global,
            iva=iva_total,
            total=total,
            metodo_pago=metodo,
            monto_pagado=body.monto_pagado,
            cambio=cambio,
            estado=EstadoVenta.completada,
            notas=body.notas,
            creado_en=_dt.now(),
        )
        db.add(venta)
        db.flush()  # Get venta.id for items

        usuario_id = int(payload["sub"])
        for item in body.items:
            db.add(ItemVenta(
                venta_id=venta.id,
                producto_id=item.producto_id,
                cantidad=item.cantidad,
                precio_unitario=item.precio_unitario,
                descuento=item.descuento,
                subtotal=(item.precio_unitario * item.cantidad) - item.descuento,
            ))
            prod = products[item.producto_id]
            stock_ant = prod.stock
            import math as _math

            if prod.venta_fraccionada and item.es_pieza:
                # ── Pieza suelta ────────────────────────────────────────────
                # Descuenta de piezas_sueltas primero; si no alcanza, abre cajas.
                necesarias = item.cantidad
                piezas_ant = prod.piezas_sueltas or 0
                if piezas_ant >= necesarias:
                    prod.piezas_sueltas -= necesarias
                    cajas_abiertas = 0
                    # FIX: track piezas in movement (stock_ant/nuevo = piezas context)
                    stock_ant = piezas_ant
                    stock_delta = necesarias
                    stock_nue_override = prod.piezas_sueltas
                else:
                    deficit = necesarias - piezas_ant
                    cajas_abiertas = _math.ceil(deficit / (prod.unidades_por_caja or 1))
                    prod.stock = max(0, prod.stock - cajas_abiertas)
                    prod.piezas_sueltas = (
                        piezas_ant
                        + cajas_abiertas * (prod.unidades_por_caja or 1)
                        - necesarias
                    )
                    _fefo_consume(db, item.producto_id, cajas_abiertas)
                    stock_delta = cajas_abiertas
                    stock_nue_override = prod.stock
                notas_mov = f"Folio {folio} | {necesarias} {prod.unidad_pieza or 'pieza(s)'}"
                if cajas_abiertas:
                    notas_mov += f" (abrió {cajas_abiertas} {prod.unidad_caja or 'caja(s)'})"
            elif prod.venta_fraccionada and not item.es_pieza:
                # ── Caja completa ───────────────────────────────────────────
                prod.stock = max(0, prod.stock - item.cantidad)
                _fefo_consume(db, item.producto_id, item.cantidad)
                stock_delta = item.cantidad
                stock_nue_override = prod.stock
                notas_mov = f"Folio {folio} | {item.cantidad} {prod.unidad_caja or 'caja(s)'}"
            else:
                # ── Producto normal ─────────────────────────────────────────
                prod.stock = max(0, prod.stock - item.cantidad)
                _fefo_consume(db, item.producto_id, item.cantidad)
                stock_delta = item.cantidad
                stock_nue_override = prod.stock
                notas_mov = f"Folio {folio}"

            db.add(MovimientoStock(
                producto_id=item.producto_id,
                tipo=TipoMovimiento.salida,
                cantidad=stock_delta,
                stock_anterior=stock_ant,
                stock_nuevo=stock_nue_override,
                referencia_id=venta.id,
                referencia_tipo="venta",
                usuario_id=usuario_id,
                notas=notas_mov,
            ))

        # Belt-and-suspenders: raw SQL stock update guarantees the decrement
        # reaches SQLite even if ORM tracking misses it for any reason.
        for pid, prod in products.items():
            db.execute(
                _sql_text(
                    "UPDATE productos SET stock=:s, piezas_sueltas=:ps WHERE id=:id"
                ),
                {"s": prod.stock or 0, "ps": prod.piezas_sueltas or 0, "id": pid},
            )
            print(f"[POS] stock update: producto {pid} ({prod.nombre}) -> stock={prod.stock or 0}, piezas_sueltas={prod.piezas_sueltas or 0}")

        db.commit()
        # Verify committed stock via fresh query
        for pid in products:
            row = db.execute(_sql_text("SELECT stock FROM productos WHERE id=:id"), {"id": pid}).fetchone()
            print(f"[POS] OK committed: producto {pid} stock={row[0] if row else '?'}")

        # Imprimir ticket
        from app.services.printer_service import printer_service
        from app.database.models import Usuario
        cajero_obj = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        cajero_nombre = cajero_obj.nombre if cajero_obj else "Cajero"
        venta_data = {
            "folio": folio,
            "cajero": cajero_nombre,
            "cliente": None,
            "items": [
                {
                    "nombre": products[i.producto_id].nombre,
                    "cantidad": i.cantidad,
                    "subtotal": (i.precio_unitario * i.cantidad) - i.descuento,
                }
                for i in body.items
            ],
            "subtotal": subtotal,
            "descuento": body.descuento_global,
            "iva": iva_total,
            "total": total,
            "metodo_pago": body.metodo_pago,
            "monto_pagado": body.monto_pagado,
            "cambio": cambio,
        }
        bg.add_task(printer_service.print_receipt, venta_data)

        ticket_texto = None
        try:
            ticket_texto = printer_service._build_ticket(venta_data, printer_service._load_farmacia_config())
        except Exception:
            pass

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            bg.add_task(sync_to_turso)
        return {"id": venta.id, "folio": folio, "total": total, "cambio": cambio, "ticket_texto": ticket_texto}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class ImprimirPruebaIn(BaseModel):
    items: list[ItemVentaIn]
    metodo_pago: str = "efectivo"
    monto_pagado: float
    descuento_global: float = 0.0


@router.post("/imprimir-prueba")
def imprimir_ticket_prueba(body: ImprimirPruebaIn, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Build and print a test ticket — no DB writes, no stock changes."""
    db = get_db_session()
    try:
        producto_ids = [i.producto_id for i in body.items]
        prods = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()}

        subtotal = sum((i.precio_unitario * i.cantidad) - i.descuento for i in body.items)
        iva_total = sum(
            i.precio_unitario * i.cantidad * 0.16
            for i in body.items
            if prods.get(i.producto_id) and prods[i.producto_id].aplica_iva
        )
        total = subtotal + iva_total - body.descuento_global
        cambio = max(0.0, body.monto_pagado - total)

        from app.database.models import Usuario
        cajero_obj = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        cajero_nombre = cajero_obj.nombre if cajero_obj else "Cajero"

        venta_data = {
            "folio": "PRUEBA-000",
            "cajero": cajero_nombre,
            "cliente": None,
            "items": [
                {
                    "nombre": prods[i.producto_id].nombre if i.producto_id in prods else f"Producto {i.producto_id}",
                    "cantidad": i.cantidad,
                    "subtotal": (i.precio_unitario * i.cantidad) - i.descuento,
                }
                for i in body.items
            ],
            "subtotal": subtotal,
            "descuento": body.descuento_global,
            "iva": iva_total,
            "total": total,
            "metodo_pago": body.metodo_pago,
            "monto_pagado": body.monto_pagado,
            "cambio": cambio,
        }

        from app.services.printer_service import printer_service
        ticket_texto = printer_service._build_ticket(venta_data, printer_service._load_farmacia_config())
        bg.add_task(printer_service.print_receipt, venta_data)

        return {"ok": True, "folio": "PRUEBA-000", "total": total, "cambio": cambio, "ticket_texto": ticket_texto}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
