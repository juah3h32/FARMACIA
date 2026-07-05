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
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [destinatario], msg.as_string())
    except Exception as e:
        raise EmailError(f"Error enviando correo: {e}")
