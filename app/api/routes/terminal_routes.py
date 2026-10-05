"""
Cobro con terminal Mercado Pago Point (Point Smart 2) desde el POS.

Flujo (polling — la app de escritorio no tiene URL pública para webhooks):
  1. POST /api/pos/terminal/cobro            → valida carrito, calcula el total en el
     servidor (el mismo cálculo que /api/pos/) y crea la orden MP con
     X-Idempotency-Key = client_ref. La venta TODAVÍA NO existe.
  2. GET  /api/pos/terminal/cobro/{order_id} → consulta la orden. Solo cuando MP
     responde status=processed se registra la venta (metodo_pago=tarjeta,
     referencia_pago=order_id). Es idempotente: una orden = una venta como máximo.
  3. POST /api/pos/terminal/cobro/{order_id}/cancelar → cancela si la terminal aún
     no la tomó; si ya está en la terminal, se cancela desde la terminal.
  4. GET  /api/pos/terminal/pendientes       → cobros aprobados que no se alcanzaron
     a registrar (p. ej. se cerró el programa a mitad del pago) o aún activos.

Los cobros en curso se guardan en DATA_DIR/mp_pendientes.json para sobrevivir
a un reinicio del programa.
"""
import json
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

import app.config as cfg
from app.api.routes.auth_routes import get_current_api_user
from app.api.routes import pos_routes
from app.database.connection import get_db_session
from app.database.models import Producto, Lote, Venta
from app.services.mercadopago_service import mp_point, MercadoPagoError, FINAL_STATES

router = APIRouter()

_lock = threading.RLock()
_pend: dict = {}
_loaded = False
_ACTIVE = {"created", "at_terminal"}


def _file():
    return cfg.DATA_DIR / "mp_pendientes.json"


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        f = _file()
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _pend.update(data)
    except Exception:
        pass


def _save():
    # Purga lo viejo (más de 24 h), salvo pagos aprobados que aún no tienen venta
    now = time.time()
    viejos = [k for k, v in _pend.items()
              if now - v.get("creado", now) > 86400
              and not (v.get("status") == "processed" and not v.get("venta"))]
    for k in viejos:
        _pend.pop(k, None)
    try:
        _file().write_text(json.dumps(_pend, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


class CobroTerminalIn(BaseModel):
    cliente_id: Optional[int] = None
    items: list[pos_routes.ItemVentaIn]
    descuento_global: float = 0.0
    notas: Optional[str] = None
    client_ref: Optional[str] = None   # uuid generado por el front — idempotencia


def _cotizar(body: CobroTerminalIn) -> float:
    """Mismo cálculo y mismas validaciones previas que pos_routes.crear_venta, para
    que el monto que se cobra en la terminal sea EXACTAMENTE el total con que luego
    se registra la venta (y no cobrar si la venta de todos modos sería rechazada)."""
    if not body.items:
        raise HTTPException(status_code=400, detail="La venta debe tener al menos un producto")
    db = get_db_session()
    try:
        ids = [i.producto_id for i in body.items]
        prods = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(ids)).all()}
        from datetime import date as _date
        hoy = _date.today()
        subtotal = iva = 0.0
        for it in body.items:
            if it.cantidad <= 0:
                raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
            prod = prods.get(it.producto_id)
            if not prod:
                raise HTTPException(status_code=404, detail=f"Producto {it.producto_id} no encontrado")
            lotes = db.query(Lote).filter(Lote.producto_id == it.producto_id, Lote.cantidad > 0).all()
            if lotes and not [l for l in lotes if l.fecha_vencimiento is None or l.fecha_vencimiento >= hoy]:
                raise HTTPException(status_code=409, detail=f"'{prod.nombre}' tiene todos los lotes vencidos — no se puede vender")
            if prod.venta_fraccionada and it.es_pieza:
                disp = (prod.piezas_sueltas or 0) + (prod.stock or 0) * (prod.unidades_por_caja or 1)
            else:
                disp = prod.stock or 0
            if disp < it.cantidad:
                raise HTTPException(status_code=409, detail=f"Stock insuficiente: '{prod.nombre}' — disponible {disp}, solicitado {it.cantidad}")
            precio = pos_routes._precio_esperado(prod, it.es_pieza)
            full = precio * it.cantidad
            desc = min(max(it.descuento, 0.0), full)
            base = full - desc
            subtotal += base
            if prod.aplica_iva:
                iva += base * 0.16
        dg = min(max(body.descuento_global, 0.0), subtotal)
        return round(subtotal - dg + iva, 2)
    finally:
        db.close()


def _venta_existente(order_id: str) -> Optional[dict]:
    db = get_db_session()
    try:
        v = db.query(Venta).filter(Venta.referencia_pago == order_id).first()
        if v:
            return {"id": v.id, "folio": v.folio, "total": v.total, "cambio": 0.0, "ticket_texto": None}
        return None
    finally:
        db.close()


def _registrar(order_id: str, info: dict, bg: BackgroundTasks) -> dict:
    """Crea la venta UNA sola vez para una orden aprobada."""
    with _lock:
        p = _pend.get(order_id)
        if p and p.get("venta"):
            return p["venta"]
        ya = _venta_existente(order_id)
        if ya:
            if p:
                p["venta"] = ya
                _save()
            return ya
        if not p:
            raise HTTPException(status_code=404, detail="Cobro no encontrado en este equipo")
        total = float(p["total"])
        try:
            pagado = float(info.get("amount") or total)
        except Exception:
            pagado = total
        if pagado < total - 0.01:
            p["error_registro"] = f"La terminal cobró {pagado:.2f} pero el total es {total:.2f}"
            _save()
            raise HTTPException(status_code=409, detail=p["error_registro"])
        b = p["body"]
        ref = order_id + (f"|{info['payment_id']}" if info.get("payment_id") else "")
        nota_mp = f"Terminal MP orden {order_id}"
        if info.get("last_four"):
            nota_mp += f" tarjeta ****{info['last_four']}"
        venta_in = pos_routes.CreateVentaIn(
            cliente_id=b.get("cliente_id"),
            items=[pos_routes.ItemVentaIn(**i) for i in b["items"]],
            metodo_pago="tarjeta",
            monto_pagado=pagado,
            descuento_global=b.get("descuento_global") or 0.0,
            notas=((b.get("notas") or "") + (" · " if b.get("notas") else "") + nota_mp),
            referencia_pago=ref[:120],
        )
        try:
            res = pos_routes.crear_venta(venta_in, bg, p["payload"])
        except HTTPException as e:
            p["error_registro"] = str(e.detail)
            _save()
            raise HTTPException(
                status_code=e.status_code,
                detail=f"El pago SÍ se aprobó en la terminal (orden {order_id}) pero la venta no se pudo "
                       f"registrar: {e.detail}. Reintenta o regístrala manualmente.")
        p["venta"] = {k: res.get(k) for k in ("id", "folio", "total", "cambio", "ticket_texto", "requiere_receta")}
        p.pop("error_registro", None)
        _save()
        return p["venta"]


def _respuesta(order_id: str, info: dict, bg: BackgroundTasks) -> dict:
    st = info.get("status", "")
    out = {"order_id": order_id, "status": st, "status_detail": info.get("status_detail", ""),
           "detalle": info.get("detalle", ""), "payment_id": info.get("payment_id")}
    with _lock:
        p = _pend.get(order_id)
        if p:
            p["status"] = st
            p["payment_id"] = info.get("payment_id")
            _save()
            out["total"] = p.get("total")
    if st == "processed":
        out["venta"] = _registrar(order_id, info, bg)
        out["message"] = "Pago aprobado"
    elif st == "failed":
        out["message"] = "Pago rechazado" + (f": {info['detalle']}" if info.get("detalle") else "")
    elif st == "canceled":
        out["message"] = "Cobro cancelado" + (f" ({info['detalle']})" if info.get("detalle") else "")
    elif st == "expired":
        out["message"] = "Se agotó el tiempo: el cliente no pagó en la terminal"
    elif st == "action_required":
        out["message"] = ("La terminal pide confirmar el resultado. Revisa la pantalla/ticket de la "
                          "terminal: si salió APROBADO usa 'Cobrar sin terminal'; si no, cancela.")
    elif st == "at_terminal":
        out["message"] = "El cliente está pagando en la terminal..."
    elif st == "refunded":
        out["message"] = "El pago fue reembolsado"
    else:
        out["message"] = "Esperando que la terminal tome el cobro..."
    out["final"] = st in FINAL_STATES
    return out


def _require_enabled():
    if not mp_point.enabled:
        raise HTTPException(status_code=400, detail="Terminal Mercado Pago no configurada (Configuración > Mercado Pago)")


@router.get("/estado")
def estado(payload: dict = Depends(get_current_api_user)):
    return {"enabled": mp_point.enabled, "device_id": mp_point.device_id if mp_point.enabled else ""}


@router.post("/cobro")
def iniciar_cobro(body: CobroTerminalIn, payload: dict = Depends(get_current_api_user)):
    _require_enabled()
    _load()
    ref = (body.client_ref or "").strip()[:64] or str(uuid.uuid4())
    with _lock:
        # Mismo client_ref = reintento del mismo clic (red lenta) → misma orden
        for oid, p in _pend.items():
            if p.get("client_ref") == ref:
                return {"order_id": oid, "total": p["total"], "status": p.get("status", "created"),
                        "terminal_id": p.get("terminal_id"), "reused": True}
        # No mandar un segundo cobro mientras otro sigue vivo en la terminal
        for oid, p in list(_pend.items()):
            if p.get("status") in _ACTIVE and p.get("terminal_id") == mp_point.device_id:
                try:
                    st = mp_point.resumen(mp_point.get_order(oid))["status"]
                except MercadoPagoError:
                    st = p.get("status")
                p["status"] = st
                if st == "created":
                    try:
                        mp_point.cancel_order(oid)
                        p["status"] = "canceled"
                    except MercadoPagoError:
                        pass
                elif st == "at_terminal":
                    _save()
                    raise HTTPException(
                        status_code=409,
                        detail="La terminal tiene otro cobro en curso. Termínalo o cancélalo en la terminal.")
        _save()

    total = _cotizar(body)
    if total <= 0:
        raise HTTPException(status_code=400, detail="El total debe ser mayor a $0 para cobrar con terminal")
    try:
        order = mp_point.create_order(total, ref, idempotency_key=ref,
                                      description=f"{cfg.PHARMACY_NAME}"[:150])
    except MercadoPagoError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    info = mp_point.resumen(order)
    oid = info["order_id"]
    if not oid:
        raise HTTPException(status_code=502, detail="Mercado Pago no devolvió el id de la orden")
    with _lock:
        _pend[oid] = {
            "client_ref": ref, "total": total, "status": info["status"] or "created",
            "terminal_id": mp_point.device_id, "creado": time.time(),
            "body": {"cliente_id": body.cliente_id, "items": [i.dict() for i in body.items],
                     "descuento_global": body.descuento_global, "notas": body.notas},
            "payload": {"sub": payload.get("sub"), "rol": payload.get("rol")},
        }
        _save()
    return {"order_id": oid, "total": total, "status": info["status"] or "created",
            "terminal_id": mp_point.device_id, "reused": False}


@router.get("/cobro/{order_id}")
def consultar_cobro(order_id: str, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _load()
    if order_id not in _pend and not _venta_existente(order_id):
        raise HTTPException(status_code=404, detail="Cobro no encontrado")
    try:
        info = mp_point.resumen(mp_point.get_order(order_id))
    except MercadoPagoError as e:
        if e.status_code in (401, 403):
            raise HTTPException(status_code=e.status_code, detail=e.message)
        # Sin internet / MP caído: NO es un rechazo — el front sigue esperando
        return {"order_id": order_id, "status": "unknown", "final": False, "offline": True,
                "message": f"{e.message} Reintentando..."}
    return _respuesta(order_id, info, bg)


@router.post("/cobro/{order_id}/cancelar")
def cancelar_cobro(order_id: str, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _load()
    if order_id not in _pend:
        raise HTTPException(status_code=404, detail="Cobro no encontrado")
    try:
        info = mp_point.resumen(mp_point.get_order(order_id))
    except MercadoPagoError as e:
        return {"ok": False, "status": "unknown", "message": f"No se pudo verificar el cobro: {e.message}"}
    st = info["status"]
    if st == "created":
        try:
            info = mp_point.resumen(mp_point.cancel_order(order_id))
            if not info.get("status"):
                info["status"] = "canceled"
        except MercadoPagoError as e:
            # Pudo haberla tomado la terminal justo ahora
            try:
                info = mp_point.resumen(mp_point.get_order(order_id))
            except MercadoPagoError:
                return {"ok": False, "status": "unknown", "message": e.message}
    out = _respuesta(order_id, info, bg)
    if out["status"] == "at_terminal":
        out["ok"] = False
        out["message"] = ("El cobro ya está en la pantalla de la terminal: cancélalo en la terminal "
                          "(botón X / Cancelar). El POS sigue esperando el resultado.")
    else:
        out["ok"] = out["status"] in ("canceled", "expired", "failed")
    return out


@router.get("/pendientes")
def pendientes(payload: dict = Depends(get_current_api_user)):
    _load()
    with _lock:
        out = []
        for oid, p in _pend.items():
            if p.get("venta"):
                continue
            if p.get("status") in _ACTIVE or p.get("status") == "processed" or p.get("error_registro"):
                out.append({"order_id": oid, "total": p.get("total"), "status": p.get("status"),
                            "error_registro": p.get("error_registro"), "creado": p.get("creado")})
        return {"pendientes": out}
