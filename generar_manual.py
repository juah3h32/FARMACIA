"""Genera el Manual de Usuario en PDF — Farmacia Eben-Ezer POS.
Ejecutar: python generar_manual.py  -> crea Manual_FarmaciaPOS.pdf en la raíz del proyecto.
"""
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak,
    Table, TableStyle, ListFlowable, ListItem, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, Circle, Ellipse, Polygon, Line, String, Group
from reportlab.graphics import renderPDF

import app.config as cfg

W, H = letter

# ── Paleta (misma identidad visual que el resto de la app) ──────────────────
C_NAVY   = colors.HexColor("#1d2140")
C_NAVY2  = colors.HexColor("#2d3358")
C_DARK   = colors.HexColor("#0F172A")
C_MUTED  = colors.HexColor("#64748B")
C_LINE   = colors.HexColor("#E2E8F0")
C_LIGHT  = colors.HexColor("#F8FAFC")
C_WHITE  = colors.white
C_GREEN  = colors.HexColor("#16A34A")
C_AMBER  = colors.HexColor("#D97706")
C_RED    = colors.HexColor("#EF4444")

styles = getSampleStyleSheet()


def sty(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)


s_h1     = sty("_h1", fontSize=18, textColor=C_NAVY, fontName="Helvetica-Bold", leading=22, spaceAfter=10)
s_h2     = sty("_h2", fontSize=12.5, textColor=C_NAVY, fontName="Helvetica-Bold", leading=16, spaceBefore=14, spaceAfter=6)
s_h3     = sty("_h3", fontSize=10.5, textColor=C_NAVY2, fontName="Helvetica-Bold", leading=14, spaceBefore=8, spaceAfter=4)
s_body   = sty("_b", fontSize=9.5, textColor=C_DARK, fontName="Helvetica", leading=14, alignment=TA_JUSTIFY, spaceAfter=6)
s_bullet = sty("_bu", fontSize=9.3, textColor=C_DARK, fontName="Helvetica", leading=13.5, spaceAfter=3)
s_muted  = sty("_m", fontSize=8.3, textColor=C_MUTED, fontName="Helvetica", leading=12, spaceAfter=4)
s_cover_title = sty("_ct", fontSize=30, textColor=C_WHITE, fontName="Helvetica-Bold", leading=36, alignment=TA_CENTER)
s_cover_sub   = sty("_cs", fontSize=13, textColor=colors.HexColor("#B9BDD6"), fontName="Helvetica", leading=18, alignment=TA_CENTER)
s_toc    = sty("_toc", fontSize=10.5, textColor=C_DARK, fontName="Helvetica-Bold", leading=20)


def bullets(items, color_bullet=C_NAVY2):
    return ListFlowable(
        [ListItem(Paragraph(t, s_bullet), leftIndent=6, value="•", bulletColor=color_bullet) for t in items],
        bulletType="bullet", leftIndent=14, spaceBefore=2, spaceAfter=8,
    )


def badge_table(rows, col_widths=None):
    """Tabla simple estilo tarjeta — encabezado navy, filas alternadas."""
    t = Table(rows, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.5, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def section_bar(texto):
    """Barra de color con el título de sección — separador visual entre capítulos."""
    t = Table([[Paragraph(f'<font color="white"><b>{texto}</b></font>', sty("_sbar", fontSize=11, textColor=C_WHITE, fontName="Helvetica-Bold"))]],
               colWidths=[W - 4 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


def _cover_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_NAVY)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    # círculos decorativos sutiles
    canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.04))
    canvas.circle(W - 2 * cm, H - 3 * cm, 5 * cm, fill=1, stroke=0)
    canvas.circle(2 * cm, 4 * cm, 4 * cm, fill=1, stroke=0)
    canvas.restoreState()


def _inner_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_NAVY)
    canvas.rect(0, H - 1.3 * cm, W, 1.3 * cm, fill=1, stroke=0)
    canvas.setStrokeColor(C_GREEN)
    canvas.setLineWidth(1.5)
    canvas.line(0, H - 1.3 * cm, W, H - 1.3 * cm)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.setFillColor(C_WHITE)
    canvas.drawString(1.8 * cm, H - 0.82 * cm, "FARMACIA EBEN-EZER — Manual de Usuario del Sistema POS")
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#B9BDD6"))
    canvas.drawRightString(W - 1.8 * cm, H - 0.82 * cm, f"v{cfg.VERSION}")

    canvas.setStrokeColor(C_LINE)
    canvas.setLineWidth(0.6)
    canvas.line(1.8 * cm, 1.3 * cm, W - 1.8 * cm, 1.3 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(C_MUTED)
    canvas.drawString(1.8 * cm, 0.9 * cm, datetime.now().strftime("Generado %d/%m/%Y"))
    canvas.drawRightString(W - 1.8 * cm, 0.9 * cm, f"Página {doc.page}")
    canvas.restoreState()


# ══════════════════════════ ÍCONOS DEL DIAGRAMA ══════════════════════════════
import math


def icon_computer(g, cx, cy, s, color):
    g.add(Rect(cx - s * 0.55, cy - s * 0.05, s * 1.1, s * 0.7, rx=3, ry=3, fillColor=color, strokeColor=None))
    g.add(Rect(cx - s * 0.47, cy + s * 0.02, s * 0.94, s * 0.55, rx=2, ry=2, fillColor=colors.white, strokeColor=None))
    g.add(Rect(cx - s * 0.35, cy - s * 0.42, s * 0.7, s * 0.13, rx=2, ry=2, fillColor=color, strokeColor=None))


def icon_database(g, cx, cy, s, color):
    w, h = s * 0.95, s * 1.05
    g.add(Rect(cx - w / 2, cy - h / 2 + s * 0.12, w, h - s * 0.24, fillColor=color, strokeColor=None))
    g.add(Ellipse(cx, cy - h / 2 + s * 0.12, w / 2, s * 0.12, fillColor=color, strokeColor=None))
    g.add(Ellipse(cx, cy + h / 2 - s * 0.12, w / 2, s * 0.12, fillColor=color, strokeColor=None))
    g.add(Ellipse(cx, cy + h / 2 - s * 0.12, w / 2 * 0.88, s * 0.09, fillColor=colors.white, strokeColor=None, fillOpacity=0.35))


def icon_cloud(g, cx, cy, s, color):
    g.add(Circle(cx - s * 0.26, cy - s * 0.04, s * 0.30, fillColor=color, strokeColor=None))
    g.add(Circle(cx + s * 0.06, cy + s * 0.10, s * 0.36, fillColor=color, strokeColor=None))
    g.add(Circle(cx + s * 0.36, cy - s * 0.04, s * 0.26, fillColor=color, strokeColor=None))
    g.add(Rect(cx - s * 0.42, cy - s * 0.30, s * 0.90, s * 0.30, fillColor=color, strokeColor=None))


def icon_document_stamp(g, cx, cy, s, color):
    w, h = s * 0.72, s * 0.98
    g.add(Rect(cx - w / 2, cy - h / 2, w, h, rx=3, ry=3, fillColor=colors.white, strokeColor=color, strokeWidth=1.4))
    for frac in (0.72, 0.54, 0.36):
        yy = cy - h / 2 + h * frac
        g.add(Line(cx - w / 2 + w * 0.16, yy, cx + w / 2 - w * 0.16, yy, strokeColor=color, strokeWidth=0.9))
    g.add(Circle(cx + w * 0.22, cy - h * 0.30, s * 0.15, fillColor=None, strokeColor=C_GREEN, strokeWidth=1.3))


def icon_building(g, cx, cy, s, color):
    w, h = s * 0.95, s * 0.68
    g.add(Polygon([cx - w * 0.55, cy + h * 0.16, cx, cy + h * 0.55, cx + w * 0.55, cy + h * 0.16],
                  fillColor=color, strokeColor=None))
    g.add(Rect(cx - w / 2, cy - h / 2, w, h * 0.66, fillColor=color, strokeColor=None))
    for i in range(4):
        xx = cx - w * 0.36 + i * (w * 0.72 / 3)
        g.add(Rect(xx - s * 0.025, cy - h * 0.40, s * 0.05, h * 0.48, fillColor=colors.white, strokeColor=None))


def icon_message(g, cx, cy, s, color):
    w, h = s * 1.0, s * 0.72
    g.add(Rect(cx - w / 2, cy - h / 2 + s * 0.08, w, h, rx=h * 0.32, ry=h * 0.32, fillColor=color, strokeColor=None))
    g.add(Polygon([cx - w * 0.12, cy - h / 2 + s * 0.08, cx + w * 0.02, cy - h / 2 + s * 0.08,
                   cx - w * 0.10, cy - h / 2 - s * 0.08], fillColor=color, strokeColor=None))


def icon_email(g, cx, cy, s, color):
    w, h = s * 1.0, s * 0.7
    g.add(Rect(cx - w / 2, cy - h / 2, w, h, rx=2, ry=2, fillColor=colors.white, strokeColor=color, strokeWidth=1.4))
    g.add(Line(cx - w / 2, cy + h / 2, cx, cy - h * 0.05, strokeColor=color, strokeWidth=1.1))
    g.add(Line(cx + w / 2, cy + h / 2, cx, cy - h * 0.05, strokeColor=color, strokeWidth=1.1))


def icon_cart(g, cx, cy, s, color):
    w, h = s * 1.05, s * 0.65
    g.add(Line(cx - w / 2 - s * 0.12, cy + h * 0.55, cx - w / 2, cy + h * 0.55, strokeColor=color, strokeWidth=1.4))
    g.add(Polygon([cx - w / 2, cy + h * 0.55, cx + w / 2, cy + h * 0.55, cx + w * 0.42, cy - h * 0.15, cx - w * 0.42, cy - h * 0.15],
                  fillColor=None, strokeColor=color, strokeWidth=1.4))
    g.add(Circle(cx - w * 0.22, cy - h * 0.42, s * 0.08, fillColor=color, strokeColor=None))
    g.add(Circle(cx + w * 0.22, cy - h * 0.42, s * 0.08, fillColor=color, strokeColor=None))


def icon_box(g, cx, cy, s, color):
    w, h = s * 0.95, s * 0.85
    g.add(Rect(cx - w / 2, cy - h / 2, w, h, fillColor=color, strokeColor=None))
    g.add(Line(cx - w / 2, cy + h * 0.15, cx + w / 2, cy + h * 0.15, strokeColor=colors.white, strokeWidth=1.2))
    g.add(Line(cx, cy + h * 0.15, cx, cy - h / 2, strokeColor=colors.white, strokeWidth=1.2))
    g.add(Line(cx - w / 2, cy + h * 0.15, cx, cy + h / 2, strokeColor=colors.white, strokeWidth=1.2))
    g.add(Line(cx + w / 2, cy + h * 0.15, cx, cy + h / 2, strokeColor=colors.white, strokeWidth=1.2))


def icon_cash(g, cx, cy, s, color):
    w, h = s * 1.05, s * 0.68
    g.add(Rect(cx - w / 2, cy - h / 2, w, h, rx=2, ry=2, fillColor=color, strokeColor=None))
    g.add(Circle(cx, cy, h * 0.28, fillColor=colors.white, strokeColor=None))
    g.add(String(cx, cy - s * 0.06, "$", fontName="Helvetica-Bold", fontSize=s * 0.28, fillColor=color, textAnchor="middle"))


def icon_printer(g, cx, cy, s, color):
    w, h = s * 0.95, s * 0.55
    g.add(Rect(cx - w / 2, cy - h * 0.1, w, h, fillColor=color, strokeColor=None))
    g.add(Rect(cx - w * 0.32, cy + h * 0.45, w * 0.64, h * 0.4, fillColor=color, strokeColor=None))
    g.add(Rect(cx - w * 0.28, cy - h * 0.55, w * 0.56, h * 0.55, fillColor=colors.white, strokeColor=color, strokeWidth=1.1))


def icon_truck(g, cx, cy, s, color):
    w, h = s * 1.1, s * 0.5
    g.add(Rect(cx - w / 2, cy - h * 0.1, w * 0.62, h, fillColor=color, strokeColor=None))
    g.add(Polygon([cx + w * 0.12, cy - h * 0.1, cx + w * 0.4, cy - h * 0.1, cx + w / 2, cy + h * 0.35, cx + w * 0.12, cy + h * 0.35],
                  fillColor=color, strokeColor=None))
    g.add(Circle(cx - w * 0.22, cy - h * 0.32, s * 0.1, fillColor=C_DARK, strokeColor=None))
    g.add(Circle(cx + w * 0.28, cy - h * 0.32, s * 0.1, fillColor=C_DARK, strokeColor=None))


def icon_check(g, cx, cy, s, color):
    g.add(Circle(cx, cy, s * 0.45, fillColor=color, strokeColor=None))
    g.add(Line(cx - s * 0.2, cy, cx - s * 0.05, cy - s * 0.15, strokeColor=colors.white, strokeWidth=2))
    g.add(Line(cx - s * 0.05, cy - s * 0.15, cx + s * 0.22, cy + s * 0.18, strokeColor=colors.white, strokeWidth=2))


def diagram_box(g, x, y, w, h, icon_fn, color, label, sublabel=None):
    g.add(Rect(x, y, w, h, rx=8, ry=8, fillColor=colors.white, strokeColor=color, strokeWidth=1.6))
    icon_fn(g, x + w / 2, y + h * 0.60, min(w, h) * 0.42, color)
    g.add(String(x + w / 2, y + h * 0.20, label, fontName="Helvetica-Bold", fontSize=8.2,
                 fillColor=C_DARK, textAnchor="middle"))
    if sublabel:
        g.add(String(x + w / 2, y + h * 0.07, sublabel, fontName="Helvetica", fontSize=6.2,
                      fillColor=C_MUTED, textAnchor="middle"))


def arrow(g, x1, y1, x2, y2, color=C_MUTED, label=None, double=False, label_dx=0):
    g.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.2))
    ang = math.atan2(y2 - y1, x2 - x1)
    ah = 5.5

    def head(px, py, a):
        p2 = (px - ah * math.cos(a - math.pi / 6), py - ah * math.sin(a - math.pi / 6))
        p3 = (px - ah * math.cos(a + math.pi / 6), py - ah * math.sin(a + math.pi / 6))
        g.add(Polygon([px, py, p2[0], p2[1], p3[0], p3[1]], fillColor=color, strokeColor=None))

    head(x2, y2, ang)
    if double:
        head(x1, y1, ang + math.pi)
    if label:
        mx, my = (x1 + x2) / 2 + label_dx, (y1 + y2) / 2 + 5
        g.add(String(mx, my, label, fontName="Helvetica-Oblique", fontSize=6.6,
                      fillColor=color, textAnchor="middle"))


def build_arch_diagram():
    dw = W - 3.6 * cm
    dh = 11.6 * cm
    d = Drawing(dw, dh)

    bw, bh = 4.3 * cm, 2.3 * cm
    y1 = dh - bh - 0.2 * cm          # fila superior
    y2 = y1 - bh - 2.0 * cm          # fila media
    y3 = y2 - bh - 2.0 * cm          # fila inferior

    x_pos   = 0.4 * cm
    x_turso = dw - bw - 0.4 * cm
    x_fact  = (dw - bw) / 2
    x_sat   = x_turso
    x_wa    = x_fact - bw * 0.92
    x_co    = x_fact + bw * 0.92

    C_POS   = C_NAVY2
    C_TURSO = colors.HexColor("#0EA5E9")
    C_FACT  = C_GREEN
    C_SAT   = C_AMBER
    C_WA    = colors.HexColor("#25D366")
    C_CO    = colors.HexColor("#3B82F6")

    # Cajas
    diagram_box(d, x_pos, y1, bw, bh, icon_computer, C_POS, "POS Local", "Esta computadora (SQLite)")
    diagram_box(d, x_turso, y1, bw, bh, icon_cloud, C_TURSO, "Turso (nube)", "Respaldo y multi-PC")
    diagram_box(d, x_fact, y2, bw, bh, icon_document_stamp, C_FACT, "Factura.com", "Timbra el CFDI")
    diagram_box(d, x_sat, y2, bw, bh, icon_building, C_SAT, "SAT", "Autoridad fiscal")
    diagram_box(d, x_wa, y3, bw * 0.85, bh * 0.85, icon_message, C_WA, "WhatsApp", "Envía al cliente")
    diagram_box(d, x_co, y3, bw * 0.85, bh * 0.85, icon_email, C_CO, "Correo", "Envía al cliente")

    # Flechas
    arrow(d, x_pos + bw, y1 + bh * 0.5, x_turso, y1 + bh * 0.5, color=C_MUTED, label="Sincroniza automático", double=True)
    arrow(d, x_pos + bw * 0.5, y1, x_fact + bw * 0.5, y2 + bh, color=C_MUTED, label="Datos de la venta", label_dx=-1.7 * cm)
    arrow(d, x_fact + bw, y2 + bh * 0.5, x_sat, y2 + bh * 0.5, color=C_AMBER, label="Timbra CFDI")
    arrow(d, x_fact + bw * 0.25, y2, x_wa + bw * 0.42, y3 + bh * 0.85, color=C_MUTED, label="PDF / XML", label_dx=-0.6 * cm)
    arrow(d, x_fact + bw * 0.75, y2, x_co + bw * 0.42, y3 + bh * 0.85, color=C_MUTED, label="PDF / XML", label_dx=0.6 * cm)

    return d


def build_flow_diagram(steps, height=4.6 * cm):
    """steps: lista de (icon_fn, color, label, sublabel) — dibuja una fila
    izquierda→derecha con flechas entre cada paso, tamaño automático al ancho de página."""
    dw = W - 3.6 * cm
    dh = height
    d = Drawing(dw, dh)

    n = len(steps)
    gap = 0.9 * cm
    bw = (dw - gap * (n - 1)) / n
    bh = dh - 0.3 * cm
    y = 0.15 * cm

    xs = []
    for i, (icon_fn, color, label, sublabel) in enumerate(steps):
        x = i * (bw + gap)
        xs.append(x)
        diagram_box(d, x, y, bw, bh, icon_fn, color, label, sublabel)

    for i in range(n - 1):
        x1 = xs[i] + bw
        x2 = xs[i + 1]
        yy = y + bh * 0.55
        arrow(d, x1, yy, x2, yy, color=C_MUTED)

    return d


story = []

# ══════════════════════════════ PORTADA ══════════════════════════════════════
story.append(Spacer(1, 6.5 * cm))
story.append(Paragraph("FARMACIA EBEN-EZER", s_cover_title))
story.append(Spacer(1, 6))
story.append(Paragraph("Manual de Usuario — Sistema POS", s_cover_sub))
story.append(Spacer(1, 4))
story.append(Paragraph(f"Versión {cfg.VERSION} &nbsp;·&nbsp; {datetime.now().strftime('%B %Y').capitalize()}", s_cover_sub))
story.append(PageBreak())

# ══════════════════════════════ CONTENIDO ═════════════════════════════════════
story.append(Paragraph("Contenido", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=C_LINE, spaceAfter=10))
contenido = [
    "Arquitectura: cómo se conectan tus datos",
    "1. Primer arranque y sincronización con la nube",
    "2. Ventas (Punto de Venta)",
    "3. Facturación electrónica CFDI",
    "4. Envío de facturas por WhatsApp y correo",
    "5. Inventario y compras",
    "6. Clientes y crédito",
    "7. Citas y promociones",
    "8. Cortes de caja",
    "9. Reportes y declaración mensual RESICO",
    "10. Administración del sistema",
]
for item in contenido:
    story.append(Paragraph(item, s_toc))
story.append(PageBreak())

# ══════════════════════════ ARQUITECTURA (DIAGRAMA) ══════════════════════════
story.append(Paragraph("Arquitectura: cómo se conectan tus datos", s_h1))
story.append(Paragraph(
    "Este diagrama resume por dónde viaja la información cuando timbras una factura: tu computadora "
    "(base de datos local), la nube de respaldo (Turso), el proveedor autorizado que timbra ante el SAT "
    "(Factura.com), y la entrega final al cliente.", s_body))
story.append(Spacer(1, 6))
story.append(build_arch_diagram())
story.append(Spacer(1, 10))
story.append(bullets([
    "<b>POS Local ↔ Turso</b>: cada venta, corte de caja o cambio se sincroniza automáticamente hacia la nube — sirve como respaldo y para usar el sistema en más de una computadora.",
    "<b>POS Local → Factura.com</b>: al timbrar, el sistema manda los datos de la venta (o del cliente, si es factura individual) al proveedor autorizado.",
    "<b>Factura.com → SAT</b>: Factura.com sella el comprobante ante el SAT y regresa el folio fiscal (UUID) — ese paso es lo que hace válida la factura.",
    "<b>Factura.com → WhatsApp / Correo</b>: una vez timbrada, el PDF y el XML se pueden enviar directo al cliente desde el mismo sistema.",
]))
story.append(PageBreak())

# ══════════════════════════ 1. PRIMER ARRANQUE ═══════════════════════════════
story.append(section_bar("1.  PRIMER ARRANQUE Y SINCRONIZACIÓN CON LA NUBE"))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "La primera vez que se instala el sistema en una computadora nueva, aparece una ventana de "
    "configuración inicial antes de abrir el programa. Esto solo se pregunta una vez.", s_body))
story.append(Paragraph("Modos disponibles", s_h3))
story.append(bullets([
    "<b>Nube (Turso)</b> — Respaldo automático y sincroniza datos entre varias computadoras. Recomendado si hay internet estable.",
    "<b>Solo este equipo (Local)</b> — Todo se queda en la computadora, sin nube. Ideal para una sola caja.",
    "<b>Sin conexión (Offline)</b> — Empieza sin internet; se puede activar la nube después desde Configuración.",
]))
story.append(Paragraph(
    "Al elegir un modo, el sistema muestra una barra de progreso real mientras configura la base de datos "
    "y, si se eligió Nube, sincroniza los datos existentes. En arranques posteriores esta pantalla ya no aparece.",
    s_body))
story.append(PageBreak())

# ══════════════════════════════ 2. VENTAS ═════════════════════════════════════
story.append(section_bar("2.  VENTAS (PUNTO DE VENTA)"))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "Módulo principal para registrar ventas del día. Permite buscar productos por nombre o código de barras, "
    "aplicar descuentos, y cobrar en efectivo, tarjeta, transferencia o pago mixto.", s_body))
story.append(Spacer(1, 4))
story.append(build_flow_diagram([
    (icon_cart, C_NAVY2, "Agregar productos", "Buscar por nombre o código"),
    (icon_cash, C_GREEN, "Cobrar", "Efectivo, tarjeta, mixto"),
    (icon_printer, C_AMBER, "Ticket", "Impresión automática"),
    (icon_document_stamp, colors.HexColor("#0EA5E9"), "Factura (opcional)", "Simplificada o CFDI"),
]))
story.append(Spacer(1, 10))
story.append(Paragraph("Funciones clave", s_h3))
story.append(bullets([
    "Venta fraccionada: productos que se venden por caja completa o por pieza suelta (el sistema calcula automáticamente cuántas cajas debe abrir).",
    "Aviso cuando un producto requiere receta médica.",
    "Bloqueo de venta si todos los lotes disponibles de un producto están vencidos.",
    "Impresión automática de ticket, con reintento en segundo plano si la impresora no responde al momento.",
    "Acumulación de puntos de lealtad si la venta se liga a un cliente registrado.",
    "Terminal Mercado Pago Point integrada para cobro con tarjeta física.",
]))
story.append(Paragraph("Facturación Simplificada", s_h3))
story.append(Paragraph(
    "Genera un recibo en PDF con los datos del cliente (nombre, RFC, dirección) para ventas donde el cliente "
    "pide un comprobante pero no requiere una factura fiscal real (CFDI). El folio de venta se elige de una "
    "lista desplegable con las ventas recientes — ya no hay que escribirlo a mano.", s_body))
story.append(PageBreak())

# ══════════════════════════ 3. FACTURACIÓN CFDI ══════════════════════════════
story.append(section_bar("3.  FACTURACIÓN ELECTRÓNICA CFDI  (NUEVO)"))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "El sistema timbra comprobantes fiscales digitales (CFDI 4.0) reales ante el SAT, a través del "
    "proveedor autorizado Factura.com. Hay dos formas de facturar:", s_body))

story.append(Paragraph("3.1  Factura Global Mensual (RESICO)", s_h2))
story.append(Paragraph(
    "Concentra todas las ventas del mes en un solo CFDI a nombre de \"Público en General\" (RFC genérico "
    "XAXX010101000), tal como lo exige el régimen RESICO. Debe timbrarse dentro de las 24 horas siguientes "
    "al cierre del mes (Regla 2.7.1.21 RMF) — el sistema avisa en rojo si ya se pasó ese plazo.", s_body))
story.append(bullets([
    "Vista previa del documento antes de timbrar (revisa los datos, es fiscalmente irreversible una vez emitido).",
    "Resumen de Declaración Mensual: calcula IVA a pagar e ISR estimado según la tabla RESICO vigente, con fecha límite de pago (día 17 del mes siguiente) en semáforo de color.",
    "Historial con estado (Timbrada / Cancelada / Error), UUID fiscal, y botón para eliminar solo los intentos fallidos.",
    "Verificación directa contra el validador oficial del SAT desde el mismo sistema.",
]))

story.append(Paragraph("3.2  Facturación Individual por Venta", s_h2))
story.append(Paragraph(
    "Cuando un cliente específico pide su propia factura (no la global), se timbra un CFDI de ingreso real "
    "a su nombre, con sus propios datos fiscales.", s_body))
story.append(Paragraph("Datos que se capturan del cliente", s_h3))
story.append(badge_table([
    ["Campo", "Ejemplo"],
    ["Nombre o razón social", "JUAN PABLO CORONA CORONA"],
    ["RFC", "COCJ990206JQ0"],
    ["Régimen fiscal", "612 — Personas Físicas con Act. Empresariales"],
    ["Código postal", "58116"],
    ["Uso de CFDI", "G03 — Gastos en general"],
    ["Forma de pago", "01 — Efectivo"],
], col_widths=[5.5 * cm, 8.5 * cm]))
story.append(Spacer(1, 6))
story.append(Paragraph(
    "Regla importante: una venta solo puede facturarse individual hasta el último día del mes en que se "
    "hizo la compra. Después de esa fecha, ya queda cubierta por la factura global mensual y el sistema "
    "bloquea el intento para evitar declarar el mismo ingreso dos veces. Tampoco se puede facturar dos "
    "veces la misma venta.", s_body))
story.append(Paragraph(
    "Todas las facturas (global e individual) se guardan organizadas automáticamente en carpetas por mes "
    "dentro de la carpeta de datos del programa, listas para respaldo o para el contador.", s_body))
story.append(PageBreak())

# ══════════════════════════ 4. ENVÍO WHATSAPP/CORREO ═════════════════════════
story.append(section_bar("4.  ENVÍO DE FACTURAS POR WHATSAPP Y CORREO  (NUEVO)"))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "Desde el detalle de cualquier factura individual ya timbrada, se puede enviar el comprobante directo "
    "al cliente sin salir del sistema.", s_body))
story.append(Paragraph("Por WhatsApp", s_h3))
story.append(Paragraph(
    "Envía un mensaje de texto con el link de descarga del PDF (respaldado automáticamente en la nube al "
    "timbrar). Usa la misma configuración de WhatsApp ya usada para alertas del sistema.", s_body))
story.append(Paragraph("Por correo electrónico", s_h3))
story.append(Paragraph(
    "Adjunta el PDF y el XML directamente al correo del cliente. Requiere configurar una cuenta de correo "
    "SMTP una sola vez (Configuración → Envío por correo): servidor, puerto, usuario y contraseña de "
    "aplicación (para Gmail: smtp.gmail.com, puerto 587, con contraseña de aplicación generada en la "
    "seguridad de la cuenta de Google, no la contraseña normal).", s_body))
story.append(PageBreak())

# ══════════════════════════ 5. INVENTARIO Y COMPRAS ══════════════════════════
story.append(section_bar("5.  INVENTARIO Y COMPRAS"))
story.append(Spacer(1, 10))
story.append(Paragraph("Control de productos, existencias, proveedores y órdenes de compra.", s_body))
story.append(Spacer(1, 4))
story.append(build_flow_diagram([
    (icon_truck, C_AMBER, "Orden de compra", "Se manda al proveedor"),
    (icon_box, C_NAVY2, "Recepción", "Se marca \"recibida\""),
    (icon_check, C_GREEN, "Stock actualizado", "Automático, sin captura extra"),
]))
story.append(Spacer(1, 10))
story.append(bullets([
    "Alta de productos con código de barras, presentación, lote y fecha de caducidad.",
    "Venta fraccionada configurable por producto (pieza suelta / caja completa).",
    "Órdenes de compra a proveedores: al marcar una orden como \"recibida\", el sistema suma el stock automáticamente y registra el movimiento — ya no hay que capturarlo aparte.",
    "Inventario cíclico (conteos físicos) con conciliación contra el stock del sistema y auditoría de ajustes.",
    "Facturas de compra de proveedores con su propio historial y archivos.",
    "Reordenamiento sugerido según stock mínimo configurado por producto.",
]))
story.append(PageBreak())

# ══════════════════════════ 6. CLIENTES Y CRÉDITO ════════════════════════════
story.append(section_bar("6.  CLIENTES Y CRÉDITO"))
story.append(Spacer(1, 10))
story.append(bullets([
    "Registro de clientes con nombre, teléfono, correo, RFC y dirección.",
    "Puntos de lealtad acumulados automáticamente en cada venta ligada a un cliente.",
    "Ventas a crédito con límite configurable por cliente y saldo de deuda.",
    "Registro de pagos/abonos — el sistema no permite registrar un pago mayor a la deuda actual, para no perder de vista ningún excedente.",
]))
story.append(PageBreak())

# ══════════════════════════ 7. CITAS Y PROMOCIONES ═══════════════════════════
story.append(section_bar("7.  CITAS Y PROMOCIONES"))
story.append(Spacer(1, 10))
story.append(Paragraph("Agenda", s_h3))
story.append(Paragraph(
    "Programa citas de pacientes con fecha, hora y tipo de servicio. El sistema evita agendar dos citas "
    "encimadas para el mismo encargado dentro de la misma media hora.", s_body))
story.append(Paragraph("Promociones", s_h3))
story.append(Paragraph(
    "Descuentos configurables con vigencia por fechas, aplicables en el punto de venta.", s_body))
story.append(PageBreak())

# ══════════════════════════ 8. CORTES DE CAJA ════════════════════════════════
story.append(section_bar("8.  CORTES DE CAJA"))
story.append(Spacer(1, 10))
story.append(Paragraph(
    "Cada cajero abre un turno con un monto de apertura y lo cierra al final del día, capturando el efectivo "
    "físico contado.", s_body))
story.append(Spacer(1, 4))
story.append(build_flow_diagram([
    (icon_cash, C_NAVY2, "Apertura", "Monto inicial de caja"),
    (icon_cart, C_GREEN, "Ventas del turno", "Efectivo, tarjeta, mixto"),
    (icon_check, C_AMBER, "Cierre", "Efectivo contado vs. esperado"),
    (icon_document_stamp, colors.HexColor("#0EA5E9"), "Corte guardado", "Historial con diferencia"),
]))
story.append(Spacer(1, 10))
story.append(bullets([
    "Desglose por forma de pago: efectivo, tarjeta, transferencia y pagos mixtos.",
    "Cálculo automático de costo de mercancía vendida y ganancia del turno.",
    "Retiros de efectivo durante el turno (personal o inversión), con motivo registrado.",
    "Cierre automático de turnos abiertos de días anteriores para no mezclar ventas entre días.",
    "Historial de turnos anteriores con diferencia entre lo esperado y lo contado.",
]))
story.append(PageBreak())

# ══════════════════════════ 9. REPORTES ══════════════════════════════════════
story.append(section_bar("9.  REPORTES Y DECLARACIÓN MENSUAL RESICO"))
story.append(Spacer(1, 10))
story.append(bullets([
    "Dashboard con ventas del día, productos más vendidos y alertas de stock bajo.",
    "Reporte de rentabilidad por producto y periodo.",
    "Exportación de reportes a PDF y Excel.",
    "Resumen de Declaración Mensual: junta ingresos, compras, IVA a pagar e ISR estimado en un solo lugar para presentar ante el SAT — el importe final siempre debe confirmarse en el Buzón Tributario o con el contador.",
]))
story.append(PageBreak())

# ══════════════════════════ 10. ADMINISTRACIÓN ═══════════════════════════════
story.append(section_bar("10.  ADMINISTRACIÓN DEL SISTEMA"))
story.append(Spacer(1, 10))
story.append(bullets([
    "Gestión de empleados y permisos (cajero / administrador).",
    "Respaldo y restauración de la base de datos, con respaldo diario automático.",
    "Actualizaciones del sistema: se descargan desde el repositorio oficial y se verifican contra un "
    "checksum antes de instalar, para evitar instalar un archivo dañado o modificado.",
    "Diagnóstico de sincronización con la nube (Turso) para revisar el estado de los datos entre computadoras.",
    "Historial de auditoría de acciones sensibles del sistema.",
]))
story.append(Spacer(1, 14))
story.append(HRFlowable(width="100%", thickness=0.8, color=C_LINE))
story.append(Spacer(1, 8))
story.append(Paragraph(
    "Este manual se generó automáticamente a partir de las funciones activas del sistema. "
    "Para dudas específicas de un módulo, consulta con el administrador del sistema.", s_muted))

# ══════════════════════════════ BUILD ═════════════════════════════════════════
doc = SimpleDocTemplate(
    "Manual_FarmaciaPOS.pdf", pagesize=letter,
    leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=2.1 * cm, bottomMargin=1.8 * cm,
)


def _on_page(canvas, doc_):
    if doc_.page == 1:
        _cover_page(canvas, doc_)
    else:
        _inner_page(canvas, doc_)


doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
print("Manual generado: Manual_FarmaciaPOS.pdf")
