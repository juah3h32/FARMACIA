from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload
import io, csv, os, tempfile

from app.database.connection import get_db_session
from app.database.models import Venta, ItemVenta, Producto, EstadoVenta, CortesCaja, Lote, MovimientoStock, TipoMovimiento
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
        num   = len(ventas)

        por_dia: dict[str, float] = {}
        for v in ventas:
            d = v.creado_en.date().isoformat() if v.creado_en else "?"
            por_dia[d] = por_dia.get(d, 0.0) + v.total

        mejor_dia   = max(por_dia, key=por_dia.get) if por_dia else None
        mejor_monto = por_dia[mejor_dia] if mejor_dia else 0.0

        # Cost of goods sold for period
        venta_ids = [v.id for v in ventas]
        if venta_ids:
            cost_rows = (
                db.query(ItemVenta.cantidad, Producto.precio_compra)
                .join(Producto, ItemVenta.producto_id == Producto.id)
                .filter(ItemVenta.venta_id.in_(venta_ids))
                .all()
            )
            total_costo = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)
        else:
            total_costo = 0.0
        # Partial devoluciones in period (full returns excluded via estado=devolucion filter)
        dev_movs = db.query(MovimientoStock).filter(
            MovimientoStock.tipo == TipoMovimiento.devolucion,
            MovimientoStock.referencia_tipo == "devolucion",
            MovimientoStock.creado_en >= fi,
            MovimientoStock.creado_en <= ff,
        ).all()
        total_devoluciones = 0.0
        for mov in dev_movs:
            orig = db.query(ItemVenta).filter(
                ItemVenta.venta_id == mov.referencia_id,
                ItemVenta.producto_id == mov.producto_id,
            ).first()
            if orig:
                total_devoluciones += orig.precio_unitario * mov.cantidad
        ventas_netas = total - total_devoluciones
        ganancia = ventas_netas - total_costo

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
    fecha_inicio: date = Query(...),
    fecha_fin:    date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(fecha_inicio, fecha_fin)
        cortes = (
            db.query(CortesCaja)
            .filter(CortesCaja.abierto_en >= fi, CortesCaja.abierto_en <= ff)
            .order_by(CortesCaja.abierto_en.desc())
            .all()
        )
        result = []
        for c in cortes:
            dur_min = None
            if c.cerrado_en and c.abierto_en:
                dur_min = int((c.cerrado_en - c.abierto_en).total_seconds() / 60)
            ef  = c.total_efectivo or 0.0
            ape = c.monto_apertura or 0.0
            esperado = ape + ef
            dif = (c.monto_cierre - esperado) if c.monto_cierre is not None else None
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
            })
        return result
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
