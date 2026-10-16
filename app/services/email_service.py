"""Envío de correo genérico vía SMTP (sin dependencias externas)."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


class EmailError(Exception):
    pass


def enviar_email(
    *, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
    destinatario: str, asunto: str, cuerpo: str,
    archivos_adjuntos: list[tuple[str, bytes]] | None = None,
) -> None:
    if not (smtp_host and smtp_user and smtp_password):
        raise EmailError("Configura tu servidor SMTP (host, usuario, contraseña) antes de enviar correos")
    if not destinatario:
        raise EmailError("Falta el correo del destinatario")

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    for nombre, contenido in (archivos_adjuntos or []):
        parte = MIMEApplication(contenido, Name=nombre)
        parte["Content-Disposition"] = f'attachment; filename="{nombre}"'
        msg.attach(parte)

    try:
        # Puerto 465 = SSL implícito desde la conexión (no STARTTLS) — proveedores
        # comunes (ej. Hostinger, algunos de Gmail/Outlook alternativos) lo exigen.
        # Usar STARTTLS ahí falla con un error críptico de protocolo sin pista de la causa.
        if int(smtp_port) == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, [destinatario], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, [destinatario], msg.as_string())
    except Exception as e:
        raise EmailError(f"Error enviando correo: {e}")


def enviar_email_html(
    *, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
    destinatario: str, asunto: str, html_txt: str, texto: str = "",
    remitente_nombre: str = "", imagenes: dict[str, bytes] | None = None, timeout: int = 15,
) -> None:
    """Correo con diseño (HTML + texto plano de respaldo). `imagenes`: {cid: png} que el HTML
    usa como src="cid:..." — van incrustadas en el correo (Gmail no muestra imágenes en base64)."""
    from email.mime.image import MIMEImage
    from email.utils import formataddr
    if not (smtp_host and smtp_user and smtp_password):
        raise EmailError("Configura tu servidor SMTP (host, usuario, contraseña) antes de enviar correos")
    raiz = MIMEMultipart("related")
    raiz["From"] = formataddr((remitente_nombre, smtp_user)) if remitente_nombre else smtp_user
    raiz["To"] = destinatario
    raiz["Subject"] = asunto
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(texto or asunto, "plain", "utf-8"))
    alt.attach(MIMEText(html_txt, "html", "utf-8"))
    raiz.attach(alt)
    for cid, datos in (imagenes or {}).items():
        img = MIMEImage(datos, "png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        raiz.attach(img)
    if int(smtp_port) == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [destinatario], raiz.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [destinatario], raiz.as_string())
