from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text as _sql_text
from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, Lote, MovimientoStock, TipoMovimiento, EstadoVenta, MetodoPago
from app.api.routes.auth_routes import get_current_api_user
import random
import string
import threading
from datetime import datetime as _dtnow

router = APIRouter()

# Serializa la creación de ventas dentro de este proceso — sin esto, dos ventas
# simultáneas del mismo producto (ej. doble click, o dos requests casi al mismo
# tiempo desde la misma instancia) podían leer el mismo stock disponible antes
# de que cualquiera hiciera commit, y ambas descontar pensando que alcanzaba.
# Nota: esto NO resuelve sobreventa entre DOS COMPUTADORAS distintas (cada una
# con su propia base local que sincroniza a Turso por separado) — ese es un
# problema de consistencia distribuida, no de bloqueo en un solo proceso.
_venta_lock = threading.Lock()


def _cerrar_corte_viejo_si_existe(db, usuario_id: int) -> None:
    """If the user has an open shift from a previous calendar day, auto-close it (commit included)."""
    from app.database.models import CortesCaja
    from app.api.routes.cortes_routes import _auto_cerrar_turno
    corte = (
        db.query(CortesCaja)
        .filter(CortesCaja.usuario_id == usuario_id, CortesCaja.cerrado_en == None)
        .order_by(CortesCaja.abierto_en.desc())
        .first()
    )
    if corte and corte.abierto_en and corte.abierto_en.date() < _dtnow.now().date():
        _auto_cerrar_turno(db, corte, "Cierre automático — nueva jornada")
        db.commit()


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
    # Id de orden/pago de la terminal Mercado Pago (solo lo llena terminal_routes)
    referencia_pago: Optional[str] = None


def _gen_folio() -> str:
    return "F" + "".join(random.choices(string.digits, k=8))


def _precio_esperado(prod, es_pieza: bool) -> float:
    """
    Server-side authoritative unit price for a cart line — NEVER trust the
    precio_unitario the client sends. Without this, a request crafted/edited
    outside the UI (e.g. curl with a valid cashier token) could set any price
    it wants and the backend would total the sale on that fabricated number.
    Mirrors the same fallback the frontend uses to display the price.
    """
    if prod.venta_fraccionada and es_pieza:
        if prod.precio_pieza and prod.precio_pieza > 0:
            return prod.precio_pieza
        return round(prod.precio_venta / (prod.unidades_por_caja or 1), 2)
    return prod.precio_venta


def _costo_esperado(prod, es_pieza: bool) -> float:
    """Costo de compra de UNA unidad vendida de la línea — precio_compra es por
    caja, así que una pieza suelta cuesta la parte proporcional, no la caja
    completa (antes se congelaba el costo de la caja por cada pieza vendida,
    inflando el costo y bajando la ganancia del Control de Caja)."""
    costo = prod.precio_compra or 0.0
    if prod.venta_fraccionada and es_pieza:
        return costo / (prod.unidades_por_caja or 1)
    return costo


def item_es_pieza(item, prod) -> bool:
    """¿La línea de venta fue por pieza suelta? Usa items_venta.es_pieza; para
    ventas anteriores a esa columna lo infiere: el precio cobrado está más
    cerca del precio por pieza que del de caja."""
    if getattr(item, "es_pieza", False):
        return True
    if not prod or not prod.venta_fraccionada or (prod.unidades_por_caja or 1) <= 1:
        return False
    precio_pieza = (prod.precio_pieza if prod.precio_pieza and prod.precio_pieza > 0
                    else (prod.precio_venta or 0) / prod.unidades_por_caja)
    return abs((item.precio_unitario or 0) - precio_pieza) < abs((item.precio_unitario or 0) - (prod.precio_venta or 0))


def reponer_stock(prod, cantidad: int, es_pieza: bool) -> None:
    """Regresa al inventario `cantidad` unidades de una línea vendida
    (cancelación o devolución): piezas a piezas_sueltas, cajas a stock."""
    if es_pieza and prod.venta_fraccionada:
        prod.piezas_sueltas = (prod.piezas_sueltas or 0) + cantidad
    else:
        prod.stock = (prod.stock or 0) + cantidad


def _fefo_consume(db, producto_id: int, cantidad: int) -> None:
    """
    Decrement lote quantities in FEFO order (earliest expiry first).
    Lotes without fecha_vencimiento are consumed last.
    Silently handles products without lotes (legacy/pre-lote-tracking).
    """
    from datetime import date as _date
    hoy = _date.today()
    lotes = (
        db.query(Lote)
        .filter(Lote.producto_id == producto_id, Lote.cantidad > 0)
        .order_by(
            Lote.fecha_vencimiento.is_(None),   # nulls last
            Lote.fecha_vencimiento.asc(),
        )
        .all()
    )
    # Vigentes primero (FEFO), vencidos al final: antes el "primero en caducar"
    # era justo el lote ya vencido, así que la venta descontaba de producto
    # caducado y dejaba el vigente intacto en el sistema.
    lotes.sort(key=lambda l: l.fecha_vencimiento is not None and l.fecha_vencimiento < hoy)
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
    _venta_lock.acquire()
    try:
        # Guard: if there is an open corte from a previous day, auto-close it NOW
        # so today's sale is never mixed into yesterday's shift totals.
        _cerrar_corte_viejo_si_existe(db, int(payload["sub"]))

        # Single query for all products at once (1 HTTP call instead of 2N)
        product_ids = [i.producto_id for i in body.items]
        products = {
            p.id: p
            for p in db.query(Producto).filter(Producto.id.in_(product_ids)).all()
        }

        # Guard: reject a sale with zero items — sin esto, una venta con
        # items=[] se registra igual con subtotal/total en $0 y sin ningún
        # producto asociado, quedando huérfana de items_venta (misma huella
        # que el incidente de "servidor reiniciado" del 13-jun: 20 ventas
        # históricas sin costo, inflando la ganancia reportada).
        if not body.items:
            raise HTTPException(status_code=400, detail="La venta debe tener al menos un producto")

        # Guard: reject non-positive quantities — without this, a negative
        # cantidad would slip through the stock check below (stock is never
        # "insufficient" against a negative number), then INCREASE stock and
        # make the item's subtotal negative, dragging the sale total below
        # zero and inflating "cambio" (change given back) for free.
        for item in body.items:
            if item.cantidad <= 0:
                raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")

        # Guard: descuentos solo con rol admin — la pantalla del POS no ofrece
        # descuentos, pero el backend aceptaba de cualquier cajero hasta el 100%
        # (venta de $500 registrada en $0).
        if payload.get("rol") != "admin" and (
            (body.descuento_global or 0) > 0 or any((i.descuento or 0) > 0 for i in body.items)
        ):
            raise HTTPException(status_code=403, detail="Solo un administrador puede aplicar descuentos")

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

        # Guard: stock por PRODUCTO sumando todas sus líneas — antes se validaba
        # línea por línea, así que dos líneas del mismo producto (o caja + pieza)
        # pasaban cada una por separado y se vendía más de lo que había (el
        # max(0, ...) de abajo escondía el faltante).
        pedido: dict[int, list] = {}
        for item in body.items:
            cajas_pz = pedido.setdefault(item.producto_id, [0, 0])
            cajas_pz[1 if item.es_pieza else 0] += item.cantidad
        for pid, (cajas, piezas) in pedido.items():
            prod = products.get(pid)
            if not prod:
                continue
            upc = (prod.unidades_por_caja or 1) if prod.venta_fraccionada else 1
            disponibles_pz = (prod.stock or 0) * upc + ((prod.piezas_sueltas or 0) if prod.venta_fraccionada else 0)
            if cajas > (prod.stock or 0) or cajas * upc + piezas > disponibles_pz:
                raise HTTPException(
                    status_code=409,
                    detail=(f"Stock insuficiente: '{prod.nombre}' — disponible {prod.stock or 0} "
                            f"{prod.unidad_caja or 'caja(s)' if prod.venta_fraccionada else ''}"
                            + (f" + {prod.piezas_sueltas or 0} {prod.unidad_pieza or 'pieza(s)'}" if prod.venta_fraccionada else "")
                            + f", solicitado {cajas} " + (f"caja(s) + {piezas} pieza(s)" if prod.venta_fraccionada else "")).replace("  ", " "),
                )
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

        # Calculate totals in one pass — precio_unitario/descuento are
        # recomputed/clamped server-side (see _precio_esperado): the client's
        # values are never trusted directly for money math or storage.
        subtotal  = 0.0
        iva_total = 0.0
        precios_validos    = {}
        descuentos_validos = {}
        for idx, item in enumerate(body.items):
            prod = products.get(item.producto_id)
            if not prod:
                raise HTTPException(status_code=404, detail=f"Producto {item.producto_id} no encontrado")
            precio = _precio_esperado(prod, item.es_pieza)
            item_full = precio * item.cantidad
            # Clamp: an item's discount can never be negative (would inflate
            # price) nor exceed its own subtotal (would make it negative).
            descuento = min(max(item.descuento, 0.0), item_full)
            precios_validos[idx]    = precio
            descuentos_validos[idx] = descuento
            item_base = item_full - descuento
            subtotal  += item_base
            if prod.aplica_iva:
                iva_total += item_base * 0.16

        # Same clamp for the global discount — can't be negative nor exceed
        # the sale's own subtotal (both would push total below zero).
        descuento_global = min(max(body.descuento_global, 0.0), subtotal)
        base   = subtotal - descuento_global
        # El IVA va sobre el precio YA descontado: el descuento global se reparte
        # proporcional entre las líneas (antes se cobraba IVA sobre el precio
        # sin descuento — p. ej. $16 en vez de $14.40).
        if subtotal > 0 and descuento_global:
            iva_total *= base / subtotal
        total  = base + iva_total
        cambio = max(0.0, body.monto_pagado - total)
        folio  = _gen_folio()

        try:
            metodo = MetodoPago(body.metodo_pago)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Método de pago inválido: '{body.metodo_pago}'")

        # Antes solo se validaba para efectivo — con tarjeta/transferencia el
        # frontend siempre manda monto_pagado==total, pero un request armado
        # a mano podía mandar cualquier monto_pagado menor y la venta se
        # registraba igual como pagada por completo (no hay flujo de crédito
        # que justifique un pago parcial en ningún método).
        if body.monto_pagado < total - 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"Monto pagado (${body.monto_pagado:.2f}) insuficiente para total (${total:.2f})"
            )

        from datetime import datetime as _dt
        venta = Venta(
            folio=folio,
            usuario_id=int(payload["sub"]),
            cliente_id=body.cliente_id,
            subtotal=subtotal,
            descuento=descuento_global,
            iva=iva_total,
            total=total,
            metodo_pago=metodo,
            monto_pagado=body.monto_pagado,
            cambio=cambio,
            estado=EstadoVenta.completada,
            notas=body.notas,
            referencia_pago=(body.referencia_pago or None),
            creado_en=_dt.now(),
        )
        db.add(venta)
        db.flush()  # Get venta.id for items

        usuario_id = int(payload["sub"])
        # Cajas completas antes que piezas: si una línea de piezas abriera cajas
        # primero, la línea de caja del mismo producto podía quedarse sin stock.
        orden = sorted(enumerate(body.items), key=lambda t: bool(t[1].es_pieza))
        for idx, item in orden:
            precio    = precios_validos[idx]
            descuento = descuentos_validos[idx]
            prod = products[item.producto_id]
            db.add(ItemVenta(
                venta_id=venta.id,
                producto_id=item.producto_id,
                cantidad=item.cantidad,
                precio_unitario=precio,
                descuento=descuento,
                subtotal=(precio * item.cantidad) - descuento,
                # Congelado al momento de vender — Control de Caja debe usar
                # SIEMPRE este valor, nunca Producto.precio_compra en vivo
                # (ver costo_unitario en models.py).
                costo_unitario=_costo_esperado(prod, item.es_pieza),
                es_pieza=bool(prod.venta_fraccionada and item.es_pieza),
            ))
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

        db.commit()

        # Acumular puntos si hay cliente vinculado
        if body.cliente_id:
            try:
                from app.database.models import Configuracion, Cliente as _Cliente
                cfg_row = db.query(Configuracion).filter(Configuracion.clave == "pesos_por_punto").first()
                pesos_por_punto = float(cfg_row.valor) if cfg_row and cfg_row.valor else 10.0
                cliente_obj = db.query(_Cliente).filter(_Cliente.id == body.cliente_id).first()
                if cliente_obj:
                    puntos_ganados = total / pesos_por_punto
                    cliente_obj.puntos_acumulados = (cliente_obj.puntos_acumulados or 0) + puntos_ganados
                    db.commit()
            except Exception:
                pass  # puntos no son críticos, nunca bloquear la venta

        # Verificar si algún producto requiere receta (para que frontend muestre aviso)
        requiere_receta = any(
            products.get(item.producto_id) and products[item.producto_id].requiere_receta
            for item in body.items
        )

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
                    "subtotal": (precios_validos[idx] * i.cantidad) - descuentos_validos[idx],
                }
                for idx, i in enumerate(body.items)
            ],
            "subtotal": subtotal,
            "descuento": descuento_global,
            "iva": iva_total,
            "total": total,
            "metodo_pago": body.metodo_pago,
            "monto_pagado": body.monto_pagado,
            "cambio": cambio,
        }
        # Con tarjeta NO se imprime solo: la terminal ya da su comprobante y no
        # entra dinero al cajón. Si el cliente pide el ticket con productos, el
        # cajero lo imprime con "Imprimir ticket" (/pos/reimprimir, sin abrir cajón).
        if body.metodo_pago != "tarjeta":
            bg.add_task(printer_service.print_receipt, venta_data)

        ticket_texto = None
        try:
            ticket_texto = printer_service._build_ticket(venta_data, printer_service._load_farmacia_config())
        except Exception:
            pass

        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso
            # only_incremental=True: al cobrar solo empuja lo que cambió (venta,
            # items, stock) — no relee ni resube tablas completas como lotes o
            # cortes_caja en cada venta (eso volvía cada cobro más lento a medida
            # que esas tablas crecían). El hilo de sincronización en background
            # ya sincroniza esas tablas completas en su latido periódico.
            bg.add_task(sync_to_turso, only_incremental=True)
        return {"id": venta.id, "folio": folio, "total": total, "cambio": cambio, "ticket_texto": ticket_texto, "requiere_receta": requiere_receta}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _venta_lock.release()
        db.close()


def venta_data_desde_bd(db, venta) -> dict:
    """Datos del ticket de una venta YA registrada (folio real, lo que quedó
    tras devoluciones) — para reimprimir o mandar el detalle a la terminal."""
    from app.database.models import Usuario
    cajero = db.query(Usuario).filter(Usuario.id == venta.usuario_id).first()
    items = []
    for it in venta.items:
        if (it.cantidad or 0) <= 0:
            continue
        nombre = it.producto.nombre if it.producto else f"Producto {it.producto_id}"
        if getattr(it, "es_pieza", False):
            nombre += " (pieza)"
        items.append({"nombre": nombre, "cantidad": it.cantidad, "precio_unitario": it.precio_unitario,
                      "subtotal": it.subtotal})
    return {
        "folio": venta.folio,
        "cajero": cajero.nombre if cajero else "Cajero",
        "cliente": None,
        "items": items,
        "subtotal": venta.subtotal,
        "descuento": venta.descuento or 0.0,
        "iva": venta.iva or 0.0,
        "total": venta.total,
        "metodo_pago": venta.metodo_pago.value if venta.metodo_pago else "",
        "monto_pagado": venta.monto_pagado,
        "cambio": venta.cambio or 0.0,
        "fecha": venta.creado_en.strftime("%d/%m/%Y %H:%M") if venta.creado_en else "",
    }


@router.post("/reimprimir/{venta_id}")
def reimprimir_ticket(venta_id: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Imprime el ticket de una venta ya hecha (p. ej. pago con tarjeta que el
    cliente pidió con productos). Nunca abre el cajón."""
    from app.services.printer_service import printer_service
    db = get_db_session()
    try:
        venta = db.query(Venta).filter(Venta.id == venta_id, Venta.eliminado.is_not(True)).first()
        if not venta:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        data = venta_data_desde_bd(db, venta)
    finally:
        db.close()
    bg.add_task(printer_service.print_receipt, data, None, False)
    return {"ok": True, "folio": data["folio"]}


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
            ((i.precio_unitario * i.cantidad) - i.descuento) * 0.16
            for i in body.items
            if prods.get(i.producto_id) and prods[i.producto_id].aplica_iva
        )
        total = (subtotal - body.descuento_global) + iva_total
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
        bg.add_task(printer_service.print_receipt, venta_data, None, False)  # reimpresión: sin abrir cajón

        return {"ok": True, "folio": "PRUEBA-000", "total": total, "cambio": cambio, "ticket_texto": ticket_texto}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class CotizacionItemIn(BaseModel):
    producto_id: int
    cantidad: int = 1
    precio_unitario: float


class CotizacionIn(BaseModel):
    items: list[CotizacionItemIn]


@router.post("/cotizacion-imprimir")
def imprimir_cotizacion(body: CotizacionIn, payload: dict = Depends(get_current_api_user)):
    """Print a price-check / cotizacion ticket — no DB writes, no stock changes."""
    db = get_db_session()
    try:
        producto_ids = [i.producto_id for i in body.items]
        prods = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(producto_ids)).all()}

        from app.database.models import Usuario
        cajero_obj = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        cajero_nombre = cajero_obj.nombre if cajero_obj else "Cajero"

        items_print = []
        for i in body.items:
            p = prods.get(i.producto_id)
            precio = i.precio_unitario
            aplica_iva = p.aplica_iva if p else False
            items_print.append({
                "producto_id": i.producto_id,
                "nombre": p.nombre if p else f"Producto {i.producto_id}",
                "precio": precio,
                "aplica_iva": aplica_iva,
                "stock": p.stock if p else 0,
                "cantidad": i.cantidad,
            })

        from app.services.printer_service import printer_service
        ok = printer_service.print_price_check(items_print, cajero_nombre)
        return {"ok": ok}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
