from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload, contains_eager
import io, csv, os, tempfile

from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, EstadoVenta, CortesCaja, Lote, MovimientoStock, TipoMovimiento, MetodoPago
from app.api.routes.cortes_routes import _valor_devoluciones
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _rango(fecha_inicio: date, fecha_fin: date):
    return (
        datetime.combine(fecha_inicio, datetime.min.time()),
        datetime.combine(fecha_fin,    datetime.max.time()),
    )


@router.get("/resumen")
def resumen(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        ventas = (
            db.query(Venta)
            .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .all()
        )
        total = sum(v.total for v in ventas)
        iva_total = sum(v.iva or 0.0 for v in ventas)
        num   = len(ventas)

        por_dia: dict[str, float] = {}
        for v in ventas:
            d = v.creado_en.date().isoformat() if v.creado_en else "?"
            por_dia[d] = por_dia.get(d, 0.0) + v.total

        mejor_dia   = max(por_dia, key=por_dia.get) if por_dia else None
        mejor_monto = por_dia[mejor_dia] if mejor_dia else 0.0

        # Cost of goods sold for period — costo CONGELADO al vender
        # (ItemVenta.costo_unitario), nunca Producto.precio_compra en vivo.
        venta_ids = [v.id for v in ventas]
        if venta_ids:
            items = db.query(ItemVenta).filter(ItemVenta.venta_id.in_(venta_ids)).all()
            pids = {it.producto_id for it in items}
            prods = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(pids)).all()} if pids else {}
            # _costo_item corrige ventas por pieza que guardaron el costo de la caja completa
            total_costo = sum(_costo_item(it, prods.get(it.producto_id))[0] for it in items)
        else:
            total_costo = 0.0
        # Partial devoluciones in period (full returns excluded via estado=devolucion filter)
        dev_movs = db.query(MovimientoStock).filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_tipo == "devolucion",
            MovimientoStock.creado_en >= fi,
            MovimientoStock.creado_en <= ff,
        ).all()
        total_devoluciones = _valor_devoluciones(db, dev_movs)
        ventas_netas = total - total_devoluciones
        # El IVA cobrado no es ganancia — es dinero del SAT que solo pasa por caja
        ganancia = (ventas_netas - iva_total) - total_costo

        return {
            "total":               total,
            "total_devoluciones":  round(total_devoluciones, 2),
            "ventas_netas":        round(ventas_netas, 2),
            "num_ventas":          num,
            "ticket_promedio":     total / num if num else 0.0,
            "mejor_dia_fecha":     mejor_dia,
            "mejor_dia_monto":     mejor_monto,
            "efectivo":            sum(v.total for v in ventas if v.metodo_pago.value == "efectivo"),
            "tarjeta":             sum(v.total for v in ventas if v.metodo_pago.value == "tarjeta"),
            "transferencia":       sum(v.total for v in ventas if v.metodo_pago.value == "transferencia"),
            "total_costo":         total_costo,
            "ganancia":            round(ganancia, 2),
            "por_dia": [{"fecha": k, "total": v} for k, v in sorted(por_dia.items())],
        }
    finally:
        db.close()


@router.get("/top-productos")
def top_productos(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    limite: int = Query(10, ge=1, le=50),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        rows = (
            db.query(
                Producto.nombre,
                func.sum(ItemVenta.cantidad).label("total_vendido"),
                func.sum(ItemVenta.subtotal).label("total_ingreso"),
            )
            .join(ItemVenta, ItemVenta.producto_id == Producto.id)
            .join(Venta,     Venta.id == ItemVenta.venta_id)
            .filter(
                Venta.creado_en >= fi,
                Venta.creado_en <= ff,
                Venta.estado == EstadoVenta.completada,
                Venta.eliminado.is_not(True),
            )
            .group_by(Producto.id, Producto.nombre)
            .order_by(func.sum(ItemVenta.cantidad).desc())
            .limit(limite)
            .all()
        )
        return [
            {"nombre": r.nombre, "cantidad": r.total_vendido or 0, "ingreso": r.total_ingreso or 0.0}
            for r in rows
        ]
    finally:
        db.close()


@router.get("/inventario")
def reporte_inventario(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        productos = (
            db.query(Producto)
            .filter(Producto.activo == True)
            .order_by(Producto.stock.asc(), Producto.nombre.asc())
            .all()
        )
        return [
            {
                "id":           p.id,
                "nombre":       p.nombre,
                "stock":        p.stock,
                "stock_minimo": p.stock_minimo,
                "precio_venta": p.precio_venta,
                "bajo_stock":   p.stock <= p.stock_minimo,
            }
            for p in productos
        ]
    finally:
        db.close()


@router.get("/cortes")
def cortes_caja(
    fecha_inicio:   date = Query(...),
    fecha_fin:      date = Query(...),
    ocultar_vacios: bool = Query(True),   # hide 0-sale, $0 phantom shifts by default
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        q = (
            db.query(CortesCaja)
            .filter(CortesCaja.abierto_en >= fi, CortesCaja.abierto_en <= ff)
        )
        if ocultar_vacios:
            # Exclude shifts that have 0 ventas AND $0 total (phantom / test shifts)
            from sqlalchemy import or_
            q = q.filter(
                or_(
                    CortesCaja.num_ventas > 0,
                    CortesCaja.total_ventas > 0,
                    CortesCaja.cerrado_en == None,  # keep open shifts even if 0 so far
                )
            )
        cortes = q.order_by(CortesCaja.abierto_en.desc()).all()

        # Los turnos guardan su propio total_ventas/num_ventas al cerrarse, pero
        # si dos turnos del mismo cajero llegan a solaparse en el tiempo (turnos
        # reconstruidos automáticamente que no deberían coexistir con el turno
        # real de ese día), la MISMA venta queda contada en los totales guardados
        # de ambos — sumar esos totales por turno infla el resultado. El resumen
        # se calcula aparte, directo sobre Venta (sin duplicados por definición),
        # para que las tarjetas de arriba siempre cuadren con la pestaña "Ventas".
        ventas_rango = (
            db.query(Venta)
            .filter(
                Venta.estado == EstadoVenta.completada,
                Venta.eliminado.is_not(True),
                Venta.creado_en >= fi,
                Venta.creado_en <= ff,
            )
            .all()
        )
        resumen_real = {
            "num_ventas":     len(ventas_rango),
            "total_ventas":   round(sum(v.total for v in ventas_rango), 2),
            "total_efectivo": round(sum(v.total for v in ventas_rango if v.metodo_pago == MetodoPago.efectivo), 2),
            "total_tarjeta":  round(sum(v.total for v in ventas_rango if v.metodo_pago == MetodoPago.tarjeta), 2),
            "total_transferencia": round(sum(v.total for v in ventas_rango if v.metodo_pago == MetodoPago.transferencia), 2),
        }

        def _solapa(a: CortesCaja, b: CortesCaja) -> bool:
            if a.id == b.id or a.usuario_id != b.usuario_id:
                return False
            a_fin = a.cerrado_en or datetime.now()
            b_fin = b.cerrado_en or datetime.now()
            return a.abierto_en <= b_fin and b.abierto_en <= a_fin

        result = []
        for c in cortes:
            dur_min = None
            if c.cerrado_en and c.abierto_en:
                dur_min = int((c.cerrado_en - c.abierto_en).total_seconds() / 60)
            ef  = c.total_efectivo or 0.0
            ape = c.monto_apertura or 0.0
            esperado = ape + ef
            dif = (c.monto_cierre - esperado) if c.monto_cierre is not None else None
            # Turno duplicado/reconstruido cuya ventana se traslapa con otro del
            # mismo cajero — sus ventas probablemente ya están contadas en el otro,
            # así que sumar el total_ventas de ambos infla el resumen del período.
            solapado = any(_solapa(c, otro) for otro in cortes)
            result.append({
                "id":               c.id,
                "cajero":           c.usuario.nombre if c.usuario else "",
                "abierto_en":       c.abierto_en.isoformat() if c.abierto_en else None,
                "cerrado_en":       c.cerrado_en.isoformat() if c.cerrado_en else None,
                "duracion_min":     dur_min,
                "num_ventas":       c.num_ventas or 0,
                "total_ventas":     c.total_ventas or 0.0,
                "total_efectivo":   ef,
                "total_tarjeta":    c.total_tarjeta or 0.0,
                "total_transferencia": c.total_transferencia or 0.0,
                "monto_apertura":   ape,
                "monto_cierre":     c.monto_cierre,
                "esperado_caja":    esperado,
                "diferencia":       dif,
                "notas":            c.notas or "",
                "abierto":          c.cerrado_en is None,
                "solapado":         solapado,
            })
        return {"cortes": result, "resumen_real": resumen_real}
    finally:
        db.close()


@router.get("/vencimientos")
def vencimientos(
    filtro: str = Query("todos"),   # todos | vencidos | por_vencer | vigentes
    dias:   int = Query(30),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        hoy = date.today()
        alerta = hoy + timedelta(days=dias)
        lotes = (
            db.query(Lote)
            .join(Producto, Lote.producto_id == Producto.id)
            .options(contains_eager(Lote.producto))   # el producto ya viene en el JOIN: sin una consulta extra por lote
            .filter(Producto.activo == True, Lote.cantidad > 0)
            .order_by(Lote.fecha_vencimiento)
            .all()
        )
        result = []
        for l in lotes:
            fv = l.fecha_vencimiento
            if fv:
                dias_rest = (fv - hoy).days
                if fv < hoy:
                    estado = "vencido"
                elif fv <= alerta:
                    estado = "por_vencer"
                else:
                    estado = "vigente"
            else:
                dias_rest = None
                estado = "sin_fecha"

            if filtro == "vencidos"    and estado != "vencido":    continue
            if filtro == "por_vencer"  and estado != "por_vencer": continue
            if filtro == "vigentes"    and estado not in ("vigente","sin_fecha"): continue

            result.append({
                "lote_id":           l.id,
                "producto_id":       l.producto_id,
                "producto":          l.producto.nombre if l.producto else "",
                "numero_lote":       l.numero_lote or "",
                "fecha_vencimiento": fv.isoformat() if fv else None,
                "cantidad":          l.cantidad,
                "dias_restantes":    dias_rest,
                "estado":            estado,
            })
        return result
    finally:
        db.close()


@router.get("/export-csv")
def export_csv(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        from app.database.models import EstadoVenta as _EV
        ventas = (
            db.query(Venta)
            .options(joinedload(Venta.items))
            .filter(
                Venta.creado_en >= fi,
                Venta.creado_en <= ff,
                Venta.estado == _EV.completada,
                Venta.eliminado.is_not(True),
            )
            .order_by(Venta.creado_en)
            .all()
        )

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Folio", "Fecha", "Subtotal", "Descuento", "IVA", "Total",
                    "Metodo Pago", "Monto Pagado", "Cambio", "Estado", "N Articulos"])
        for v in ventas:
            w.writerow([
                v.folio or v.id,
                v.creado_en.strftime("%Y-%m-%d %H:%M") if v.creado_en else "",
                round(v.subtotal, 2),
                round(v.descuento, 2),
                round(v.iva, 2),
                round(v.total, 2),
                v.metodo_pago.value,
                round(v.monto_pagado, 2),
                round(v.cambio, 2),
                v.estado.value,
                len(v.items),
            ])

        buf.seek(0)
        filename = f"ventas_{fecha_inicio}_{fecha_fin}.csv"
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),  # utf-8-sig = Excel-compatible BOM
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        db.close()


MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]


def _build_cierre_mensual_pdf_bytes(mes: int, anio: int) -> bytes:  # noqa: C901
    """Generate RESICO monthly closing PDF — constancia/INFONAVIT style."""
    import calendar
    import app.config as cfg
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, KeepTogether,
                                    HRFlowable, Flowable, PageBreak)

    # ── Signature-line Flowable (canvas) ─────────────────────────────────────
    class _SigLine(Flowable):
        def __init__(self, w, label, subtext=""):
            super().__init__()
            self.width = w; self.height = 1.6 * cm
            self.label = label; self.subtext = subtext
        def draw(self):
            c = self.canv; cx = self.width / 2
            c.saveState()
            c.setStrokeColor(colors.HexColor("#1d2140"))
            c.setLineWidth(0.6)
            pad = 0.8 * cm
            c.line(pad, 0.85 * cm, self.width - pad, 0.85 * cm)
            c.setFont("Helvetica-Bold", 6.5)
            c.setFillColor(colors.HexColor("#1d2140"))
            c.drawCentredString(cx, 0.55 * cm, self.label)
            if self.subtext:
                c.setFont("Helvetica", 6)
                c.setFillColor(colors.HexColor("#64748B"))
                c.drawCentredString(cx, 0.32 * cm, self.subtext)
            c.restoreState()
        def wrap(self, aw, ah): return self.width, self.height

    # ── Palette (constancia: almost monochrome, navy accent) ─────────────────
    C_NAVY  = colors.HexColor("#0D1B3E")
    C_NAVY2 = colors.HexColor("#1d2140")
    C_DARK  = colors.HexColor("#0F172A")
    C_MUTED = colors.HexColor("#64748B")
    C_LINE  = colors.HexColor("#CBD5E1")
    C_LIGHT = colors.HexColor("#F1F5F9")
    C_WHITE = colors.white
    C_BLACK = colors.black
    C_GOLD  = colors.HexColor("#92400E")  # dark amber for totals

    W, H = letter
    _, last_day = calendar.monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin    = date(anio, mes, last_day)
    fi, ff       = _rango(fecha_inicio, fecha_fin)
    nombre_mes   = MESES_ES[mes - 1]
    per_label    = f"{nombre_mes} {anio}".upper()
    now_str      = datetime.now().strftime("%d/%m/%Y %H:%M")
    rfc_val      = cfg.PHARMACY_RFC

    styles = getSampleStyleSheet()
    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    # Constancia typography
    s_title  = sty("_t",  fontSize=13, textColor=C_NAVY,  fontName="Helvetica-Bold", leading=16, alignment=TA_CENTER)
    s_sub    = sty("_s",  fontSize=8,  textColor=C_MUTED, fontName="Helvetica",      leading=12, alignment=TA_CENTER)
    s_fld_l  = sty("_fl", fontSize=6,  textColor=C_MUTED, fontName="Helvetica-Bold", leading=8)
    s_fld_v  = sty("_fv", fontSize=9,  textColor=C_DARK,  fontName="Helvetica-Bold", leading=13)
    s_fld_vr = sty("_fr", fontSize=9,  textColor=C_DARK,  fontName="Helvetica-Bold", leading=13, alignment=TA_RIGHT)
    s_body   = sty("_b",  fontSize=8,  textColor=C_DARK,  fontName="Helvetica",      leading=12)
    s_th     = sty("_h",  fontSize=7.5,textColor=C_WHITE, fontName="Helvetica-Bold", leading=11, alignment=TA_CENTER)
    s_th_l   = sty("_hl", fontSize=7.5,textColor=C_WHITE, fontName="Helvetica-Bold", leading=11)
    s_td     = sty("_d",  fontSize=7.5,textColor=C_DARK,  fontName="Helvetica",      leading=11)
    s_td_r   = sty("_dr", fontSize=7.5,textColor=C_DARK,  fontName="Helvetica",      leading=11, alignment=TA_RIGHT)
    s_td_c   = sty("_dc", fontSize=7.5,textColor=C_DARK,  fontName="Helvetica",      leading=11, alignment=TA_CENTER)
    s_td_b   = sty("_db", fontSize=7.5,textColor=C_DARK,  fontName="Helvetica-Bold", leading=11)
    s_td_br  = sty("_dbr",fontSize=7.5,textColor=C_DARK,  fontName="Helvetica-Bold", leading=11, alignment=TA_RIGHT)
    s_mut    = sty("_m",  fontSize=6.5,textColor=C_MUTED, fontName="Helvetica",      leading=10)
    s_mut_c  = sty("_mc", fontSize=6.5,textColor=C_MUTED, fontName="Helvetica",      leading=10, alignment=TA_CENTER)
    s_mut_r  = sty("_mr", fontSize=6.5,textColor=C_MUTED, fontName="Helvetica",      leading=10, alignment=TA_RIGHT)
    s_legal  = sty("_lg", fontSize=6.5,textColor=C_MUTED, fontName="Helvetica",      leading=9.5, alignment=TA_JUSTIFY)

    cw = W - 3.6 * cm   # narrower margins = more table space, constancia feel

    # ── Header / footer drawn on canvas ──────────────────────────────────────
    def _on_page(canvas, doc):
        canvas.saveState()
        # Navy full-width top bar (constancia style)
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, H - 1.35 * cm, W, 1.35 * cm, fill=1, stroke=0)
        # Thin gold rule below bar
        canvas.setStrokeColor(colors.HexColor("#B45309"))
        canvas.setLineWidth(1.5)
        canvas.line(0, H - 1.35 * cm, W, H - 1.35 * cm)
        # Header text
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(C_WHITE)
        canvas.drawString(1.8 * cm, H - 0.85 * cm, cfg.PHARMACY_NAME)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#93C5FD"))
        canvas.drawRightString(W - 1.8 * cm, H - 0.85 * cm,
                               f"RFC: {rfc_val}  ·  RESICO  ·  {per_label}")
        # Footer rule
        canvas.setStrokeColor(C_NAVY)
        canvas.setLineWidth(1.0)
        canvas.line(1.8 * cm, 1.9 * cm, W - 1.8 * cm, 1.9 * cm)
        canvas.setLineWidth(0.3)
        canvas.setStrokeColor(C_LINE)
        canvas.line(1.8 * cm, 1.75 * cm, W - 1.8 * cm, 1.75 * cm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(1.8 * cm, 1.4 * cm, f"Generado: {now_str}")
        canvas.drawCentredString(W / 2, 1.4 * cm,
                                 f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}")
        canvas.drawRightString(W - 1.8 * cm, 1.4 * cm,
                               f"Página {doc.page}")
        canvas.restoreState()

    # ── Query ─────────────────────────────────────────────────────────────────
    db = get_db_session()
    try:
        ventas = (
            db.query(Venta)
            .options(selectinload(Venta.usuario), selectinload(Venta.cliente))
            .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .order_by(Venta.creado_en)
            .all()
        )
        total_ingresos = sum(v.total for v in ventas)
        num_ventas     = len(ventas)
        ef  = sum(v.total for v in ventas if v.metodo_pago.value == "efectivo")
        tj  = sum(v.total for v in ventas if v.metodo_pago.value == "tarjeta")
        tr  = sum(v.total for v in ventas if v.metodo_pago.value == "transferencia")
        tick_prom = total_ingresos / num_ventas if num_ventas else 0.0
        por_dia: dict[str, dict] = {}
        for v in ventas:
            d = v.creado_en.date().isoformat() if v.creado_en else "?"
            if d not in por_dia:
                por_dia[d] = {"ef": 0.0, "tj": 0.0, "tr": 0.0, "n": 0}
            pv = v.metodo_pago.value
            por_dia[d]["ef"] += v.total if pv == "efectivo"      else 0
            por_dia[d]["tj"] += v.total if pv == "tarjeta"       else 0
            por_dia[d]["tr"] += v.total if pv == "transferencia" else 0
            por_dia[d]["n"]  += 1
        dias_con_vta = len(por_dia)

        def money(v): return f"${v:,.2f}"

        story = []

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE 1 — PORTADA estilo CONSTANCIA (centrada, formal)
        # ═══════════════════════════════════════════════════════════════════
        story.append(Spacer(1, 0.4 * cm))

        # Título centrado grande
        story.append(Paragraph(
            "DECLARACIÓN MENSUAL DE INGRESOS",
            sty("pt", fontSize=15, textColor=C_NAVY, fontName="Helvetica-Bold",
                leading=19, alignment=TA_CENTER),
        ))
        story.append(Paragraph(
            "Régimen Simplificado de Confianza — RESICO",
            sty("ps2", fontSize=9, textColor=C_MUTED, fontName="Helvetica",
                leading=13, alignment=TA_CENTER),
        ))
        story.append(Spacer(1, 0.25 * cm))
        story.append(HRFlowable(
            width=cw, thickness=2, color=C_NAVY, spaceAfter=3,
        ))
        story.append(HRFlowable(
            width=cw, thickness=0.5, color=colors.HexColor("#B45309"),
            spaceBefore=2, spaceAfter=0,
        ))
        story.append(Spacer(1, 0.3 * cm))

        # Grid de campos estilo constancia — 4 celdas (2×2)
        def _campo(label, value, align=TA_LEFT):
            return [
                Paragraph(label, s_fld_l),
                Paragraph(value, sty(f"fv{label[:3]}",
                                     fontSize=9, textColor=C_DARK,
                                     fontName="Helvetica-Bold", leading=13,
                                     alignment=align)),
            ]

        campos_t = Table([
            [
                _campo("CONTRIBUYENTE", cfg.PHARMACY_NAME),
                _campo("R.F.C.", rfc_val),
                _campo("PERÍODO", per_label, TA_CENTER),
                _campo("EJERCICIO", str(anio), TA_CENTER),
            ],
            [
                _campo("DOMICILIO FISCAL", cfg.PHARMACY_ADDRESS),
                _campo("TELÉFONO", cfg.PHARMACY_PHONE),
                _campo("FECHA INICIO", fecha_inicio.strftime("%d/%m/%Y"), TA_CENTER),
                _campo("FECHA FIN", fecha_fin.strftime("%d/%m/%Y"), TA_CENTER),
            ],
        ], colWidths=[cw * 0.38, cw * 0.22, cw * 0.20, cw * 0.20])
        campos_t.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.8, C_NAVY),
            ("INNERGRID",     (0, 0), (-1, -1), 0.4, C_LINE),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#F8FAFC")),
        ]))
        story.append(campos_t)
        story.append(Spacer(1, 0.45 * cm))

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE 2 — RESUMEN FINANCIERO (6 campos en tabla formal)
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph(
            "I.  RESUMEN FINANCIERO DEL PERÍODO",
            sty("s2t", fontSize=8, textColor=C_NAVY, fontName="Helvetica-Bold",
                leading=11, spaceBefore=0),
        ))
        story.append(HRFlowable(width=cw, thickness=0.5, color=C_NAVY,
                                spaceAfter=4, spaceBefore=2))

        # 3 columnas: concepto | importe | notas
        fin_data = [
            [Paragraph("<b>CONCEPTO</b>", s_th_l),
             Paragraph("<b>IMPORTE</b>", s_th),
             Paragraph("<b>% DEL TOTAL</b>", s_th)],
        ]
        def pct(v): return f"{v/total_ingresos*100:.1f}%" if total_ingresos else "—"
        rows_fin = [
            ("Ingresos Totales del Período",  money(total_ingresos), "100.0%", True),
            ("   · Efectivo",                 money(ef),             pct(ef),  False),
            ("   · Tarjeta bancaria",          money(tj),             pct(tj),  False),
            ("   · Transferencia / depósito",  money(tr),             pct(tr),  False),
            ("Número de transacciones",        str(num_ventas),       f"{dias_con_vta} días hábiles", False),
            ("Ticket promedio por venta",      money(tick_prom),      "—",      False),
        ]
        for concepto, importe, nota, bold in rows_fin:
            fs = s_td_b if bold else s_td
            fr = s_td_br if bold else s_td_r
            fin_data.append([
                Paragraph(concepto, fs),
                Paragraph(importe,  fr),
                Paragraph(nota,     s_td_c),
            ])
        fin_t = Table(fin_data, colWidths=[cw * 0.52, cw * 0.26, cw * 0.22])
        fin_t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  C_NAVY2),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
            ("LINEBELOW",      (0, 0), (-1, 0),  1.0, C_NAVY),
            ("LINEBELOW",      (0, 1), (-1, 1),  1.0, C_NAVY2),
            ("BOX",            (0, 0), (-1, -1), 0.6, C_NAVY),
            ("INNERGRID",      (0, 1), (-1, -1), 0.25, C_LINE),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(fin_t)
        story.append(Spacer(1, 0.5 * cm))

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE 3 — RESUMEN DIARIO
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph(
            "II.  DESGLOSE DIARIO DE INGRESOS",
            sty("s3t", fontSize=8, textColor=C_NAVY, fontName="Helvetica-Bold", leading=11),
        ))
        story.append(HRFlowable(width=cw, thickness=0.5, color=C_NAVY,
                                spaceAfter=4, spaceBefore=2))

        COL_D = [3.5*cm, 1.6*cm, 3.0*cm, 3.0*cm, 3.4*cm, None]
        dia_data = [[
            Paragraph("<b>Fecha</b>",            s_th_l),
            Paragraph("<b>Ops.</b>",              s_th),
            Paragraph("<b>Efectivo</b>",          s_th),
            Paragraph("<b>Tarjeta</b>",           s_th),
            Paragraph("<b>Transferencia</b>",     s_th),
            Paragraph("<b>Total del Día</b>",     s_th),
        ]]
        t_ef = t_tj = t_tr = t_tot = 0.0; t_n = 0
        for d_iso in sorted(por_dia):
            row = por_dia[d_iso]
            tot = row["ef"] + row["tj"] + row["tr"]
            t_ef += row["ef"]; t_tj += row["tj"]; t_tr += row["tr"]
            t_tot += tot;      t_n  += row["n"]
            try:
                d_obj = date.fromisoformat(d_iso)
                d_fmt = d_obj.strftime("%a %d/%m/%Y").capitalize()
            except Exception:
                d_fmt = d_iso
            dia_data.append([
                Paragraph(d_fmt,                                   s_td),
                Paragraph(str(row["n"]),                           s_td_c),
                Paragraph(money(row["ef"]) if row["ef"] else "—",  s_td_r),
                Paragraph(money(row["tj"]) if row["tj"] else "—",  s_td_r),
                Paragraph(money(row["tr"]) if row["tr"] else "—",  s_td_r),
                Paragraph(f"<b>{money(tot)}</b>",
                          sty(f"dt{d_iso}", fontSize=7.5, textColor=C_NAVY2,
                              fontName="Helvetica-Bold", leading=11, alignment=TA_RIGHT)),
            ])
        # Total final row
        dia_data.append([
            Paragraph("<b>TOTAL DEL MES</b>",  s_th_l),
            Paragraph(f"<b>{t_n}</b>",         s_th),
            Paragraph(f"<b>{money(t_ef)}</b>", s_th),
            Paragraph(f"<b>{money(t_tj)}</b>", s_th),
            Paragraph(f"<b>{money(t_tr)}</b>", s_th),
            Paragraph(f"<b>{money(t_tot)}</b>",
                      sty("_ttot", fontSize=8, textColor=colors.HexColor("#FDE68A"),
                          fontName="Helvetica-Bold", leading=12, alignment=TA_RIGHT)),
        ])
        lr = len(dia_data) - 1
        dia_t = Table(dia_data, colWidths=COL_D)
        dia_t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0),      (-1, 0),      C_NAVY2),
            ("BACKGROUND",     (0, lr),     (-1, lr),     C_NAVY),
            ("ROWBACKGROUNDS", (0, 1),      (-1, lr - 1), [C_WHITE, C_LIGHT]),
            ("BOX",            (0, 0),      (-1, -1),     0.6, C_NAVY),
            ("INNERGRID",      (0, 1),      (-1, lr - 1), 0.25, C_LINE),
            ("LINEBELOW",      (0, 0),      (-1, 0),      0.8, C_NAVY),
            ("LINEABOVE",      (0, lr),     (-1, lr),     1.0, C_NAVY),
            ("VALIGN",         (0, 0),      (-1, -1),     "MIDDLE"),
            ("TOPPADDING",     (0, 0),      (-1, -1),     5),
            ("BOTTOMPADDING",  (0, 0),      (-1, -1),     5),
            ("LEFTPADDING",    (0, 0),      (-1, -1),     6),
            ("RIGHTPADDING",   (0, 0),      (-1, -1),     6),
        ]))
        story.append(KeepTogether(dia_t) if len(dia_data) <= 24 else dia_t)
        story.append(Spacer(1, 0.5 * cm))

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE 4 — DETALLE DE TRANSACCIONES
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph(
            f"III.  DETALLE DE TRANSACCIONES  ({num_ventas} registros)",
            sty("s4t", fontSize=8, textColor=C_NAVY, fontName="Helvetica-Bold", leading=11),
        ))
        story.append(HRFlowable(width=cw, thickness=0.5, color=C_NAVY,
                                spaceAfter=4, spaceBefore=2))

        pago_lbl = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transf."}
        v_data = [[
            Paragraph("<b>Folio</b>",   s_th),
            Paragraph("<b>Fecha</b>",   s_th),
            Paragraph("<b>Hora</b>",    s_th),
            Paragraph("<b>Cajero</b>",  s_th_l),
            Paragraph("<b>Importe</b>", s_th),
            Paragraph("<b>Pago</b>",    s_th),
        ]]
        for v in ventas:
            cajero  = (v.usuario.nombre or v.usuario.username) if v.usuario else "—"
            pv      = v.metodo_pago.value if v.metodo_pago else ""
            fecha_s = v.creado_en.strftime("%d/%m/%Y") if v.creado_en else "—"
            hora_s  = v.creado_en.strftime("%H:%M")    if v.creado_en else "—"
            v_data.append([
                Paragraph(str(v.folio or v.id), s_td_b),
                Paragraph(fecha_s,              s_mut),
                Paragraph(hora_s,               s_mut_c),
                Paragraph((cajero or "—")[:22], s_td),
                Paragraph(money(v.total),        s_td_br),
                Paragraph(pago_lbl.get(pv, pv), s_mut_c),
            ])
        v_t = Table(v_data, colWidths=[2.0*cm, 2.8*cm, 1.6*cm, None, 2.8*cm, 2.2*cm])
        v_t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  C_NAVY2),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
            ("BOX",            (0, 0), (-1, -1), 0.6, C_NAVY),
            ("INNERGRID",      (0, 1), (-1, -1), 0.25, C_LINE),
            ("LINEBELOW",      (0, 0), (-1, 0),  0.8, C_NAVY),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        story.append(v_t)
        story.append(Spacer(1, 0.6 * cm))

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE 5 — CIERRE FORMAL CON FIRMAS
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph(
            "IV.  RESUMEN DE CIERRE Y FIRMAS",
            sty("s5t", fontSize=8, textColor=C_NAVY, fontName="Helvetica-Bold", leading=11),
        ))
        story.append(HRFlowable(width=cw, thickness=0.5, color=C_NAVY,
                                spaceAfter=4, spaceBefore=2))

        # Total box — ancho completo
        total_box = Table([[
            Table([
                [Paragraph("TOTAL DE INGRESOS A DECLARAR AL SAT",
                           sty("tb1", fontSize=7, textColor=C_MUTED,
                               fontName="Helvetica-Bold", leading=10,
                               alignment=TA_CENTER))],
                [Paragraph(money(total_ingresos),
                           sty("tb2", fontSize=20, textColor=C_NAVY,
                               fontName="Helvetica-Bold", leading=24,
                               alignment=TA_CENTER))],
                [Paragraph(f"Período: {per_label}  ·  RFC: {rfc_val}",
                           sty("tb3", fontSize=7, textColor=C_MUTED,
                               fontName="Helvetica", leading=10,
                               alignment=TA_CENTER))],
            ], colWidths=[cw - 0.4 * cm]),
        ]], colWidths=[cw])
        total_box.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 1.2, C_NAVY),
            ("LINEBELOW",     (0, 0), (-1, 0),  4,   C_NAVY),
            ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))
        story.append(total_box)
        story.append(Spacer(1, 0.9 * cm))

        # 3 líneas de firma simétricas — más altas
        class _SigLineWide(_SigLine):
            def __init__(self, w, label, subtext=""):
                super().__init__(w, label, subtext)
                self.height = 2.4 * cm  # más espacio para firmar

        sw = cw / 3
        sig_row = Table([[
            _SigLineWide(sw, "Firma y Sello del Contador Público",
                         "Cédula Profesional / RFC del Contador"),
            _SigLineWide(sw, "Vo. Bo. del Responsable del Negocio",
                         cfg.PHARMACY_NAME),
            _SigLineWide(sw, "Fecha de Revisión y Entrega",
                         "dd / mm / aaaa"),
        ]], colWidths=[sw, sw, sw])
        sig_row.setStyle(TableStyle([
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ]))
        story.append(sig_row)
        story.append(Spacer(1, 0.9 * cm))

        # ═══════════════════════════════════════════════════════════════════
        # BLOQUE QR — estilo constancia SAT / situación fiscal
        # ═══════════════════════════════════════════════════════════════════
        import qrcode as _qrcode
        import io as _io
        from reportlab.platypus import Image as RLImage

        qr_content = (
            f"CONTRIBUYENTE:{cfg.PHARMACY_NAME} "
            f"RFC:{rfc_val} "
            f"REGIMEN:RESICO "
            f"PERIODO:{per_label} "
            f"INGRESOS:{money(total_ingresos)} "
            f"TRANSACCIONES:{num_ventas} "
            f"DOMICILIO:{cfg.PHARMACY_ADDRESS} "
            f"GENERADO:{now_str}"
        )

        qr_img = _qrcode.QRCode(
            version=None,
            error_correction=_qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr_img.add_data(qr_content)
        qr_img.make(fit=True)
        pil_img = qr_img.make_image(fill_color="black", back_color="white")
        qr_buf = _io.BytesIO()
        pil_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)

        qr_size = 2.8 * cm
        qr_rl = RLImage(qr_buf, width=qr_size, height=qr_size)

        # QR izquierda, info derecha
        info_col = cw - qr_size - 0.4 * cm
        qr_block = Table([[
            qr_rl,
            [
                Paragraph(
                    "VERIFICACIÓN DEL DOCUMENTO",
                    sty("qrtit", fontSize=7, textColor=C_NAVY,
                        fontName="Helvetica-Bold", leading=10),
                ),
                Spacer(1, 5),
                Paragraph(
                    f"<b>Contribuyente:</b> {cfg.PHARMACY_NAME}<br/>"
                    f"<b>RFC:</b> {rfc_val}<br/>"
                    f"<b>Régimen:</b> Simplificado de Confianza (RESICO)<br/>"
                    f"<b>Período:</b> {per_label}&nbsp;&nbsp;&nbsp;"
                    f"<b>Total declarado:</b> {money(total_ingresos)}<br/>"
                    f"<b>Domicilio:</b> {cfg.PHARMACY_ADDRESS}<br/>"
                    f"<b>Generado:</b> {now_str}",
                    sty("qrdet", fontSize=7, textColor=C_MUTED,
                        fontName="Helvetica", leading=11),
                ),
                Spacer(1, 5),
                Paragraph(
                    "Escanee el código QR para verificar los datos de esta declaración.",
                    sty("qrhint", fontSize=6, textColor=C_MUTED,
                        fontName="Helvetica", leading=9),
                ),
            ],
        ]], colWidths=[qr_size + 0.4 * cm, info_col])
        qr_block.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.6, C_NAVY),
            ("LINEBEFORE",    (1, 0), (1, -1),  0.4, C_LINE),
            ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (0, -1),  8),
            ("RIGHTPADDING",  (0, 0), (0, -1),  8),
            ("LEFTPADDING",   (1, 0), (1, -1),  10),
            ("RIGHTPADDING",  (1, 0), (1, -1),  10),
            ("ALIGN",         (0, 0), (0, -1),  "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(Spacer(1, 1.8 * cm))
        story.append(KeepTogether(qr_block))
        story.append(Spacer(1, 0.5 * cm))
        story.append(HRFlowable(width=cw, thickness=0.4, color=C_LINE, spaceAfter=5))
        story.append(Paragraph(
            "Este documento ha sido generado electrónicamente por el sistema de Punto de Venta. "
            "Los ingresos consignados corresponden a las ventas realizadas y registradas durante el período indicado "
            "para efectos de declaración mensual bajo el Régimen Simplificado de Confianza (RESICO) conforme al "
            "Título IV, Capítulo II, Sección IV de la Ley del Impuesto Sobre la Renta (LISR). "
            "Este reporte no sustituye al CFDI, ni a la declaración fiscal oficial presentada ante el SAT.",
            s_legal,
        ))

    finally:
        db.close()

    # ── Build ─────────────────────────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    try:
        doc = SimpleDocTemplate(
            tmp.name,
            pagesize=letter,
            rightMargin=1.8*cm, leftMargin=1.8*cm,
            topMargin=1.9*cm, bottomMargin=2.4*cm,
            title=f"Declaración RESICO {per_label} — {cfg.PHARMACY_NAME}",
        )
        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
        with open(tmp.name, "rb") as f:
            data = f.read()
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass

    return data


@router.get("/cierre-mensual-pdf")
def cierre_mensual_pdf(
    mes:  int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020, le=2100),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    data     = _build_cierre_mensual_pdf_bytes(mes, anio)
    filename = f"Cierre_RESICO_{MESES_ES[mes-1]}_{anio}.pdf"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class _SaveCierrePdfBody(BaseModel):
    path: str


@router.post("/save-cierre-mensual-pdf")
def save_cierre_mensual_pdf(
    body: _SaveCierrePdfBody,
    mes:  int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020, le=2100),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    if not body.path:
        raise HTTPException(status_code=400, detail="path requerido")
    data = _build_cierre_mensual_pdf_bytes(mes, anio)
    with open(body.path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": body.path}


def _build_ventas_pdf_bytes(fecha_inicio: date, fecha_fin: date) -> bytes:  # noqa: C901
    """Generate ventas PDF for given period; return raw bytes."""
    import app.config as cfg
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable,
                                    KeepTogether, PageBreak)

    W, H = letter
    fi, ff = _rango(fecha_inicio, fecha_fin)
    now_str  = datetime.now().strftime("%d/%m/%Y %H:%M")
    per_label = f"{fecha_inicio.strftime('%d/%m/%Y')} — {fecha_fin.strftime('%d/%m/%Y')}"

    # Palette
    C_BLUE  = colors.HexColor("#1d2140")
    C_BLUE_L = colors.HexColor("#EFF6FF")
    C_BLUE_M = colors.HexColor("#BFDBFE")
    C_DARK  = colors.HexColor("#0F172A")
    C_MUTED = colors.HexColor("#64748B")
    C_GREEN = colors.HexColor("#16A34A")
    C_GRN_L = colors.HexColor("#DCFCE7")
    C_AMBER = colors.HexColor("#D97706")
    C_AMB_L = colors.HexColor("#FEF3C7")
    C_PURP  = colors.HexColor("#7C3AED")
    C_PURP_L = colors.HexColor("#F5F3FF")
    C_GRAY  = colors.HexColor("#F1F5F9")
    C_GRAY_B = colors.HexColor("#E2E8F0")
    C_WHITE = colors.white
    C_RED   = colors.HexColor("#EF4444")

    styles = getSampleStyleSheet()
    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    s_body  = sty("_b",  fontSize=8,  textColor=C_DARK,  fontName="Helvetica",      leading=12)
    s_bold  = sty("_bb", fontSize=8,  textColor=C_DARK,  fontName="Helvetica-Bold", leading=12)
    s_hdr   = sty("_h",  fontSize=8,  textColor=C_WHITE, fontName="Helvetica-Bold", leading=12, alignment=TA_CENTER)
    s_ctr   = sty("_c",  fontSize=8,  textColor=C_DARK,  fontName="Helvetica",      leading=12, alignment=TA_CENTER)
    s_right = sty("_r",  fontSize=8,  textColor=C_DARK,  fontName="Helvetica",      leading=12, alignment=TA_RIGHT)
    s_mut   = sty("_m",  fontSize=7,  textColor=C_MUTED, fontName="Helvetica",      leading=11)

    cw = W - 3.0 * cm
    story = []

    def _on_cover(canvas, doc):
        pass

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColorRGB(0.886, 0.91, 0.941)
        canvas.setLineWidth(0.5)
        canvas.line(1.5 * cm, H - 1.6 * cm, W - 1.5 * cm, H - 1.6 * cm)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColorRGB(0.114, 0.129, 0.251)
        canvas.drawString(1.5 * cm, H - 1.3 * cm, cfg.PHARMACY_NAME)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColorRGB(0.392, 0.455, 0.545)
        canvas.drawRightString(W - 1.5 * cm, H - 1.3 * cm, f"Reporte de Ventas  ·  {per_label}")
        canvas.line(1.5 * cm, 1.5 * cm, W - 1.5 * cm, 1.5 * cm)
        canvas.drawString(1.5 * cm, 1.2 * cm, now_str)
        canvas.drawCentredString(W / 2, 1.2 * cm, f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}")
        canvas.drawRightString(W - 1.5 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    # ── Query data ───────────────────────────────────────────────────────────
    db = get_db_session()
    try:
        ventas = (
            db.query(Venta)
            .options(selectinload(Venta.usuario),
                     selectinload(Venta.cliente))
            .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .order_by(Venta.creado_en)
            .all()
        )

        total_ventas = sum(v.total for v in ventas)
        num_ventas   = len(ventas)
        ef           = sum(v.total for v in ventas if v.metodo_pago.value == "efectivo")
        tj           = sum(v.total for v in ventas if v.metodo_pago.value == "tarjeta")
        tr           = sum(v.total for v in ventas if v.metodo_pago.value == "transferencia")
        tick_prom    = total_ventas / num_ventas if num_ventas else 0.0

        # Top productos
        top = (
            db.query(
                Producto.nombre,
                func.sum(ItemVenta.cantidad).label("qty"),
                func.sum(ItemVenta.subtotal).label("ing"),
            )
            .join(ItemVenta, ItemVenta.producto_id == Producto.id)
            .join(Venta,     Venta.id == ItemVenta.venta_id)
            .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .group_by(Producto.id, Producto.nombre)
            .order_by(func.sum(ItemVenta.cantidad).desc())
            .limit(15)
            .all()
        )

        def money(v): return f"${v:,.2f}"
        def fmtDT(v): return v.strftime("%d/%m/%Y %H:%M") if v else "—"

        # ── Cover / Header ───────────────────────────────────────────────────
        cover_data = [[
            [
                Paragraph(f"<b>REPORTE DE VENTAS</b>",
                          sty("ch", fontSize=20, textColor=C_WHITE, fontName="Helvetica-Bold",
                              leading=24, alignment=TA_CENTER)),
                Spacer(1, 6),
                Paragraph(cfg.PHARMACY_NAME,
                          sty("cn", fontSize=11, textColor=colors.HexColor("#93C5FD"),
                              fontName="Helvetica", alignment=TA_CENTER)),
                Spacer(1, 4),
                Paragraph(f"Período: {per_label}",
                          sty("cp", fontSize=9, textColor=colors.HexColor("#CBD5E1"),
                              fontName="Helvetica", alignment=TA_CENTER)),
            ]
        ]]
        cover_t = Table(cover_data, colWidths=[cw])
        cover_t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 20),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
            ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ]))
        story.append(cover_t)
        story.append(Spacer(1, 0.35 * cm))

        # ── KPI row ──────────────────────────────────────────────────────────
        kpi_items = [
            (money(total_ventas), "Total Ventas",     C_BLUE,  C_BLUE_L),
            (str(num_ventas),     "Transacciones",    C_GREEN, C_GRN_L),
            (money(tick_prom),    "Ticket Promedio",  C_AMBER, C_AMB_L),
            (money(ef),           "Efectivo",         C_GREEN, C_GRN_L),
            (money(tj),           "Tarjeta",          C_BLUE,  C_BLUE_L),
            (money(tr),           "Transferencia",    C_PURP,  C_PURP_L),
        ]
        kpi_cells = []
        kpi_w = []
        for val, lbl, tc, bg in kpi_items:
            cell = Table([[
                [Paragraph(f"<b>{val}</b>",
                           sty(f"kv{lbl[:2]}", fontSize=12, textColor=tc,
                               fontName="Helvetica-Bold", leading=15, alignment=TA_CENTER)),
                 Paragraph(lbl, sty(f"kl{lbl[:2]}", fontSize=7, textColor=C_MUTED,
                                    fontName="Helvetica", alignment=TA_CENTER))]
            ]], colWidths=[cw / 6 - 0.2 * cm])
            cell.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), bg),
                ("BOX",           (0, 0), (-1, -1), 0.5, C_GRAY_B),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING",   (0, 0), (-1, -1), 4),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ]))
            kpi_cells.append(cell)
            kpi_w.append(cw / 6)
        kpi_row = Table([kpi_cells], colWidths=kpi_w)
        kpi_row.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ]))
        story.append(KeepTogether(kpi_row))
        story.append(Spacer(1, 0.35 * cm))

        # ── Top productos ─────────────────────────────────────────────────────
        if top:
            top_data = [[Paragraph("<b>#</b>", s_hdr),
                         Paragraph("<b>Producto</b>", s_hdr),
                         Paragraph("<b>Unidades</b>", s_hdr),
                         Paragraph("<b>Ingreso</b>", s_hdr)]]
            medals = ["#F59E0B", "#94A3B8", "#B45309"]
            for i, r in enumerate(top):
                clr = colors.HexColor(medals[i]) if i < 3 else C_MUTED
                top_data.append([
                    Paragraph(f"<b>{i+1}</b>",
                               sty(f"tm{i}", fontSize=9, textColor=clr,
                                   fontName="Helvetica-Bold", alignment=TA_CENTER)),
                    Paragraph(r.nombre or "—", s_body),
                    Paragraph(str(int(r.qty or 0)),
                               sty(f"tq{i}", fontSize=8, textColor=C_BLUE,
                                   fontName="Helvetica-Bold", alignment=TA_CENTER)),
                    Paragraph(money(r.ing or 0),
                               sty(f"ti{i}", fontSize=8, textColor=C_GREEN,
                                   fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                ])
            top_t = Table(top_data, colWidths=[1.2 * cm, None, 3 * cm, 3.5 * cm])
            top_t.setStyle(TableStyle([
                ("BACKGROUND",     (0, 0), (-1, 0),  C_BLUE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_GRAY]),
                ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
                ("LINEBELOW",      (0, 0), (-1, 0),  1.5, C_BLUE),
                ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",     (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
                ("LEFTPADDING",    (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            # Section label
            hdr_top = Table([[Paragraph(
                "<b>🏆  Top Productos Más Vendidos</b>",
                sty("tph", fontSize=9, textColor=C_WHITE, fontName="Helvetica-Bold", leading=13)
            )]], colWidths=[cw])
            hdr_top.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ]))
            story.append(hdr_top)
            story.append(Spacer(1, 2))
            story.append(KeepTogether(top_t))
            story.append(Spacer(1, 0.35 * cm))

        # ── Ventas table ─────────────────────────────────────────────────────
        hdr_v = Table([[Paragraph(
            f"<b>📋  Detalle de Ventas  ·  {num_ventas} registros</b>",
            sty("vh", fontSize=9, textColor=C_WHITE, fontName="Helvetica-Bold", leading=13)
        )]], colWidths=[cw])
        hdr_v.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ]))
        story.append(hdr_v)
        story.append(Spacer(1, 2))

        pago_icon = {"efectivo": "💵", "tarjeta": "💳", "transferencia": "🏦"}
        v_data = [[
            Paragraph("<b>Folio</b>",   s_hdr),
            Paragraph("<b>Fecha</b>",   s_hdr),
            Paragraph("<b>Cajero</b>",  s_hdr),
            Paragraph("<b>Cliente</b>", s_hdr),
            Paragraph("<b>Total</b>",   s_hdr),
            Paragraph("<b>Pago</b>",    s_hdr),
        ]]
        for v in ventas:
            cajero  = (v.usuario.nombre or v.usuario.username) if v.usuario else "—"
            cliente = v.cliente.nombre if v.cliente else "Público gral."
            pago_val = v.metodo_pago.value if v.metodo_pago else ""
            icon = pago_icon.get(pago_val, "")
            is_ef   = pago_val == "efectivo"
            is_tj   = pago_val == "tarjeta"
            is_tr   = pago_val == "transferencia"
            tc = C_GREEN if is_ef else (C_BLUE if is_tj else C_PURP)
            v_data.append([
                Paragraph(str(v.folio or v.id), sty(f"vf{v.id}", fontSize=7, textColor=C_BLUE,
                                                     fontName="Helvetica-Bold", leading=11)),
                Paragraph(fmtDT(v.creado_en), s_mut),
                Paragraph(cajero or "—",    s_mut),
                Paragraph((cliente or "Público gral.")[:28], s_mut),
                Paragraph(money(v.total),
                           sty(f"vt{v.id}", fontSize=8, textColor=C_DARK,
                               fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=12)),
                Paragraph(f"{icon} {pago_val}",
                           sty(f"vp{v.id}", fontSize=7, textColor=tc,
                               fontName="Helvetica-Bold", leading=11)),
            ])
        v_t = Table(v_data, colWidths=[2 * cm, 3.2 * cm, 3.2 * cm, 4 * cm, 2.8 * cm, 2.8 * cm])
        v_t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  C_BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_GRAY]),
            ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
            ("LINEBELOW",      (0, 0), (-1, 0),  1.5, C_BLUE),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
        ]))
        story.append(v_t)

    finally:
        db.close()

    # ── Build PDF ─────────────────────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    try:
        doc = SimpleDocTemplate(
            tmp.name,
            pagesize=letter,
            rightMargin=1.5 * cm, leftMargin=1.5 * cm,
            topMargin=2.0 * cm, bottomMargin=2.2 * cm,
            title=f"Reporte Ventas {per_label} — {cfg.PHARMACY_NAME}",
        )
        doc.build(story, onFirstPage=_on_cover, onLaterPages=_on_page)
        with open(tmp.name, "rb") as f:
            data = f.read()
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass

    return data


@router.get("/export-pdf")
def export_pdf_ventas(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    data = _build_ventas_pdf_bytes(fecha_inicio, fecha_fin)
    filename = f"Ventas_{fecha_inicio}_{fecha_fin}.pdf"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class _SavePdfBody(BaseModel):
    path: str


@router.post("/save-pdf-to-path")
def save_pdf_to_path(
    body: _SavePdfBody,
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    if not body.path:
        raise HTTPException(status_code=400, detail="path requerido")
    data = _build_ventas_pdf_bytes(fecha_inicio, fecha_fin)
    with open(body.path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": body.path}


@router.delete("/cortes/fantasmas")
def eliminar_cortes_fantasma(bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    """Admin: permanently delete closed shifts with 0 ventas and $0 total."""
    _require_admin(payload)
    db = get_db_session()
    try:
        fantasmas = (
            db.query(CortesCaja)
            .filter(
                CortesCaja.cerrado_en != None,
                CortesCaja.num_ventas == 0,
                CortesCaja.total_ventas == 0,
            )
            .all()
        )
        ids = [c.id for c in fantasmas]
        for c in fantasmas:
            db.delete(c)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            # cortes_caja está en _NO_TURSO_DELETE — igual que retiros_caja, el
            # sync normal nunca borra por ausencia, así que sin este delete
            # explícito el corte fantasma borrado reaparecía en el próximo pull.
            # Síncrono (no bg.add_task): si la app cierra justo después de borrar
            # (p.ej. para instalar una actualización), una tarea en background se
            # pierde antes de llegar a Turso y el corte "resucita" en el próximo pull.
            delete_ids_from_turso("cortes_caja", ids)
            bg.add_task(sync_to_turso)
        return {"ok": True, "eliminados": len(ids), "ids": ids}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/rentabilidad-cajero")
def rentabilidad_cajero(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        from app.database.models import Usuario
        usuarios = db.query(Usuario).filter(Usuario.activo == True).all()
        result = []
        for u in usuarios:
            ventas = (
                db.query(Venta)
                .filter(
                    Venta.usuario_id == u.id,
                    Venta.creado_en >= fi,
                    Venta.creado_en <= ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True),
                )
                .all()
            )
            if not ventas:
                continue
            total_v = sum(v.total for v in ventas)
            iva_v = sum(v.iva or 0.0 for v in ventas)
            vids = [v.id for v in ventas]
            cost_rows = (
                db.query(ItemVenta.cantidad, ItemVenta.costo_unitario)
                .filter(ItemVenta.venta_id.in_(vids))
                .all()
            )
            total_c = sum(r.cantidad * (r.costo_unitario or 0.0) for r in cost_rows)

            # Devoluciones parciales de este cajero en el período (mismo cálculo
            # que /resumen — si no, la ganancia por cajero no coincide con la general)
            dev_movs = db.query(MovimientoStock).filter(
                MovimientoStock.tipo == TipoMovimiento.devolucion,
                MovimientoStock.referencia_tipo == "devolucion",
                MovimientoStock.usuario_id == u.id,
                MovimientoStock.creado_en >= fi,
                MovimientoStock.creado_en <= ff,
            ).all()
            total_dev = _valor_devoluciones(db, dev_movs)

            ventas_netas = total_v - total_dev
            # El IVA cobrado no es ganancia — es dinero del SAT que solo pasa por caja
            ganancia = (ventas_netas - iva_v) - total_c
            result.append({
                "cajero": u.nombre or u.username,
                "rol": u.rol.value if u.rol else "",
                "num_ventas": len(ventas),
                "total_ventas": round(total_v, 2),
                "total_costo": round(total_c, 2),
                "ganancia": round(ganancia, 2),
                "ticket_promedio": round(total_v / len(ventas), 2) if ventas else 0.0,
                "margen_pct": round(ganancia / total_v * 100, 1) if total_v else 0.0,
            })
        result.sort(key=lambda x: -x["total_ventas"])
        return result
    finally:
        db.close()


@router.get("/inventario-excel")
def exportar_inventario_excel(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from fastapi.responses import Response
    db = get_db_session()
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventario"
        headers = ["ID", "Código", "Nombre", "Categoría", "Proveedor", "Stock",
                   "Stock Mín.", "Precio Compra", "Precio Venta", "Valor Inventario",
                   "Presentación", "Activo"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(fill_type="solid", fgColor="1d2140")
        productos = (db.query(Producto).filter(Producto.activo == True)
                     .order_by(Producto.nombre).all())
        for row, p in enumerate(productos, 2):
            ws.cell(row=row, column=1, value=p.id)
            ws.cell(row=row, column=2, value=p.codigo_barras or "")
            ws.cell(row=row, column=3, value=p.nombre)
            ws.cell(row=row, column=4, value=p.categoria.nombre if p.categoria else "")
            ws.cell(row=row, column=5, value=p.proveedor.nombre if p.proveedor else "")
            ws.cell(row=row, column=6, value=p.stock)
            ws.cell(row=row, column=7, value=p.stock_minimo)
            ws.cell(row=row, column=8, value=p.precio_compra)
            ws.cell(row=row, column=9, value=p.precio_venta)
            ws.cell(row=row, column=10, value=round(p.stock * p.precio_compra, 2))
            ws.cell(row=row, column=11, value=p.presentacion or "")
            ws.cell(row=row, column=12, value="Sí" if p.activo else "No")
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=0)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)
        import io as _io
        buf = _io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=inventario.xlsx"},
        )
    finally:
        db.close()


# ── PDF de ventas, ganancias e inversión ─────────────────────────────────────
# Para el dueño: cuánto vendió, cuánto ganó (ventas − costo de lo vendido),
# cuánto metió de inversión (compras de mercancía, pagos a proveedor: retiros
# tipo "inversion" + gastos capturados) y cuánto sacó para él (retiros
# "personal"), agrupado por semana, mes o día.

_MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _costo_item(it, prod) -> tuple[float, bool]:
    """Costo de una línea vendida. Ventas por pieza de builds viejos guardaron el
    costo de la CAJA completa por cada pieza (es_pieza=0, precio de pieza): se
    divide entre las piezas por caja. Devuelve (costo_total, se_corrigio)."""
    costo = it.costo_unitario or 0.0
    upc = (prod.unidades_por_caja or 1) if prod else 1
    if (not it.es_pieza and prod is not None and upc > 1 and costo > (it.precio_unitario or 0)
            and (it.precio_unitario or 0) < (prod.precio_venta or 0) * 0.75):
        return it.cantidad * costo / upc, True
    return it.cantidad * costo, False


def _clave_periodo(d: date, agrupar: str):
    if agrupar == "mes":
        return (d.year, d.month)
    if agrupar == "dia":
        return (d.year, d.month, d.day)
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _etiqueta_periodo(clave, agrupar: str, fi: date, ff: date) -> str:
    if agrupar == "mes":
        return f"{MESES_ES[clave[1] - 1]} {clave[0]}"
    if agrupar == "dia":
        return f"{clave[2]:02d} {_MES_CORTO[clave[1] - 1]} {clave[0]}"
    lunes = date.fromisocalendar(clave[0], clave[1], 1)
    ini, fin = max(lunes, fi), min(lunes + timedelta(days=6), ff)
    if ini.month == fin.month:
        return f"Sem {clave[1]} · {ini.day}–{fin.day} {_MES_CORTO[fin.month - 1]}"
    return f"Sem {clave[1]} · {ini.day} {_MES_CORTO[ini.month - 1]}–{fin.day} {_MES_CORTO[fin.month - 1]}"


_PDF_TIPOS = {"completo": "Ventas, ganancias e inversión", "ventas": "Reporte de ventas",
              "ganancia": "Reporte de ganancias", "inversion": "Inversión y retiros"}


def _build_finanzas_pdf_bytes(fecha_inicio: date, fecha_fin: date, agrupar: str = "semana", tipo: str = "completo") -> bytes:  # noqa: C901
    """PDF para el dueño. tipo: completo | ventas | ganancia | inversion."""
    import app.config as cfg
    from app.database.models import RetiroCaja, Gasto
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
                                    PageTemplate, Frame)
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart

    if agrupar not in ("semana", "mes", "dia"):
        agrupar = "semana"
    if tipo not in _PDF_TIPOS:
        tipo = "completo"
    V = tipo in ("completo", "ventas")      # lleva ventas
    G = tipo in ("completo", "ganancia")    # lleva ganancia
    I = tipo in ("completo", "inversion")   # lleva inversión / retiros
    W, H = letter
    fi, ff = _rango(fecha_inicio, fecha_fin)
    per_label = (fecha_inicio.strftime('%d/%m/%Y') if fecha_inicio == fecha_fin
                 else f"{fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}")
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    nombre_per = {"semana": "semana", "mes": "mes", "dia": "día"}[agrupar]

    NAVY = colors.HexColor("#1d2140")
    INK, MUTED, LINE, SOFT = colors.HexColor("#0F172A"), colors.HexColor("#64748B"), colors.HexColor("#E2E8F0"), colors.HexColor("#F8FAFC")
    C_VENTA, C_COSTO, C_GAN = colors.HexColor("#2E4A8A"), colors.HexColor("#D97706"), colors.HexColor("#15803D")
    C_INV, C_GASTO, C_PERS, C_RESTO = colors.HexColor("#6D28D9"), colors.HexColor("#B45309"), colors.HexColor("#64748B"), colors.HexColor("#0891B2")
    C_RED = colors.HexColor("#B91C1C")

    base = getSampleStyleSheet()["Normal"]
    _n = [0]
    def sty(**kw):
        _n[0] += 1
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("textColor", INK)
        return ParagraphStyle(f"fz{_n[0]}", parent=base, **kw)
    s_th = sty(fontSize=7, textColor=MUTED, fontName="Helvetica-Bold", leading=9)
    s_thr = sty(fontSize=7, textColor=MUTED, fontName="Helvetica-Bold", leading=9, alignment=TA_RIGHT)
    s_txt = sty(fontSize=8, leading=10.5)
    s_num = sty(fontSize=8, leading=10.5, alignment=TA_RIGHT)
    s_numb = sty(fontSize=8, leading=10.5, alignment=TA_RIGHT, fontName="Helvetica-Bold")
    s_mut = sty(fontSize=7, textColor=MUTED, leading=9.5)
    # keepWithNext: el título nunca se queda solo al pie de una página
    s_h2 = sty(fontSize=11, fontName="Helvetica-Bold", leading=14, keepWithNext=1, spaceAfter=4)
    s_h2sub = sty(fontSize=7.5, textColor=MUTED, leading=10, keepWithNext=1, spaceBefore=-3, spaceAfter=5)
    money = lambda v: f"-${-v:,.2f}" if v < 0 else f"${v:,.2f}"
    money0 = lambda v: f"-${-v:,.0f}" if v < 0 else f"${v:,.0f}"
    cw = W - 3.0 * cm

    # ── Datos ────────────────────────────────────────────────────────────────
    db = get_db_session()
    try:
        ventas = (db.query(Venta)
                  .options(selectinload(Venta.items), selectinload(Venta.usuario))
                  .filter(Venta.creado_en >= fi, Venta.creado_en <= ff,
                          Venta.estado == EstadoVenta.completada, Venta.eliminado.is_not(True))
                  .order_by(Venta.creado_en).all())
        prod_ids = {it.producto_id for v in ventas for it in v.items}
        prods = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(prod_ids)).all()} if prod_ids else {}
        retiros = (db.query(RetiroCaja).options(selectinload(RetiroCaja.usuario))
                   .filter(RetiroCaja.creado_en >= fi, RetiroCaja.creado_en <= ff)
                   .order_by(RetiroCaja.creado_en).all())
        gastos = (db.query(Gasto).options(selectinload(Gasto.usuario))
                  .filter(Gasto.fecha >= fecha_inicio, Gasto.fecha <= fecha_fin)
                  .order_by(Gasto.fecha).all())
        dev_movs = db.query(MovimientoStock).filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_tipo == "devolucion",
            MovimientoStock.creado_en >= fi, MovimientoStock.creado_en <= ff).all()
        devoluciones = _valor_devoluciones(db, dev_movs)

        per: dict = {}
        def bucket(d):
            k = _clave_periodo(d, agrupar)
            return per.setdefault(k, {"ventas": 0.0, "costo": 0.0, "tickets": 0, "iva": 0.0,
                                      "inversion": 0.0, "personal": 0.0, "gastos": 0.0})
        por_prod: dict = {}
        lineas_corregidas = 0
        for v in ventas:
            b = bucket(v.creado_en.date())
            b["ventas"] += v.total or 0.0
            b["iva"] += v.iva or 0.0
            b["tickets"] += 1
            for it in v.items:
                c, corr = _costo_item(it, prods.get(it.producto_id))
                lineas_corregidas += corr
                b["costo"] += c
                pp = por_prod.setdefault(it.producto_id, {"piezas": 0.0, "ventas": 0.0, "costo": 0.0})
                pp["piezas"] += it.cantidad or 0
                pp["ventas"] += it.subtotal or 0.0
                pp["costo"] += c
        for r in retiros:
            bucket(r.creado_en.date())["inversion" if r.tipo == "inversion" else "personal"] += r.monto or 0.0
        for g in gastos:
            bucket(g.fecha)["gastos"] += g.monto or 0.0

        tot = {k: sum(b[k] for b in per.values()) for k in ("ventas", "costo", "tickets", "iva", "inversion", "personal", "gastos")}
        ventas_netas = tot["ventas"] - devoluciones
        ganancia = ventas_netas - tot["iva"] - tot["costo"]
        margen = (ganancia / ventas_netas * 100) if ventas_netas else 0.0
        efectivo_resto = ventas_netas - tot["inversion"] - tot["gastos"] - tot["personal"]
        ticket_prom = ventas_netas / tot["tickets"] if tot["tickets"] else 0.0
        claves = sorted(per)

        story = []

        # ── Resumen en una frase ──
        frase = ""
        if V or G:
            if not tot["tickets"]:
                frase = "No hubo ventas en este periodo. "
            elif G:
                frase = (f"En este periodo vendiste <b>{money(ventas_netas)}</b> en {tot['tickets']} tickets "
                         f"(promedio {money(ticket_prom)}) y la ganancia fue de <b><font color='#15803D'>{money(ganancia)}</font></b>, "
                         f"un margen de {margen:.1f}%. ")
            else:
                frase = (f"En este periodo vendiste <b>{money(ventas_netas)}</b> en {tot['tickets']} tickets, "
                         f"con un ticket promedio de <b>{money(ticket_prom)}</b>. ")
        if I:
            frase += (f"Invertiste <b>{money(tot['inversion'] + tot['gastos'])}</b> y retiraste <b>{money(tot['personal'])}</b> para ti; "
                      f"del efectivo de las ventas quedan <b>{money(efectivo_resto)}</b>.")
        story += [Paragraph(frase, sty(fontSize=10, leading=15)), Spacer(1, 0.45 * cm)]

        # ── Tarjetas ──
        def tarjeta(valor, titulo, nota, color):
            t = Table([[Paragraph(titulo.upper(), sty(fontSize=6.5, textColor=MUTED, fontName="Helvetica-Bold", leading=8))],
                       [Paragraph(valor, sty(fontSize=14, textColor=color, fontName="Helvetica-Bold", leading=17))],
                       [Paragraph(nota, sty(fontSize=6.5, textColor=MUTED, leading=8.5))]],
                      colWidths=[cw / 4 - 0.3 * cm])
            t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 3, color), ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                   ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                   ("TOPPADDING", (0, 0), (0, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
                                   ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, 1), 1)]))
            return t
        def fila(items):
            r = Table([[tarjeta(*i) for i in items]], colWidths=[cw / 4] * 4, hAlign="LEFT")
            r.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0.3 * cm),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            return r
        k_ventas = (money(ventas_netas), "Ventas", f"{tot['tickets']} tickets", C_VENTA)
        filas_kpi = []
        if tipo == "ventas":
            filas_kpi.append([k_ventas, (str(tot["tickets"]), "Tickets", "ventas realizadas", C_VENTA),
                              (money(ticket_prom), "Ticket promedio", "por venta", C_COSTO),
                              (money(devoluciones), "Devoluciones", "parciales del periodo", C_PERS)])
        if G:
            filas_kpi.append([k_ventas, (money(tot["costo"]), "Costo de lo vendido", "lo que costó la mercancía", C_COSTO),
                              (money(ganancia), "Ganancia", "ventas − costo", C_GAN if ganancia >= 0 else C_RED),
                              (f"{margen:.1f}%", "Margen", "ganas de cada $100 vendidos", C_GAN if margen >= 0 else C_RED)])
        if I:
            filas_kpi.append([(money(tot["inversion"]), "Inversión", "compras y pagos a proveedor", C_INV),
                              (money(tot["gastos"]), "Gastos", "renta, luz, servicios", C_GASTO),
                              (money(tot["personal"]), "Retiros personales", "lo que sacaste para ti", C_PERS),
                              (money(efectivo_resto), "Efectivo restante", "ventas − todo lo que salió", C_RESTO if efectivo_resto >= 0 else C_RED)])
        for i, items in enumerate(filas_kpi):
            if i:
                story.append(Spacer(1, 0.25 * cm))
            story.append(fila(items))
        story.append(Spacer(1, 0.55 * cm))

        def seccion(titulo, sub=None):
            out = [Paragraph(titulo, s_h2)]
            if sub:
                out.append(Paragraph(sub, s_h2sub))
            return out

        def tabla(data, widths, total=False):
            esc = cw / sum(widths)   # que siempre ocupe todo el ancho de la hoja
            t = Table(data, colWidths=[w * esc for w in widths], repeatRows=1, hAlign="LEFT")
            st = [("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
                  ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
            if total:
                st += [("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY), ("BACKGROUND", (0, -1), (-1, -1), SOFT)]
            t.setStyle(TableStyle(st))
            return t
        th = lambda h, der=False: Paragraph(h, s_thr if der else s_th)

        # ── ¿A dónde se fue el efectivo? (barra 100%) ──
        if I and ventas_netas > 0:
            partes = [("Inversión", tot["inversion"], C_INV), ("Gastos", tot["gastos"], C_GASTO),
                      ("Retiros personales", tot["personal"], C_PERS), ("Queda", max(efectivo_resto, 0), C_RESTO)]
            total_barra = sum(p[1] for p in partes) or 1
            bh = 14
            d = Drawing(cw, bh + 16)
            x = 0
            for nombre, val, col in partes:
                if val <= 0:
                    continue
                w = cw * val / total_barra
                d.add(Rect(x, 16, w, bh, fillColor=col, strokeColor=colors.white, strokeWidth=1))
                if w > 40:
                    d.add(String(x + w / 2, 20, f"{val / total_barra * 100:.0f}%", fontName="Helvetica-Bold", fontSize=7,
                                 fillColor=colors.white, textAnchor="middle"))
                x += w
            lx = 0
            for nombre, val, col in partes:
                d.add(Rect(lx, 3, 7, 7, fillColor=col, strokeColor=None))
                etiqueta = f"{nombre} {money0(val)}"
                d.add(String(lx + 10, 3.5, etiqueta, fontName="Helvetica", fontSize=7, fillColor=MUTED))
                lx += 10 + len(etiqueta) * 3.6 + 16
            story += seccion("¿A dónde se fue el efectivo de las ventas?",
                             "Del dinero que entró por ventas: cuánto se reinvirtió, se gastó, se retiró y cuánto queda.")
            story.append(d)
            if efectivo_resto < 0:
                story.append(Paragraph(f"Salió {money(-efectivo_resto)} más de lo que entró por ventas en este periodo "
                                       "(se usó efectivo de periodos anteriores).", sty(fontSize=7, textColor=C_RED, leading=9)))
            story.append(Spacer(1, 0.5 * cm))

        # ── Gráfica por periodo ──
        series = []
        if V or G:
            series.append(("Ventas", [per[k]["ventas"] for k in claves], C_VENTA))
        if G:
            series.append(("Ganancia", [per[k]["ventas"] - per[k]["iva"] - per[k]["costo"] for k in claves], C_GAN))
        if I:
            series.append(("Inversión y gastos", [per[k]["inversion"] + per[k]["gastos"] for k in claves], C_INV))
            series.append(("Retiros personales", [per[k]["personal"] for k in claves], C_PERS))
        if len(claves) >= 2 and series:
            etiquetas = []
            for k in claves:
                e = _etiqueta_periodo(k, agrupar, fecha_inicio, fecha_fin)
                etiquetas.append(e.split(" · ")[0] if agrupar == "semana" else (e[:3] + " " + e[-2:] if agrupar == "mes" else e[:6]))
            ch_h = 5.2 * cm
            d = Drawing(cw, ch_h + 18)
            bc = VerticalBarChart()
            bc.x, bc.y, bc.width, bc.height = 38, 22, cw - 44, ch_h - 14
            bc.data = [s[1] for s in series]
            bc.groupSpacing = 6 if len(claves) < 12 else 3
            bc.barSpacing = 0.5
            for i, (_, _, col) in enumerate(series):
                bc.bars[i].fillColor = col
                bc.bars[i].strokeColor = None
            bc.valueAxis.valueMin = min(0, min(min(s[1]) for s in series))
            bc.valueAxis.valueMax = max(max(max(s[1]) for s in series), 1) * 1.08
            bc.valueAxis.labels.fontName = "Helvetica"
            bc.valueAxis.labels.fontSize = 6.5
            bc.valueAxis.labels.fillColor = MUTED
            bc.valueAxis.labelTextFormat = lambda v: f"${v / 1000:.1f}k" if abs(v) >= 1000 else f"${v:.0f}"
            bc.valueAxis.strokeColor = LINE
            bc.valueAxis.visibleGrid = True
            bc.valueAxis.gridStrokeColor = LINE
            bc.valueAxis.gridStrokeWidth = 0.4
            bc.categoryAxis.categoryNames = etiquetas
            bc.categoryAxis.labels.fontName = "Helvetica"
            bc.categoryAxis.labels.fontSize = 6 if len(claves) > 10 else 6.5
            bc.categoryAxis.labels.fillColor = MUTED
            bc.categoryAxis.labels.angle = 45 if len(claves) > 12 else 0
            bc.categoryAxis.labels.boxAnchor = "ne" if len(claves) > 12 else "n"
            bc.categoryAxis.strokeColor = LINE
            d.add(bc)
            lx = cw - sum(10 + len(s[0]) * 3.7 + 14 for s in series)
            for nombre, _, col in series:
                d.add(Rect(lx, ch_h + 8, 7, 7, fillColor=col, strokeColor=None))
                d.add(String(lx + 10, ch_h + 8.5, nombre, fontName="Helvetica", fontSize=7, fillColor=MUTED))
                lx += 10 + len(nombre) * 3.7 + 14
            tit_graf = {"completo": "Ventas, ganancia e inversión", "ventas": "Ventas", "ganancia": "Ventas y ganancia",
                        "inversion": "Inversión, gastos y retiros"}[tipo]
            story.append(KeepTogether(seccion(f"{tit_graf} por {nombre_per}") + [d]))
            story.append(Spacer(1, 0.45 * cm))

        # ── Tabla por periodo (columnas según el reporte) ──
        def _g(b): return b["ventas"] - b["iva"] - b["costo"]
        cols = []   # (título, valor por periodo, total, ancho cm, estilo)
        if V or G:
            cols.append(("Ventas", lambda b: money(b["ventas"]), money(ventas_netas), 2.3, None))
        if tipo == "ventas":
            cols += [("Tickets", lambda b: str(b["tickets"]), str(tot["tickets"]), 1.6, None),
                     ("Ticket prom.", lambda b: money(b["ventas"] / b["tickets"]) if b["tickets"] else "—", money(ticket_prom), 2.2, None)]
        if G:
            cols += [("Costo", lambda b: money(b["costo"]), money(tot["costo"]), 2.2, None),
                     ("Ganancia", lambda b: money(_g(b)), money(ganancia), 2.3, "gan"),
                     ("Margen", lambda b: f"{_g(b) / b['ventas'] * 100:.1f}%" if b["ventas"] else "—", f"{margen:.1f}%", 1.5, None)]
        if tipo == "completo":
            cols.append(("Tickets", lambda b: str(b["tickets"]), str(tot["tickets"]), 1.4, None))
        if I:
            cols += [("Inversión", lambda b: money(b["inversion"]), money(tot["inversion"]), 2.1, None),
                     ("Gastos", lambda b: money(b["gastos"]), money(tot["gastos"]), 1.9, None),
                     ("Retiros pers.", lambda b: money(b["personal"]), money(tot["personal"]), 2.1, None)]
        if claves:
            ancho_per = max(3.4 * cm, cw - sum(c[3] for c in cols) * cm)
            data = [[th("Periodo")] + [th(c[0], True) for c in cols]]
            for k in claves:
                b = per[k]
                fila_t = [Paragraph(_etiqueta_periodo(k, agrupar, fecha_inicio, fecha_fin), s_txt)]
                for c in cols:
                    stl = (sty(fontSize=8, leading=10.5, alignment=TA_RIGHT, fontName="Helvetica-Bold",
                               textColor=C_GAN if _g(b) >= 0 else C_RED) if c[4] == "gan" else s_num)
                    fila_t.append(Paragraph(c[1](b), stl))
                data.append(fila_t)
            if devoluciones and (V or G):
                data.append([Paragraph("Devoluciones", s_mut)] +
                            [Paragraph(money(-devoluciones) if c[0] in ("Ventas", "Ganancia") else "", s_num) for c in cols])
            data.append([Paragraph("<b>Total</b>", s_txt)] + [Paragraph(c[2], s_numb) for c in cols])
            story += seccion(f"Detalle por {nombre_per}")
            story += [tabla(data, [ancho_per] + [c[3] * cm for c in cols], total=True), Spacer(1, 0.55 * cm)]

        # ── Inversión y gastos / retiros personales ──
        if I:
            inv = [r for r in retiros if r.tipo == "inversion"]
            story += seccion(f"Inversión y gastos · {money(tot['inversion'] + tot['gastos'])}",
                             "Retiros de caja marcados como inversión (compras de medicamento, pagos a proveedor) y gastos capturados.")
            if inv or gastos:
                data = [[th("Fecha"), th("Tipo"), th("Concepto"), th("Registró"), th("Monto", True)]]
                filas = [(r.creado_en, "Inversión", r.concepto or "—", (r.usuario.nombre or r.usuario.username) if r.usuario else "—", r.monto or 0.0) for r in inv]
                filas += [(datetime.combine(g.fecha, datetime.min.time()), f"Gasto · {g.categoria.value if g.categoria else 'otros'}", g.concepto or "—",
                           (g.usuario.nombre or g.usuario.username) if g.usuario else "—", g.monto or 0.0) for g in gastos]
                for f, t, c, u, mo in sorted(filas, key=lambda x: x[0]):
                    data.append([Paragraph(f.strftime("%d/%m/%Y"), s_txt),
                                 Paragraph(t, sty(fontSize=7, leading=9.5, textColor=C_INV if t == "Inversión" else C_GASTO, fontName="Helvetica-Bold")),
                                 Paragraph(c, s_txt), Paragraph(u, s_mut), Paragraph(money(mo), s_numb)])
                data.append([Paragraph("<b>Total</b>", s_txt), "", "", "", Paragraph(money(tot["inversion"] + tot["gastos"]), s_numb)])
                story.append(tabla(data, [2.3 * cm, 2.9 * cm, 7.6 * cm, 2.9 * cm, 2.5 * cm], total=True))
            else:
                story.append(Paragraph("No hay inversión ni gastos registrados en este periodo.", s_mut))
            story.append(Spacer(1, 0.55 * cm))

            pers = [r for r in retiros if r.tipo != "inversion"]
            story += seccion(f"Retiros personales · {money(tot['personal'])}", "Dinero que sacaste de la caja para ti, nómina u otros.")
            if pers:
                data = [[th("Fecha"), th("Concepto"), th("Registró"), th("Monto", True)]]
                for r in pers:
                    data.append([Paragraph(r.creado_en.strftime("%d/%m/%Y"), s_txt), Paragraph(r.concepto or "—", s_txt),
                                 Paragraph((r.usuario.nombre or r.usuario.username) if r.usuario else "—", s_mut),
                                 Paragraph(money(r.monto or 0.0), s_numb)])
                data.append([Paragraph("<b>Total</b>", s_txt), "", "", Paragraph(money(tot["personal"]), s_numb)])
                story.append(tabla(data, [2.3 * cm, 10.5 * cm, 2.9 * cm, 2.5 * cm], total=True))
            else:
                story.append(Paragraph("No hay retiros personales en este periodo.", s_mut))
            story.append(Spacer(1, 0.55 * cm))

        # ── Productos ──
        if (V or G) and por_prod:
            if G:
                orden = lambda kv: kv[1]["ventas"] - kv[1]["costo"]
                tit, campo = "Productos que más ganancia dejan", "Ganancia"
            else:
                orden = lambda kv: kv[1]["ventas"]
                tit, campo = "Productos más vendidos", "Ventas"
            top = sorted(por_prod.items(), key=orden, reverse=True)[:15]
            mx = max(orden(kv) for kv in top) or 1
            data = [[th("#"), th("Producto"), th("Vendidos", True), th("Ventas" if G else "Costo", True), th(campo, True), th("")]]
            for i, kv in enumerate(top, 1):
                pid, dd = kv
                p = prods.get(pid)
                val = orden(kv)
                barra = Drawing(3.2 * cm, 7)
                barra.add(Rect(0, 1, max(1, 3.2 * cm * max(val, 0) / mx), 5, fillColor=C_GAN if G else C_VENTA, strokeColor=None))
                data.append([Paragraph(str(i), s_mut), Paragraph((p.nombre if p else f"Producto {pid}")[:46], s_txt),
                             Paragraph(f"{dd['piezas']:g}", s_num), Paragraph(money(dd["ventas"] if G else dd["costo"]), s_num),
                             Paragraph(money(val), s_numb), barra])
            story.append(KeepTogether(seccion(tit) + [tabla(data, [0.7 * cm, 7.3 * cm, 1.8 * cm, 2.4 * cm, 2.4 * cm, 3.6 * cm])]))
            story.append(Spacer(1, 0.55 * cm))

        # ── Detalle de ventas (solo en el reporte de ventas) ──
        if tipo == "ventas" and ventas:
            story += seccion(f"Detalle de ventas · {len(ventas)} tickets")
            data = [[th("Folio"), th("Fecha"), th("Cajero"), th("Pago"), th("Total", True)]]
            for v in ventas:
                data.append([Paragraph(str(v.folio or v.id), s_txt), Paragraph(v.creado_en.strftime("%d/%m/%Y %H:%M"), s_mut),
                             Paragraph((v.usuario.nombre or v.usuario.username) if v.usuario else "—", s_mut),
                             Paragraph(v.metodo_pago.value if v.metodo_pago else "—", s_mut), Paragraph(money(v.total or 0.0), s_numb)])
            data.append([Paragraph("<b>Total</b>", s_txt), "", "", "", Paragraph(money(tot["ventas"]), s_numb)])
            story += [tabla(data, [3 * cm, 3.6 * cm, 5.4 * cm, 3 * cm, 3.2 * cm], total=True), Spacer(1, 0.55 * cm)]

        notas = []
        if G:
            notas.append("Ganancia = ventas − costo de la mercancía vendida (el costo que tenía cada producto al venderse)"
                         + (" − devoluciones" if devoluciones else "") + (" − IVA" if tot["iva"] else "") + ".")
            if lineas_corregidas:
                notas.append(f"Se corrigió el costo de {lineas_corregidas} venta(s) por pieza que tenían guardado el costo de la caja completa.")
        if I:
            notas.append("Efectivo restante = ventas − inversión − gastos − retiros personales.")
        if V and devoluciones:
            notas.append(f"Devoluciones del periodo: {money(devoluciones)}.")
        if notas:
            nt = Table([[Paragraph("<br/>".join("• " + n for n in notas), s_mut)]], colWidths=[cw], hAlign="LEFT")
            nt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story.append(nt)
    finally:
        db.close()

    logo = cfg.BASE_DIR / "app" / "web" / "logo.png"
    BANDA = 3.0 * cm

    def _pie(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(1.5 * cm, 1.45 * cm, W - 1.5 * cm, 1.45 * cm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(1.5 * cm, 1.1 * cm, f"Generado el {now_str}")
        canvas.drawCentredString(W / 2, 1.1 * cm, f"{cfg.PHARMACY_NAME}  ·  {_PDF_TIPOS[tipo]}  ·  {per_label}")
        canvas.drawRightString(W - 1.5 * cm, 1.1 * cm, f"Página {doc.page}")
        canvas.restoreState()

    def _portada(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, H - BANDA, W, BANDA, stroke=0, fill=1)
        if logo.exists():
            try:
                canvas.drawImage(str(logo), 1.5 * cm, H - BANDA + 0.85 * cm, width=4.6 * cm, height=1.28 * cm,
                                 mask="auto", preserveAspectRatio=True, anchor="w")
            except Exception:
                pass
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawRightString(W - 1.5 * cm, H - 1.35 * cm, _PDF_TIPOS[tipo])
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#C7D2FE"))
        canvas.drawRightString(W - 1.5 * cm, H - 1.95 * cm, f"{per_label}  ·  por {nombre_per}")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(W - 1.5 * cm, H - 2.45 * cm, cfg.PHARMACY_NAME)
        canvas.restoreState()
        _pie(canvas, doc)

    buf = io.BytesIO()
    from reportlab.platypus import BaseDocTemplate
    doc = BaseDocTemplate(buf, pagesize=letter, title=f"{_PDF_TIPOS[tipo]} {per_label} — {cfg.PHARMACY_NAME}")
    # Primera página con la banda azul; las demás con margen normal.
    f1 = Frame(1.5 * cm, 2.0 * cm, cw, H - BANDA - 0.6 * cm - 2.0 * cm, id="f1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f2 = Frame(1.5 * cm, 2.0 * cm, cw, H - 1.5 * cm - 2.0 * cm, id="f2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="portada", frames=[f1], onPage=_portada, autoNextPageTemplate="resto"),
                          PageTemplate(id="resto", frames=[f2], onPage=_pie)])
    doc.build(story)
    return buf.getvalue()


@router.get("/finanzas-pdf")
def finanzas_pdf(
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    agrupar:      str = Query("semana"),
    tipo:         str = Query("completo"),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    data = _build_finanzas_pdf_bytes(fecha_inicio, fecha_fin, agrupar, tipo)
    filename = f"Reporte_{tipo}_{fecha_inicio}_{fecha_fin}.pdf"
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/save-finanzas-pdf")
def save_finanzas_pdf(
    body: _SavePdfBody,
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    agrupar:      str = Query("semana"),
    tipo:         str = Query("completo"),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    if not body.path:
        raise HTTPException(status_code=400, detail="path requerido")
    data = _build_finanzas_pdf_bytes(fecha_inicio, fecha_fin, agrupar, tipo)
    with open(body.path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": body.path}
