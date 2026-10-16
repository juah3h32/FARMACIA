"""Correos de recuperación de contraseña: diseño con la portada y el logo de la farmacia.

Se envían con el correo propio de la farmacia si lo configuró (SMTP en Configuración) y, si no,
por el servicio de envío del sistema (relay en la web del POS), así una farmacia nueva solo tiene
que escribir su correo y la recuperación funciona sin configurar nada más.
"""
import hashlib
import html
import io
import re
import sys
from pathlib import Path

import app.config as cfg

AZUL = "#1d2140"
AZUL_2 = "#243366"
AZUL_CLARO = "#3373B9"

# Servicio de envío del sistema (ver relay_routes.py): no recibe HTML, solo los datos del correo
# (tipo, código, nombres); el servidor arma el correo con estas mismas plantillas y limita envíos.
RELAY_URL = "https://farmacia-ebenezer.com/api/relay/correo-recuperacion"
_ASSETS = Path(getattr(sys, "_MEIPASS", cfg.BASE_DIR)) / "assets"


# ── portada (encabezado del correo) ──────────────────────────────────────────
def _logo_path() -> Path | None:
    """Logo de la farmacia: el que haya puesto en DATA_DIR (otra farmacia) o el del programa."""
    for p in (cfg.DATA_DIR / "logo_farmacia.png", _ASSETS / "logos" / "LOGO.png"):
        if p.is_file():
            return p
    return None


def portada_png(nombre: str, logo: Path | None | bool = True) -> bytes:
    """Banner del encabezado (1360x300): azul de la farmacia, de lado a lado, con el logo en una
    tarjeta blanca. logo=False: solo el nombre (en el servidor de envío, sin el logo de esa farmacia)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    logo = _logo_path() if logo is True else (logo or None)
    clave = hashlib.md5(f"{nombre}|{logo}|{logo.stat().st_mtime if logo else 0}|v3".encode()).hexdigest()[:12]
    cache = cfg.DATA_DIR / "correo" / f"portada_{clave}.png"
    if cache.is_file():
        return cache.read_bytes()

    W, H = 1360, 300
    # fondo del mismo azul liso que la banda del correo (sin corte en los bordes de la imagen);
    # el brillo y los adornos se desvanecen hacia los lados
    img = Image.new("RGBA", (W, H), (29, 33, 64, 255))
    brillo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(brillo).ellipse((W * 0.18, -H * 0.6, W * 0.82, H * 1.5), fill=(51, 82, 150, 120))
    img = Image.alpha_composite(img, brillo.filter(ImageFilter.GaussianBlur(70)))
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    for (cx, cy, r) in ((60, 300, 260), (1300, -20, 230), (1180, 300, 120), (240, -60, 140)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(80, 140, 210, 70), width=2)
        d.ellipse((cx - r + 36, cy - r + 36, cx + r - 36, cy + r - 36), fill=(51, 115, 185, 22))
    for i in range(0, W, 34):                                   # trama de puntos suave
        for j in range(18, H, 34):
            if (i // 34 + j // 34) % 3 == 0:
                d.ellipse((i, j, i + 3, j + 3), fill=(255, 255, 255, 14))
    lados = Image.linear_gradient("L").rotate(90).resize((W // 2, H))         # 0 en el borde → 255 al centro
    mascara = Image.new("L", (W, H), 0)
    mascara.paste(lados.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    mascara.paste(lados, (W // 2, 0))
    deco.putalpha(Image.composite(deco.getchannel("A"), Image.new("L", (W, H), 0), mascara))
    img = Image.alpha_composite(img, deco)

    card_w, card_h = 640, 196
    x0, y0 = (W - card_w) // 2, (H - card_h) // 2
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle((x0, y0 + 12, x0 + card_w, y0 + card_h + 12), 30, fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(16)))
    ImageDraw.Draw(img).rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), 30, fill=(255, 255, 255, 255))
    if logo:
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((card_w - 90, card_h - 50), Image.LANCZOS)
        img.alpha_composite(lg, ((W - lg.width) // 2, y0 + (card_h - lg.height) // 2))
    else:
        try:
            f = ImageFont.truetype(str(_ASSETS / "fonts" / "Montserrat-Bold.ttf"), 54)
        except Exception:
            f = ImageFont.load_default()
        dd = ImageDraw.Draw(img)
        tw = dd.textlength(nombre, font=f)
        dd.text(((W - tw) / 2, y0 + card_h / 2 - 34), nombre, font=f, fill=AZUL)
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    data = out.getvalue()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        for viejo in cache.parent.glob("portada_*.png"):
            viejo.unlink(missing_ok=True)
        cache.write_bytes(data)
    except Exception:
        pass
    return data


# ── plantillas ───────────────────────────────────────────────────────────────
_FUENTE = "'Segoe UI',Roboto,'Helvetica Neue',Helvetica,Arial,sans-serif"


def _marco(farmacia: str, preencabezado: str, cuerpo: str, pie: str, contacto: dict) -> str:
    """Diseño de ancho completo: banda azul con el logo, contenido de 680 px y pie gris de lado a lado."""
    f = html.escape(farmacia)
    datos = " &middot; ".join(html.escape(v) for v in (contacto.get("direccion", ""), contacto.get("telefono", "")) if v)
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="x-apple-disable-message-reformatting">
<title>{f}</title></head>
<body style="margin:0;padding:0;background:#ffffff;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#ffffff">{html.escape(preencabezado)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff">
  <tr><td align="center" bgcolor="{AZUL}" style="background:{AZUL};padding:0;line-height:0">
    <img src="cid:portada" width="680" alt="{f}" style="display:block;width:100%;max-width:680px;height:auto;border:0">
  </td></tr>
  <tr><td align="center" style="padding:0 20px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px">
      <tr><td style="padding:40px 4px 12px;font-family:{_FUENTE};color:#0F172A">
{cuerpo}
      </td></tr>
    </table>
  </td></tr>
  <tr><td align="center" bgcolor="#F1F5F9" style="background:#F1F5F9;padding:28px 20px 34px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px"><tr>
      <td style="font-family:{_FUENTE};font-size:12px;line-height:19px;color:#64748B">
        <b style="color:{AZUL};font-size:13px">{f}</b><br>{datos + "<br>" if datos else ""}
        {pie} Este es un mensaje automático del punto de venta; no respondas a este correo.
      </td></tr></table>
  </td></tr>
</table></body></html>"""


def _paso(n: int, titulo: str, texto: str) -> str:
    return (f'<tr><td width="44" valign="top" style="padding:0 0 18px"><div style="width:30px;height:30px;border-radius:15px;'
            f'background:{AZUL};color:#fff;font-size:13px;font-weight:700;line-height:30px;text-align:center">{n}</div></td>'
            f'<td valign="top" style="padding:3px 0 18px;font-size:14px;line-height:21px;color:#475569">'
            f'<b style="color:#0F172A;font-size:15px">{titulo}</b><br>{texto}</td></tr>')


def _dato(etiqueta: str, valor: str) -> str:
    return (f'<td valign="top" style="padding:16px 18px;border-right:1px solid #E2E8F0">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#94A3B8">{etiqueta}</div>'
            f'<div style="font-size:15px;font-weight:700;color:#0F172A;margin-top:4px">{valor}</div></td>')


def _ahora_texto() -> str:
    from datetime import datetime
    meses = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    n = datetime.now()
    return f"{n.day} {meses[n.month - 1]} {n:%Y}, {n:%H:%M}"


def html_codigo(farmacia: str, nombre: str, usuario: str, codigo: str, minutos: int = 15,
                contacto: dict | None = None) -> tuple[str, str]:
    contacto = contacto or {}
    digitos = "".join(
        f'<td style="padding:0 5px"><div style="width:56px;height:68px;border-radius:14px;background:#ffffff;'
        f'border:1px solid #CBD5E1;font-size:36px;font-weight:800;line-height:68px;text-align:center;color:{AZUL};'
        f'font-family:Consolas,Menlo,monospace">{d}</div></td>' for d in codigo)
    ayuda = (f' o llama a la farmacia al <b style="color:#0F172A">{html.escape(contacto["telefono"])}</b>'
             if contacto.get("telefono") else "")
    cuerpo = f"""        <p style="margin:0 0 8px;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:{AZUL_CLARO}">Seguridad de la cuenta</p>
        <h1 style="margin:0 0 14px;font-size:30px;line-height:38px;font-weight:800;color:{AZUL}">Restablece tu contraseña</h1>
        <p style="margin:0 0 28px;font-size:16px;line-height:25px;color:#334155">Hola <b>{html.escape(nombre)}</b>, recibimos una solicitud para restablecer la contraseña de tu cuenta en el punto de venta de <b>{html.escape(farmacia)}</b>. Usa este código para continuar:</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5FF;border-radius:18px">
          <tr><td align="center" style="padding:30px 16px 10px">
            <div style="font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#64748B;margin-bottom:14px">Tu código de verificación</div>
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>{digitos}</tr></table>
          </td></tr>
          <tr><td align="center" style="padding:12px 16px 26px;font-size:13px;color:#475569">Vence en <b>{minutos} minutos</b> &middot; Sirve una sola vez</td></tr>
        </table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:22px 0 34px;border:1px solid #E2E8F0;border-radius:14px;border-collapse:separate">
          <tr>{_dato("Usuario", html.escape(usuario))}{_dato("Solicitado", _ahora_texto())}<td valign="top" style="padding:16px 18px">
            <div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#94A3B8">Vence</div>
            <div style="font-size:15px;font-weight:700;color:#0F172A;margin-top:4px">en {minutos} min</div></td></tr>
        </table>
        <h2 style="margin:0 0 18px;font-size:18px;font-weight:800;color:{AZUL}">Cómo usar tu código</h2>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {_paso(1, "Vuelve al punto de venta", 'En la ventana de <b>¿Olvidaste tu contraseña?</b> donde pediste el código.')}
          {_paso(2, "Escribe el código y tu contraseña nueva", "La contraseña debe tener al menos 8 caracteres; escríbela dos veces.")}
          {_paso(3, "Entra con tu contraseña nueva", "Por seguridad, las sesiones abiertas en otras computadoras se cierran solas.")}
        </table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0 6px">
          <tr><td style="background:#FFF7ED;border-left:4px solid #F97316;border-radius:10px;padding:16px 18px;font-size:14px;line-height:21px;color:#7C2D12">
            <b>¿No fuiste tú?</b> Ignora este correo: tu contraseña no cambia. Nunca compartas este código; nadie de la farmacia te lo pedirá.
          </td></tr>
        </table>
        <p style="margin:22px 0 0;font-size:13px;line-height:20px;color:#64748B">¿Problemas con el código? Pide uno nuevo desde la misma pantalla{ayuda}.</p>"""
    texto = (f"Hola {nombre}:\n\nRecibimos una solicitud para restablecer la contraseña de tu cuenta ({usuario}) en el "
             f"punto de venta de {farmacia}.\n\nTu código: {codigo}\nVence en {minutos} minutos y sirve una sola vez.\n\n"
             "Cómo usarlo:\n1. Vuelve a la ventana de \"¿Olvidaste tu contraseña?\".\n"
             "2. Escribe el código y tu contraseña nueva (mínimo 8 caracteres) dos veces.\n"
             "3. Entra con tu contraseña nueva.\n\n¿No fuiste tú? Ignora este correo: tu contraseña no cambia.\n")
    return _marco(farmacia, f"Tu código es {codigo}. Vence en {minutos} minutos.", cuerpo,
                  "Recibiste este correo porque se pidió recuperar la cuenta del administrador.", contacto), texto


def html_prueba(farmacia: str, nombre: str, usuario: str, email: str, contacto: dict | None = None) -> tuple[str, str]:
    contacto = contacto or {}
    cuerpo = f"""        <p style="margin:0 0 8px;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#16A34A">Todo listo</p>
        <h1 style="margin:0 0 14px;font-size:30px;line-height:38px;font-weight:800;color:{AZUL}">Correo de recuperación activado</h1>
        <p style="margin:0 0 26px;font-size:16px;line-height:25px;color:#334155">Hola <b>{html.escape(nombre)}</b>, a partir de ahora los códigos para recuperar la contraseña del administrador llegarán a este correo.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 34px;border:1px solid #E2E8F0;border-radius:14px;border-collapse:separate">
          <tr>{_dato("Usuario", html.escape(usuario))}{_dato("Correo", html.escape(email))}<td valign="top" style="padding:16px 18px">
            <div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#94A3B8">Activado</div>
            <div style="font-size:15px;font-weight:700;color:#0F172A;margin-top:4px">{_ahora_texto()}</div></td></tr>
        </table>
        <h2 style="margin:0 0 18px;font-size:18px;font-weight:800;color:{AZUL}">Si algún día olvidas tu contraseña</h2>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          {_paso(1, "Pide un código", 'En la pantalla de inicio presiona <b>¿Olvidaste tu contraseña?</b> y elige <b>Enviarme un código por correo</b>.')}
          {_paso(2, "Revisa este correo", "Te llegará un código de 6 dígitos que vence en 15 minutos.")}
          {_paso(3, "¿Sin internet?", "Usa uno de tus <b>códigos de respaldo</b>. Guárdalos en un lugar seguro.")}
          {_paso(4, "¿Un empleado olvidó la suya?", "Ábrelo en <b>Empleados</b> y presiona <b>Generar código</b>; dáselo en persona.")}
        </table>"""
    texto = (f"Hola {nombre}:\n\nA partir de ahora los códigos para recuperar la contraseña del administrador "
             f"({usuario}) del punto de venta de {farmacia} llegarán a {email}.\n")
    return _marco(farmacia, "Los códigos de recuperación llegarán a este correo.", cuerpo,
                  "Recibiste este correo porque se configuró como correo de recuperación.", contacto), texto


# ── envío ─────────────────────────────────────────────────────────────────────
class CorreoError(Exception):
    pass


def nombre_farmacia(db) -> str:
    from app.database.models import Configuracion
    row = db.query(Configuracion).filter(Configuracion.clave == "farmacia_nombre").first()
    nombre = (row.valor if row and row.valor else cfg.PHARMACY_NAME) or "Farmacia"
    return " ".join(nombre.split()).title() if nombre.isupper() else nombre


def smtp_propio(db) -> dict | None:
    from app.database.models import Configuracion
    claves = ("email_smtp_host", "email_smtp_port", "email_smtp_user", "email_smtp_password")
    d = {r.clave: r.valor for r in db.query(Configuracion).filter(Configuracion.clave.in_(claves)).all()}
    return d if d.get("email_smtp_host") and d.get("email_smtp_user") and d.get("email_smtp_password") else None


def construir(tipo: str, farmacia: str, nombre: str, usuario: str, codigo: str = "", email: str = "",
              contacto: dict | None = None) -> tuple[str, str, str]:
    """(asunto, html, texto) del correo."""
    contacto = {k: str(v)[:120] for k, v in (contacto or {}).items() if k in ("telefono", "direccion") and v}
    if tipo == "codigo":
        h, t = html_codigo(farmacia, nombre, usuario, codigo, contacto=contacto)
        return f"{codigo} es tu código para restablecer la contraseña", h, t
    h, t = html_prueba(farmacia, nombre, usuario, email, contacto=contacto)
    return "Correo de recuperación activado", h, t


def contacto_farmacia(db) -> dict:
    from app.database.models import Configuracion
    d = {r.clave: (r.valor or "") for r in db.query(Configuracion).filter(
        Configuracion.clave.in_(("farmacia_telefono", "farmacia_direccion"))).all()}
    tel = re.sub(r"^\s*tel[.:]?\s*", "", d.get("farmacia_telefono", ""), flags=re.I).strip()
    if not re.search(r"\d{7,}", re.sub(r"\D", "", tel)) or set(re.sub(r"\D", "", tel)) <= {"0"}:
        tel = ""                                  # sin teléfono real (p. ej. "Tel: 000-000-0000")
    return {"telefono": tel, "direccion": " ".join(d.get("farmacia_direccion", "").split())[:120]}


def validar_datos(tipo: str, farmacia: str, nombre: str, usuario: str, codigo: str, destinatario: str) -> None:
    if tipo not in ("codigo", "prueba"):
        raise CorreoError("Tipo de correo no válido")
    if tipo == "codigo" and not re.fullmatch(r"\d{6}", codigo or ""):
        raise CorreoError("Código no válido")
    if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", destinatario or "") or len(destinatario) > 120:
        raise CorreoError("Correo no válido")
    for v in (farmacia, nombre, usuario):
        if not v or len(v) > 80:
            raise CorreoError("Datos no válidos")


def enviar(tipo: str, destinatario: str, farmacia: str, nombre: str, usuario: str,
           codigo: str = "", smtp: dict | None = None, contacto: dict | None = None) -> str:
    """Envía con el SMTP de la farmacia si lo tiene; si no, por el servicio del sistema.
    Devuelve 'propio' o 'sistema'."""
    validar_datos(tipo, farmacia, nombre, usuario, codigo, destinatario)
    portada = portada_png(farmacia)
    if smtp:
        asunto, html_txt, texto = construir(tipo, farmacia, nombre, usuario, codigo, destinatario, contacto)
        from app.services.email_service import enviar_email_html
        enviar_email_html(smtp_host=smtp["email_smtp_host"], smtp_port=int(smtp.get("email_smtp_port") or 587),
                          smtp_user=smtp["email_smtp_user"], smtp_password=smtp["email_smtp_password"],
                          destinatario=destinatario, asunto=asunto, html_txt=html_txt, texto=texto,
                          remitente_nombre=farmacia, imagenes={"portada": portada})
        return "propio"
    import base64
    import requests
    datos = {"tipo": tipo, "destinatario": destinatario, "farmacia": farmacia, "nombre": nombre,
             "usuario": usuario, "codigo": codigo, "portada": base64.b64encode(portada).decode(),
             "telefono": (contacto or {}).get("telefono", ""), "direccion": (contacto or {}).get("direccion", "")}
    try:
        r = requests.post(RELAY_URL, json=datos, timeout=25)
    except requests.RequestException:
        raise CorreoError("Sin conexión a internet para enviar el correo. Usa un código de respaldo.")
    if r.status_code != 200:
        try:
            det = r.json().get("detail", "")
        except Exception:
            det = ""
        raise CorreoError(det or f"El servicio de correo no respondió ({r.status_code}). Intenta más tarde.")
    return "sistema"
